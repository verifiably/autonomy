"""The proxy's request handling (envelope design decision 13). Each actor connection
carries one request, checked in the spec's order, framed by the proxy, streamed back
and recorded. The close transition and every socket the server opened belong to the
server. The control loop that decides when to close is in `proxy`."""

from __future__ import annotations

import json
import socket
import ssl
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from autonomy.baseline import utc_now, write_all
from autonomy.egress.dialect import check_body, parse_body
from autonomy.egress.errors import Refused
from autonomy.egress.request import MAX_HEAD, forwarded_headers, frame, parse_head, refusal
from autonomy.egress.route import Operation, Route
from autonomy.egress.upstream import (
    ActorGone, Gate, RouteClosed, UpstreamError, connect, cut, read_response, response_head, send_all,
)

JOIN_TIMEOUT = 2.0


class Recorder:
    """`egress.jsonl`: one line per request, written when it ends, then the closing line,
    which is always last. A worker still running after the close's bounded join gets
    its line from the close (`ProxyServer.close`); nothing is written after it."""

    def __init__(self, fd: int) -> None:
        self._fd = fd
        self._lock = threading.Lock()
        self._closed = False

    def line(self, record: Mapping[str, object]) -> None:
        data = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        with self._lock:
            if self._closed:
                return
            if "closed" in record:
                self._closed = True
            write_all(self._fd, data)


class Allowance(Protocol):
    """autonomy-9e8a43's join points (decision 13): `admit` before any byte goes
    upstream, `settle` when the response stream ends, however it ended."""

    def admit(self, run: str, operation: Operation, model: str, request_bytes: int, in_flight: int) -> str | None: ...

    def settle(self, seq: int, upstream_request_id: str | None, usage: Mapping[str, object] | None) -> None: ...


class NoAllowance:
    """Until an allowance exists, `admit` allows every request the route permits and
    `settle` does nothing beyond the record line."""

    def admit(self, run: str, operation: Operation, model: str, request_bytes: int, in_flight: int) -> str | None:
        return None

    def settle(self, seq: int, upstream_request_id: str | None, usage: Mapping[str, object] | None) -> None:
        return None


def _no_hold(stage: str, seq: int) -> None:
    return None


@dataclass(frozen=True)
class Hooks:
    """A test seam: `hold(stage, seq)` runs at each stage before a request's first byte
    goes upstream: `parsed`, `body-checked`, `admit`, `connecting`, `before-send`."""

    hold: Callable[[str, int], None] = _no_hold


def _bad_gateway(message: str) -> bytes:
    body = json.dumps({"type": "error", "error": {"type": "egress_upstream", "message": message}}).encode()
    head = (
        "HTTP/1.1 502 Bad Gateway\r\ncontent-type: application/json\r\n"
        f"content-length: {len(body)}\r\nconnection: close\r\n\r\n"
    )
    return head.encode("ascii") + body


_CLOSED_BEFORE = "the route closed before this request went upstream"


class ProxyServer:
    def __init__(
        self, route: Route, credential: str, recorder: Recorder, *, context: ssl.SSLContext, run: str = "",
        allowance: Allowance | None = None, hooks: Hooks = Hooks(),
    ) -> None:
        self.route = route
        self.recorder = recorder
        self.gate = Gate()
        self._run = run
        self._credential = credential
        self._context = context
        self._allowance = allowance or NoAllowance()
        self._hooks = hooks
        self._listener: socket.socket | None = None
        self._actors: set[socket.socket] = set()
        self._upstreams: set[socket.socket] = set()
        self._threads: list[threading.Thread] = []
        self._outstanding: dict[int, dict[str, object]] = {}
        self._shut = False
        self._in_flight = 0
        self._lock = threading.Lock()
        self._thread = threading.Thread  # a test seam: the class that runs each worker

    # -- lifecycle -----------------------------------------------------------------

    def serve(self, listener: socket.socket) -> None:
        self._listener = listener
        if not self._start(self._accept):
            listener.close()

    def close(self, cause: str) -> bool:
        """The close transition, then: stop accepting, cut every upstream socket, shut
        each actor connection for reading (a worker waiting on the actor wakes, and a
        cancelled request can still be answered `route-closed`), join the workers for
        at most `JOIN_TIMEOUT`, and write the closing line. Nothing here waits on a
        peer."""
        if not self.gate.close(cause):
            return False
        with self._lock:
            self._shut = True
            actors = list(self._actors)
            upstreams = list(self._upstreams)
            threads = list(self._threads)
        if self._listener is not None:
            cut(self._listener)
            self._listener.close()
        for sock in upstreams:
            cut(sock)
        for sock in actors:
            cut(sock, socket.SHUT_RD)
        self._join(threads, JOIN_TIMEOUT)
        with self._lock:
            survivors = list(self._actors)
        for sock in survivors:  # a worker blocked writing to an actor that stopped reading
            cut(sock)
        self._join(threads, 0.5)
        with self._lock:
            # A worker still running (a DNS lookup that has not returned) must not lose
            # its request's line: write it now, as cut, and suppress the worker's own.
            for _, live in sorted(self._outstanding.items()):
                record = dict(live)
                record["ended"] = "route-closed"
                if not record["forwarded"]:
                    record["refused"] = "route-closed"
                self.recorder.line(record)
            self._outstanding.clear()  # their workers' own lines are now never written
            self.recorder.line({"at": utc_now(), "closed": cause, "last_seq": self.gate.last_seq})
        return True

    @staticmethod
    def _join(threads: list[threading.Thread], seconds: float) -> None:
        deadline = time.monotonic() + seconds
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(max(0.0, deadline - time.monotonic()))

    def _start(self, target: Callable[..., None], *args: object) -> bool:
        """Register and start a worker in one step under the lock the close takes, so
        the close never joins a thread that has not started. None starts after it."""
        thread = self._thread(target=target, args=args, daemon=True)
        with self._lock:
            if self._shut:
                return False
            self._threads = [t for t in self._threads if t.is_alive()]
            self._threads.append(thread)
            thread.start()
        return True

    def _finish(self, record: dict[str, object]) -> None:
        """Write a request's line, unless the close already wrote it: an accepted
        request is outstanding until one of the two writes its line."""
        with self._lock:
            seq = record["seq"]
            if seq is not None and self._outstanding.pop(int(seq), None) is None:
                return
            self.recorder.line(record)

    def _track(self, sock: socket.socket, *, upstream: bool) -> bool:
        with self._lock:
            if self._shut:
                return False
            (self._upstreams if upstream else self._actors).add(sock)
            return True

    def _release(self, sock: socket.socket) -> None:
        with self._lock:
            self._actors.discard(sock)
            self._upstreams.discard(sock)
        cut(sock)
        sock.close()

    def _accept(self) -> None:
        assert self._listener is not None
        while True:
            try:
                conn, _ = self._listener.accept()
            except OSError:
                return
            if not self._track(conn, upstream=False):
                conn.close()
                return
            if not self._start(self._handle, conn):
                self._release(conn)
                return

    # -- the actor's side ------------------------------------------------------------

    @staticmethod
    def _recv(conn: socket.socket) -> bytes:
        try:
            return conn.recv(65536)
        except OSError as caught:
            raise ActorGone() from caught

    @staticmethod
    def _to_actor(conn: socket.socket, data: bytes) -> None:
        try:
            conn.sendall(data)
        except OSError as caught:
            raise ActorGone(attempted=True) from caught

    @staticmethod
    def _answer(conn: socket.socket, data: bytes) -> None:
        try:
            conn.sendall(data)
        except OSError:
            pass

    def _read_head(self, conn: socket.socket) -> tuple[bytes, bytes] | None:
        buffer = b""
        while (at := buffer.find(b"\r\n\r\n")) < 0:
            if len(buffer) > MAX_HEAD:
                raise Refused("request-malformed", f"a request head over {MAX_HEAD} bytes")
            chunk = self._recv(conn)
            if not chunk:
                if not buffer:
                    return None
                raise ActorGone()
            buffer += chunk
        if at > MAX_HEAD:
            raise Refused("request-malformed", f"a request head over {MAX_HEAD} bytes")
        return buffer[:at], buffer[at + 4:]

    def _read_body(self, conn: socket.socket, rest: bytes, length: int) -> bytes:
        """Exactly `length` bytes. Anything after them (a pipelined request) is never
        parsed: the connection closes after this one response."""
        body = bytearray(rest[:length])
        while len(body) < length:
            chunk = self._recv(conn)
            if not chunk:
                raise ActorGone()
            body += chunk[: length - len(body)]
        return bytes(body)

    # -- one request -----------------------------------------------------------------

    def _handle(self, conn: socket.socket) -> None:
        record: dict[str, object] = {
            "at": utc_now(), "seq": None, "method": None, "path": None, "query": None, "model": None,
            "status": None, "refused": None, "upstream_request_id": None, "request_bytes": 0,
            "response_bytes": 0, "forwarded": False, "ended": "complete",
        }
        upstream: socket.socket | None = None
        answered = False
        request_id: str | None = None

        def closed_before_upstream() -> None:
            record.update(refused="route-closed", status=403)
            self._answer(conn, refusal("route-closed", _CLOSED_BEFORE))

        try:
            head = self._read_head(conn)
            if head is None:
                return  # closed before a request: nothing to record
            record["at"] = utc_now()
            with self._lock:  # one step: the close's finalization sees every seq the gate has handed out
                seq = self.gate.next_seq()
                if seq is not None:
                    record["seq"] = seq
                    self._outstanding[seq] = record
            if seq is None:
                raise Refused("route-closed", "the route is closed")
            request = parse_head(head[0])
            record.update(method=request.method, path=request.path, query=request.query)
            if request.content_length > self.route.max_request_bytes:
                raise Refused(
                    "request-too-large",
                    f"{request.content_length} bytes; the route allows {self.route.max_request_bytes}",
                )
            op = self.route.operation(request.method, request.path, request.query)
            if op is None:
                target = request.path + (f"?{request.query}" if request.query else "")
                raise Refused(
                    "operation-refused",
                    f"{request.method} {target} is not an operation of the route; it allows {self.route.describe()}",
                )
            headers = forwarded_headers(request, self.route)
            self._hooks.hold("parsed", seq)
            body = self._read_body(conn, head[1], request.content_length)
            record["request_bytes"] = len(body)
            parsed = parse_body(body)
            if isinstance(parsed.get("model"), str):
                record["model"] = parsed["model"]
            check_body(parsed, op)
            self._hooks.hold("body-checked", seq)
            with self._lock:
                self._in_flight += 1
                in_flight = self._in_flight
            try:
                verdict = self._allowance.admit(self._run, op, parsed["model"], len(body), in_flight)
                if verdict is not None:
                    raise Refused("allowance-refused", verdict)
                self._hooks.hold("admit", seq)
                if not self.gate.is_open:
                    raise Refused("route-closed", "the route is closed")
                self._hooks.hold("connecting", seq)
                upstream = connect(self.gate, self.route.host, self.route.port, self._context, watch=conn)
                if not self._track(upstream, upstream=True):
                    raise RouteClosed()
                payload = frame(request, self.route, headers, body, self._credential)
                self._hooks.hold("before-send", seq)
                send_all(self.gate, upstream, payload, watch=conn)
                record["forwarded"] = True
                response = read_response(self.gate, upstream, watch=conn)
                request_id = response.request_id
                record.update(status=response.status, upstream_request_id=request_id)
                answered = True
                self._to_actor(conn, response_head(response))
                for piece in response.body:
                    self._to_actor(conn, piece)
                    record["response_bytes"] = int(record["response_bytes"]) + len(piece)
            finally:
                with self._lock:
                    self._in_flight -= 1
        except Refused as refused:
            record.update(refused=refused.code, status=403)
            self._answer(conn, refusal(refused.code, refused.message))
        except RouteClosed as closed:
            record["ended"] = "route-closed"
            if closed.attempted or closed.sent:
                record["forwarded"] = True
            if not record["forwarded"]:
                closed_before_upstream()
        except ActorGone as gone:
            if gone.attempted:
                record["forwarded"] = True
            if self.gate.is_open:
                record["ended"] = "actor-closed"
            else:
                record["ended"] = "route-closed"
                if not record["forwarded"]:
                    closed_before_upstream()  # the close shut only our read side: the answer still goes
        except (UpstreamError, OSError) as caught:
            if getattr(caught, "attempted", False):
                record["forwarded"] = True
            if not self.gate.is_open:
                record["ended"] = "route-closed"
                if not record["forwarded"]:
                    closed_before_upstream()
            else:
                record["ended"] = "upstream-error"
                if not answered:
                    record["status"] = 502
                    self._answer(conn, _bad_gateway(str(caught)))
        except Exception as caught:  # a defect here must still answer and record, never vanish
            record["ended"] = "upstream-error"
            if not answered:
                record["status"] = 502
                self._answer(conn, _bad_gateway(f"the proxy failed: {type(caught).__name__}"))
        finally:
            if upstream is not None:
                self._release(upstream)
            if record["forwarded"] and record["seq"] is not None:
                self._allowance.settle(int(record["seq"]), request_id, None)
            if record["seq"] is not None or record["refused"] is not None:
                self._finish(record)  # before the actor's EOF, so a reader at EOF sees it
            self._release(conn)
