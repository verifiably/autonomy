"""The proxy's upstream side (envelope design decision 13).

`Gate` holds the route's open flag and the lock that the close transition takes. The
lock is held only for a flag check and one non-blocking call: a write of at most
`SLICE` bytes, a `connect` that returns `EINPROGRESS`, or one handshake step. So the
transition never waits on an upstream, and no byte goes upstream after it, connection
setup included. Every wait (for room to write, for bytes to read, for the connect or
the handshake) happens outside the lock and gives up within `POLL` seconds of the
close. A read off a closed route ends the stream as cut, never as complete.

Bytes already handed to the kernel before the transition may still drain after it:
the boundary is the write call, not the wire."""

from __future__ import annotations

import errno
import os
import re
import select
import socket
import ssl
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from autonomy.egress.route import always_dropped

POLL = 0.2
SLICE = 16 * 1024
MAX_RESPONSE_HEAD = 64 * 1024
_STATUS = re.compile(rb"HTTP/1\.[01] ([0-9]{3})(?: (.*))?")
_HEX = re.compile(rb"[0-9A-Fa-f]{1,16}")
_DIGITS = re.compile(r"[0-9]{1,15}")
_T = TypeVar("_T")


class RouteClosed(Exception):
    """The route closed before this request was done. `sent` bytes were counted as
    written; `attempted` says whether any write was tried while the route was open.
    A TLS write reports no partial progress (OpenSSL's partial-write mode is off in
    CPython), so `attempted` is the honest answer to "did anything go upstream"."""

    def __init__(self, sent: int = 0, attempted: bool = False) -> None:
        super().__init__("the route is closed")
        self.sent = sent
        self.attempted = attempted


class UpstreamError(Exception):
    """The upstream could not be reached, failed TLS verification, or answered
    something that is not HTTP/1.1."""


class ActorGone(Exception):
    """The actor hung up, or its connection broke, while the proxy waited on the
    upstream or wrote to the actor. `attempted` says whether any write upstream was
    tried."""

    def __init__(self, attempted: bool = False) -> None:
        super().__init__("the actor hung up")
        self.attempted = attempted


class SendFailed(UpstreamError):
    """A write failed (a reset, a broken pipe, a TLS error) after `sent` bytes, with
    `attempted` saying whether any write was tried: the record's `forwarded`."""

    def __init__(self, sent: int, attempted: bool, message: str) -> None:
        super().__init__(message)
        self.sent = sent
        self.attempted = attempted


class Gate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open = True
        self._seq = 0
        self.cause: str | None = None
        self.last_seq = 0

    @property
    def is_open(self) -> bool:
        """A hint for waits. Every call that can put a byte upstream rechecks the flag
        under the lock."""
        return self._open

    def next_seq(self) -> int | None:
        with self._lock:
            if not self._open:
                return None
            self._seq += 1
            return self._seq

    def close(self, cause: str) -> bool:
        """The close transition: no byte goes upstream after it returns."""
        with self._lock:
            if not self._open:
                return False
            self._open = False
            self.cause = cause
            self.last_seq = self._seq
            return True

    def attempt(self, sock: socket.socket, data: memoryview) -> int | None:
        """One non-blocking write while the route is open; None once it is closed."""
        with self._lock:
            if not self._open:
                return None
            return sock.send(data)

    def call(self, step: Callable[[], _T]) -> _T:
        """One non-blocking step that may put bytes upstream (a connect, a handshake
        step), only while the route is open. Raises `RouteClosed` once it is closed."""
        with self._lock:
            if not self._open:
                raise RouteClosed()
            return step()


def _wait(
    gate: Gate, sock: socket.socket, *, readable: bool, deadline: float | None = None,
    watch: socket.socket | None = None,
) -> None:
    """Wait for `sock`, giving up within `POLL` of the close. `watch` is the actor's
    connection: an actor that hangs up while the upstream is silent raises
    `ActorGone`, so its upstream request does not run on unseen. Bytes the actor sends
    meanwhile are never parsed (one request per connection): they are dropped."""
    while gate.is_open:
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError()
        reads = [sock] if readable else []
        if watch is not None:
            reads.append(watch)
        ready_read, ready_write, _ = select.select(reads, [] if readable else [sock], [], POLL)
        if watch is not None and watch in ready_read:
            try:
                data = watch.recv(65536)
            except OSError:
                data = b""
            if not data:
                raise ActorGone()
            ready_read = [item for item in ready_read if item is not watch]
        if ready_read or ready_write:
            return
    raise RouteClosed()


def send_all(gate: Gate, sock: socket.socket, data: bytes, *, watch: socket.socket | None = None) -> None:
    """Write `data` in non-blocking attempts of at most `SLICE` bytes under the gate's
    lock. A TLS write that needs a read or a write first, or a full buffer, waits
    outside the lock and retries the same slice (OpenSSL requires the same bytes),
    rechecking the flag."""
    view = memoryview(data)
    sent = 0
    attempted = False
    while sent < len(data):
        piece = view[sent : sent + SLICE]
        try:
            written = gate.attempt(sock, piece)
        except ssl.SSLWantReadError:
            attempted, readable = True, True
        except (ssl.SSLWantWriteError, BlockingIOError, InterruptedError):
            attempted, readable = True, False
        except OSError as caught:  # after the SSLWant*/BlockingIOError clauses, which are OSErrors too
            raise SendFailed(sent, True, f"the write upstream failed: {caught}") from caught
        else:
            if written is None:
                raise RouteClosed(sent, attempted)
            attempted = True
            sent += written
            continue
        try:
            _wait(gate, sock, readable=readable, watch=watch)
        except RouteClosed:
            raise RouteClosed(sent, attempted) from None
        except ActorGone:
            raise ActorGone(attempted) from None


def tls_context(ca_file: Path | None) -> ssl.SSLContext:
    """Verification on, always: the system trust store, or the route's `ca_file`."""
    return ssl.create_default_context(cafile=str(ca_file) if ca_file is not None else None)


def cut(sock: socket.socket, how: int = socket.SHUT_RDWR) -> None:
    """Shut a socket down at its descriptor. `SSLSocket.shutdown` would drop its TLS
    state under a read in another thread, which then reads raw bytes as plaintext:
    the base method leaves it, and that read fails or sees EOF."""
    try:
        socket.socket.shutdown(sock, how)
    except OSError:
        pass


def _open(gate: Gate, host: str, port: int, deadline: float, watch: socket.socket | None) -> socket.socket:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as caught:
        raise UpstreamError(f"cannot resolve {host}: {caught}") from caught
    last: OSError | None = None
    for family, kind, proto, _, address in infos:
        try:
            sock = socket.socket(family, kind, proto)
        except OSError as caught:  # an address family this kernel lacks: try the next
            last = caught
            continue
        sock.setblocking(False)
        try:
            code = gate.call(lambda: sock.connect_ex(address))
            if code not in (0, errno.EINPROGRESS):
                raise OSError(code, os.strerror(code))
            _wait(gate, sock, readable=False, deadline=deadline, watch=watch)
            code = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if code:
                raise OSError(code, os.strerror(code))
            return sock
        except TimeoutError:  # an OSError too: the deadline ends every address, not just this one
            sock.close()
            raise
        except OSError as caught:
            sock.close()
            last = caught
        except BaseException:
            sock.close()
            raise
    raise UpstreamError(f"cannot reach {host}:{port}: {last}")


def connect(
    gate: Gate, host: str, port: int, context: ssl.SSLContext, *, timeout: float = 30.0,
    watch: socket.socket | None = None,
) -> ssl.SSLSocket:
    """Every wait here also watches the actor (`watch`): a hangup during the TCP
    connect or the TLS handshake raises `ActorGone`, which nothing has sent upstream."""
    deadline = time.monotonic() + timeout
    try:
        raw = _open(gate, host, port, deadline, watch)
    except TimeoutError:
        raise UpstreamError(f"connecting to {host}:{port} took over {timeout:g} s") from None
    tls = context.wrap_socket(raw, server_hostname=host, do_handshake_on_connect=False)
    try:
        while True:
            try:
                gate.call(tls.do_handshake)
                return tls
            except ssl.SSLWantReadError:
                readable = True
            except ssl.SSLWantWriteError:
                readable = False
            except ssl.SSLError as caught:
                raise UpstreamError(f"TLS with {host}: {caught}") from caught
            except OSError as caught:
                raise UpstreamError(f"the TLS handshake with {host} failed: {caught}") from caught
            try:
                _wait(gate, tls, readable=readable, deadline=deadline, watch=watch)
            except TimeoutError:
                raise UpstreamError(f"the TLS handshake with {host} took over {timeout:g} s") from None
    except BaseException:
        tls.close()
        raise


class _Reader:
    def __init__(self, gate: Gate, sock: socket.socket, watch: socket.socket | None) -> None:
        self._gate = gate
        self._sock = sock
        self._watch = watch
        self.buffer = bytearray()

    def _fill(self) -> bool:
        while True:
            try:
                chunk = self._sock.recv(65536)
            except ssl.SSLWantReadError:
                self._wait(readable=True)
                continue
            except ssl.SSLWantWriteError:
                self._wait(readable=False)
                continue
            except (BlockingIOError, InterruptedError):
                self._wait(readable=True)
                continue
            except (ssl.SSLEOFError, ssl.SSLZeroReturnError):
                chunk = b""
            if not chunk:
                if not self._gate.is_open:
                    raise RouteClosed(attempted=True)
                return False
            self.buffer += chunk
            return True

    def _wait(self, *, readable: bool) -> None:
        try:
            _wait(self._gate, self._sock, readable=readable, watch=self._watch)
        except ActorGone:
            raise ActorGone(attempted=True) from None  # the request already went upstream

    def until(self, marker: bytes, limit: int) -> bytes:
        while (at := self.buffer.find(marker)) < 0:
            if len(self.buffer) > limit:
                raise UpstreamError(f"the upstream sent over {limit} bytes without {marker!r}")
            if not self._fill():
                raise UpstreamError("the upstream closed mid-head")
        if at > limit:
            raise UpstreamError(f"the upstream sent over {limit} bytes before {marker!r}")
        found = bytes(self.buffer[:at])
        del self.buffer[: at + len(marker)]
        return found

    def exactly(self, count: int) -> Iterator[bytes]:
        while count:
            if not self.buffer and not self._fill():
                raise UpstreamError("the upstream closed mid-body")
            piece = bytes(self.buffer[:count])
            del self.buffer[: len(piece)]
            count -= len(piece)
            yield piece

    def rest(self) -> Iterator[bytes]:
        while True:
            if self.buffer:
                piece = bytes(self.buffer)
                self.buffer.clear()
                yield piece
            if not self._fill():
                return


def _chunked(reader: _Reader) -> Iterator[bytes]:
    while True:
        size_text = reader.until(b"\r\n", 1024).split(b";", 1)[0].strip()
        if not _HEX.fullmatch(size_text):
            raise UpstreamError("a chunk size that is not hex")
        size = int(size_text, 16)
        if size == 0:
            while reader.until(b"\r\n", 8192):
                pass
            return
        yield from reader.exactly(size)
        if reader.until(b"\r\n", 16):
            raise UpstreamError("a chunk without its CRLF")


@dataclass
class Response:
    status: int
    reason: str
    headers: tuple[tuple[str, str], ...]
    body: Iterator[bytes]

    @property
    def request_id(self) -> str | None:
        return next((value for name, value in self.headers if name == "request-id"), None)


def read_response(gate: Gate, sock: socket.socket, *, watch: socket.socket | None = None) -> Response:
    reader = _Reader(gate, sock, watch)
    while True:
        head = reader.until(b"\r\n\r\n", MAX_RESPONSE_HEAD)
        status_line, *lines = head.split(b"\r\n")
        match = _STATUS.fullmatch(status_line)
        if match is None:
            raise UpstreamError(f"not an HTTP/1.1 status line: {status_line[:80]!r}")
        headers: list[tuple[str, str]] = []
        for line in lines:
            name, colon, value = line.partition(b":")
            if not colon or not name or name != name.strip() or b"\n" in value or b"\r" in value:
                raise UpstreamError("a malformed response header")
            headers.append((name.decode("latin-1").lower(), value.strip(b" \t").decode("latin-1")))
        status = int(match[1])
        if 100 <= status < 200:
            continue  # an interim response: the final one follows
        break
    reason = (match[2] or b"").decode("latin-1")
    codings = [value for name, value in headers if name == "transfer-encoding"]
    lengths = [value for name, value in headers if name == "content-length"]
    if status in (204, 304):
        body: Iterator[bytes] = iter(())
    elif codings:
        if codings[-1].split(",")[-1].strip().lower() != "chunked":
            raise UpstreamError(f"a transfer coding the proxy does not decode: {codings[-1]}")
        body = _chunked(reader)
    elif lengths:
        if len(set(lengths)) != 1 or not _DIGITS.fullmatch(lengths[0]):
            raise UpstreamError("an unusable Content-Length")
        body = reader.exactly(int(lengths[0]))
    else:
        body = reader.rest()
    return Response(status, reason, tuple(headers), body)


def response_head(response: Response) -> bytes:
    """The head the actor gets: the upstream's end-to-end headers, less the
    always-dropped set and any header its `Connection` names, and the proxy's own
    framing (the body ends at close)."""
    hop = frozenset(
        token.strip(" \t").lower()
        for name, value in response.headers if name == "connection"
        for token in value.split(",") if token.strip(" \t")
    )
    lines = [f"HTTP/1.1 {response.status} {response.reason}".rstrip()]
    lines += [f"{name}: {value}" for name, value in response.headers if not always_dropped(name) and name not in hop]
    lines.append("connection: close")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
