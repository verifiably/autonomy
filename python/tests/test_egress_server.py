import errno
import json
import os
import socket
import threading
import time

import pytest

import autonomy.egress.server as server_module
from egress_fixtures import (  # noqa: F401  (tls, serve and served are fixtures)
    CANARY, MODEL, PI_BETAS, exchange, message, raw_request, serve, served, status_and_body, tls,
)
from autonomy.egress.server import Hooks
from autonomy.egress.upstream import Gate


def test_an_allowed_request_streams_as_it_arrives(serve):  # E21
    s = serve(mode="sse")
    s.upstream.events, s.upstream.gap = 5, 0.3
    body = json.dumps(message()).encode()
    first_at = None
    received = b""
    with socket.create_connection(("127.0.0.1", s.port), timeout=10) as sock:
        sock.sendall(raw_request(body=body, headers=[("x-api-key", "placeholder")]))
        while chunk := sock.recv(65536):
            received += chunk
            if first_at is None and b"event: message" in received:
                first_at = time.monotonic()
    s.server.close("close")
    assert first_at is not None and first_at < s.upstream.last_event_at
    assert received.count(b"event: message") == 5
    (seen,) = s.upstream.seen
    assert seen.headers["host"] == [f"localhost:{s.upstream.port}"]
    assert seen.headers["x-api-key"] == [CANARY]
    assert "authorization" not in seen.headers
    assert seen.body == body
    line = s.records()[0]
    assert (line["seq"], line["status"], line["forwarded"], line["ended"], line["refused"]) == (1, 200, True, "complete", None)
    assert line["upstream_request_id"] == "req_sse" and line["model"] == MODEL and line["response_bytes"] > 0


REFUSED = {
    "CONNECT": (raw_request(method="CONNECT", target="api.anthropic.com:443"), "target-refused"),
    "absolute-form": (raw_request(target="http://other/v1/messages?beta=true", body=message()), "target-refused"),
    "authority-form": (raw_request(target="other:443", body=message()), "target-refused"),
    "dot-dot": (raw_request(target="/v1/messages/../x?beta=true", body=message()), "operation-refused"),
    "encoded dot-dot": (raw_request(target="/v1/%2e%2e/x?beta=true", body=message()), "operation-refused"),
    "double slash": (raw_request(target="//other/v1/messages?beta=true", body=message()), "operation-refused"),
    "dot segment": (raw_request(target="/v1/messages/./?beta=true", body=message()), "operation-refused"),
    "query outside the route": (raw_request(target="/v1/messages", body=message()), "operation-refused"),
    "model outside the route": (raw_request(body=message(model="claude-opus-5-5")), "model-refused"),
    "upgrade": (raw_request(headers=[("upgrade", "h2c")], body=message()), "target-refused"),
    "chunked smuggle": (raw_request(
        headers=[("transfer-encoding", "chunked")],
        body=b"0\r\n\r\nPOST /v1/admin HTTP/1.1\r\nhost: x\r\ncontent-length: 0\r\n\r\n"), "request-malformed"),
    "too large": (raw_request(headers=[("content-length", "9000000")]), "request-too-large"),
    "mcp servers": (raw_request(body=message(mcp_servers=[{"type": "url", "url": "https://x", "name": "x"}])), "body-refused"),
    "web fetch": (raw_request(body=message(tools=[{"type": "web_fetch_20250910", "name": "web_fetch"}])), "body-refused"),
    "url source": (raw_request(body=message(messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "url", "url": "https://x/i.png"}}]}])), "body-refused"),
    "file source": (raw_request(body=message(messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "file", "file_id": "f"}}]}])), "body-refused"),
    "unlisted block": (raw_request(body=message(messages=[{"role": "user", "content": [
        {"type": "search_result", "content": []}]}])), "body-refused"),
    "unlisted block in a tool result": (raw_request(body=message(messages=[{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t", "content": [{"type": "search_result"}]}]}])), "body-refused"),
    "unlisted beta": (raw_request(headers=[("anthropic-beta", "mcp-client-2025-04-04")], body=message()), "header-refused"),
    "beta on two lines": (raw_request(headers=[("anthropic-beta", PI_BETAS[0]), ("anthropic-beta", "mcp-client-2025-04-04")],
                                      body=message()), "header-refused"),
    "beta in two cases": (raw_request(headers=[("anthropic-beta", PI_BETAS[0]), ("Anthropic-Beta", PI_BETAS[0])],
                                      body=message()), "header-refused"),
    "unlisted version": (raw_request(headers=[("anthropic-version", "2099-01-01")], body=message())
                         .replace(b"anthropic-version: 2023-06-01\r\n", b"", 1), "header-refused"),
    "model twice": (raw_request(body=b'{"model": "%s", "model": "claude-opus-5-5", "messages": []}' % MODEL.encode()),
                    "request-malformed"),
    "byte-order mark": (raw_request(body=b"\xef\xbb\xbf" + json.dumps(message()).encode()), "request-malformed"),
    "NaN": (raw_request(body=b'{"model": "%s", "temperature": NaN}' % MODEL.encode()), "request-malformed"),
}


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_refused_requests_never_reach_the_upstream(served, case):  # E21
    data, code = REFUSED[case]
    status, body = status_and_body(exchange(served.port, data))
    assert status == 403
    assert json.loads(body)["error"]["code"] == code
    assert served.upstream.seen == [] and served.upstream.connections == 0
    assert served.records()[0]["refused"] == code


def test_an_operation_refusal_names_the_routes_operations(served):
    _, body = status_and_body(exchange(served.port, raw_request(target="/v1/complete", body=message())))
    assert "POST /v1/messages?beta=true" in json.loads(body)["error"]["message"]


def test_actor_credentials_are_stripped_and_replaced(served):  # E21
    exchange(served.port, raw_request(body=message(), headers=[
        ("connection", "x-api-key"), ("x-api-key", "placeholder"), ("authorization", "Bearer sk-ant-oat01-x"),
        ("x-probe", "1"), ("cookie", "c=1"),
    ]))
    (seen,) = served.upstream.seen
    assert seen.headers["x-api-key"] == [CANARY]
    for name in ("authorization", "x-probe", "cookie"):
        assert name not in seen.headers
    assert seen.headers["connection"] == ["close"]


def test_destination_overrides_reach_only_the_upstream(served):  # E21
    for headers in ([("host", "other")], [("x-forwarded-host", "other")], [("forwarded", "host=other")]):
        data = raw_request(body=message(), headers=headers).replace(b"host: 127.0.0.1:4780\r\n", b"", 1)
        assert status_and_body(exchange(served.port, data))[0] == 200
    assert len(served.upstream.seen) == 3
    assert all(seen.headers["host"] == [f"localhost:{served.upstream.port}"] for seen in served.upstream.seen)
    assert served.other.connections == 0


def test_a_redirect_returns_to_the_actor_and_is_never_followed(serve):  # E21
    s = serve(mode="redirect")
    answer = exchange(s.port, raw_request(body=message()))
    s.server.close("close")
    assert status_and_body(answer)[0] == 302
    assert s.other.origin.encode() in answer
    assert s.other.connections == 0


def test_a_pipelined_second_request_is_never_parsed(served):  # Review Focus 1
    second = raw_request(target="/v1/complete", body=message())
    answer = exchange(served.port, raw_request(body=message()) + second)
    assert answer.count(b"HTTP/1.1 ") == 1
    assert len(served.upstream.seen) == 1
    assert [line["seq"] for line in served.records()] == [1]


def test_an_actor_that_hangs_up_mid_stream_ends_its_request(serve):  # Review Focus 3
    s = serve(mode="sse")
    s.upstream.events, s.upstream.gap = 20, 0.2
    with socket.create_connection(("127.0.0.1", s.port), timeout=10) as sock:
        sock.sendall(raw_request(body=message()))
        received = b""
        while b"event: message" not in received:
            chunk = sock.recv(65536)
            if not chunk:
                break
            received += chunk
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not s.records():
        time.sleep(0.1)
    s.server.close("close")
    assert s.records()[0]["ended"] == "actor-closed"
    assert not s.server._actors and not s.server._upstreams


def test_twenty_concurrent_requests_are_all_served(serve):  # Review Focus 4
    seen_in_flight = []

    class Spy:
        def admit(self, run, operation, model, request_bytes, in_flight):
            assert run == "run-test"
            seen_in_flight.append(in_flight)
            time.sleep(0.05)
            return None

        def settle(self, seq, upstream_request_id, usage):
            return None

    s = serve(allowance=Spy())
    answers = []
    threads = [threading.Thread(target=lambda: answers.append(exchange(s.port, raw_request(body=message()))))
               for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    s.server.close("close")
    assert len(answers) == 20 and all(status_and_body(a)[0] == 200 for a in answers)
    seqs = sorted(line["seq"] for line in s.records() if "closed" not in line)
    assert seqs == list(range(1, 21))
    assert max(seen_in_flight) > 1


def test_an_allowance_refusal_is_answered_and_never_forwarded(serve):
    class Refuse:
        def admit(self, run, operation, model, request_bytes, in_flight):
            return "the run's allowance is spent"

        def settle(self, seq, upstream_request_id, usage):
            raise AssertionError("never settled")

    s = serve(allowance=Refuse())
    status, body = status_and_body(exchange(s.port, raw_request(body=message())))
    s.server.close("close")
    assert status == 403 and json.loads(body)["error"]["code"] == "allowance-refused"
    assert s.upstream.seen == []


class Holder:
    """Blocks request 1 at one stage until released, and says when it got there."""

    def __init__(self, stage: str) -> None:
        self.stage = stage
        self.reached = threading.Event()
        self.release = threading.Event()

    def __call__(self, stage: str, seq: int) -> None:
        if stage == self.stage and seq == 1:
            self.reached.set()
            assert self.release.wait(20)


def close_while_held(s, holder: Holder) -> bytes:
    answer = {}
    client = threading.Thread(target=lambda: answer.setdefault("raw", exchange(s.port, raw_request(body=message()))))
    client.start()
    assert holder.reached.wait(10)
    closer = threading.Thread(target=s.server.close, args=("close",))
    closer.start()
    deadline = time.monotonic() + 5
    while s.server.gate.is_open and time.monotonic() < deadline:
        time.sleep(0.01)
    holder.release.set()
    closer.join(10)
    client.join(10)
    return answer["raw"]


@pytest.mark.parametrize("stage", ["before-send", "connecting", "admit", "body-checked"])
def test_a_request_held_before_its_first_byte_never_goes_upstream(serve, stage):  # E22
    holder = Holder(stage)
    s = serve(hooks=Hooks(hold=holder))
    raw = close_while_held(s, holder)
    status, body = status_and_body(raw)
    assert status == 403 and json.loads(body)["error"]["code"] == "route-closed"
    assert s.upstream.seen == []
    held, closing = s.records()
    assert (held["seq"], held["refused"], held["forwarded"]) == (1, "route-closed", False)
    assert (held["ended"], held["status"]) == ("route-closed", 403)  # decision 13
    assert closing["closed"] == "close" and held["seq"] <= closing["last_seq"]


def test_a_check_only_at_acceptance_would_send_after_the_close(serve, monkeypatch):
    # Negative (E22): a gate whose write ignores the flag sends the held request, though
    # its seq still passes the last_seq check.
    monkeypatch.setattr(Gate, "attempt", lambda self, sock, data: sock.send(data))
    monkeypatch.setattr(server_module, "cut", lambda sock, how=socket.SHUT_RDWR: None)  # nor cuts
    holder = Holder("before-send")
    s = serve(hooks=Hooks(hold=holder))
    close_while_held(s, holder)
    time.sleep(0.5)
    assert len(s.upstream.seen) == 1


def test_after_the_close_a_connect_is_refused(served):
    served.server.close("close")
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", served.port), timeout=2)


def test_a_stalled_upstream_never_delays_the_close(serve):  # E22, with the lease in Task 8
    s = serve(mode="stall")
    big = json.dumps(message(system="x" * 6_000_000)).encode()
    client = threading.Thread(target=lambda: exchange(s.port, raw_request(body=big), timeout=30), daemon=True)
    client.start()
    deadline = time.monotonic() + 10
    while not s.upstream.seen and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.5)  # the body fills the buffers; the send waits for room
    started = time.monotonic()
    assert s.server.close("lease")
    assert time.monotonic() - started < 1.0 + 2.0  # the transition at once; joins bounded by JOIN_TIMEOUT
    client.join(5)
    line = s.records()[0]
    assert (line["ended"], line["forwarded"]) == ("route-closed", True)
    assert s.upstream.stalled_bytes() < len(big)


def test_every_forwarded_request_is_settled_and_no_other(serve):
    settled = []

    class Spy:
        def admit(self, run, operation, model, request_bytes, in_flight):
            return None

        def settle(self, seq, upstream_request_id, usage):
            settled.append((seq, upstream_request_id))

    s = serve(allowance=Spy())
    exchange(s.port, raw_request(body=message()))
    exchange(s.port, raw_request(body=message(model="claude-opus-5-5")))
    s.server.close("close")
    assert settled == [(1, "req_json")]


def test_nothing_is_recorded_after_the_closing_line(tmp_path):
    from autonomy.egress.server import Recorder

    path = tmp_path / "egress.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    recorder = Recorder(fd)
    recorder.line({"at": "t", "closed": "close", "last_seq": 0})
    recorder.line({"at": "t", "seq": 1})
    os.close(fd)
    assert len(path.read_text().splitlines()) == 1


def test_a_request_waiting_on_its_body_is_answered_route_closed(serve):
    s = serve()
    data = raw_request(body=message())
    with socket.create_connection(("127.0.0.1", s.port), timeout=10) as sock:
        sock.sendall(data[:-5])  # the proxy waits for the last 5 bytes of the body
        time.sleep(0.3)
        started = time.monotonic()
        s.server.close("close")
        assert time.monotonic() - started < 1.0  # the read side's shutdown wakes the worker
        answer = b""
        while chunk := sock.recv(65536):
            answer += chunk
    status, body = status_and_body(answer)
    assert status == 403 and json.loads(body)["error"]["code"] == "route-closed"
    assert s.records()[0]["refused"] == "route-closed"
    assert s.upstream.seen == []


def test_a_close_racing_a_new_worker_never_joins_an_unstarted_thread(serve, monkeypatch):
    # The close's snapshot of the workers waits on the lock that a start holds until
    # its thread has started: here the close begins while a worker is being started.
    # The join bound is short, so the close reaches the new worker while it is held.
    monkeypatch.setattr(server_module, "JOIN_TIMEOUT", 0.2)
    s = serve()
    outcome = {}
    real = threading.Thread

    def closing():
        try:
            outcome["closed"] = s.server.close("close")
        except BaseException as caught:
            outcome["error"] = caught

    class Racing(real):
        def start(self):
            if getattr(self, "_target", None) == s.server._handle and "closer" not in outcome:
                closer = real(target=closing)
                outcome["closer"] = closer
                closer.start()
                time.sleep(0.6)  # the closer waits on the server's lock, past its join bound
            super().start()

    s.server._thread = Racing
    client = real(target=lambda: exchange(s.port, raw_request(body=message())), daemon=True)
    client.start()
    deadline = time.monotonic() + 10
    while "closer" not in outcome and time.monotonic() < deadline:
        time.sleep(0.01)
    outcome["closer"].join(10)
    assert "error" not in outcome, outcome.get("error")
    assert outcome["closed"] is True
    assert s.records()[-1]["closed"] == "close"


def test_an_actor_that_hangs_up_on_a_silent_upstream_ends_its_request(serve):
    s = serve(mode="silent")
    with socket.create_connection(("127.0.0.1", s.port), timeout=10) as sock:
        sock.sendall(raw_request(body=message()))
        received = b""
        while b"\r\n\r\n" not in received:
            chunk = sock.recv(65536)
            if not chunk:
                break
            received += chunk
    assert s.upstream.peer_closed.wait(3)  # the proxy saw the hangup and closed upstream
    deadline = time.monotonic() + 3
    while not s.records() and time.monotonic() < deadline:
        time.sleep(0.05)
    line = s.records()[0]
    assert (line["ended"], line["forwarded"]) == ("actor-closed", True)
    assert not s.server._upstreams


def test_an_actor_that_hangs_up_during_the_handshake_ends_its_request(serve):  # finding 2, setup
    s = serve(mode="nohandshake")
    with socket.create_connection(("127.0.0.1", s.port), timeout=10) as sock:
        sock.sendall(raw_request(body=message()))
        deadline = time.monotonic() + 10
        while s.upstream.connections == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.3)  # the proxy is waiting on a handshake that never comes
    assert s.upstream.peer_closed.wait(3)  # the hangup ended the handshake, not its 30 s timeout
    deadline = time.monotonic() + 3
    while not s.records() and time.monotonic() < deadline:
        time.sleep(0.05)
    line = s.records()[0]
    assert (line["ended"], line["forwarded"]) == ("actor-closed", False)
    assert not s.server._upstreams


def test_a_seq_handed_out_just_before_the_close_still_gets_its_line(serve, monkeypatch):
    # Allocation and registration are one step under the server's lock: a worker paused
    # right after the gate hands it seq 1, past the close's joins, is still published.
    monkeypatch.setattr(server_module, "JOIN_TIMEOUT", 0.2)
    allocated = threading.Event()
    real = Gate.next_seq

    def pausing(self):
        seq = real(self)
        if seq == 1:
            allocated.set()
            time.sleep(1.2)
        return seq

    monkeypatch.setattr(Gate, "next_seq", pausing)
    s = serve()
    threading.Thread(target=lambda: exchange(s.port, raw_request(body=message())), daemon=True).start()
    assert allocated.wait(10)
    s.server.close("close")
    time.sleep(1.5)
    lines = s.records()
    assert [line.get("seq") for line in lines] == [1, None]
    assert lines[-1]["closed"] == "close" and lines[-1]["last_seq"] == 1


def test_a_worker_stuck_past_the_join_still_gets_its_line(serve, monkeypatch):
    # A DNS lookup that outlasts the close's bounded join: the close writes the line,
    # and the worker's own, when the lookup returns, is suppressed.
    monkeypatch.setattr(server_module, "JOIN_TIMEOUT", 0.2)
    resolving = threading.Event()
    real = socket.getaddrinfo

    def slow(host, *args, **kwargs):
        if host == "localhost":
            resolving.set()
            time.sleep(1.5)
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", slow)
    s = serve()
    offered = []  # every line the server asks to write, so a duplicate shows even if dropped
    write = s.server.recorder.line
    monkeypatch.setattr(s.server.recorder, "line", lambda record: (offered.append(dict(record)), write(record)))
    threading.Thread(target=lambda: exchange(s.port, raw_request(body=message())), daemon=True).start()
    assert resolving.wait(10)
    s.server.close("close")
    lines = s.records()
    assert [line.get("seq") for line in lines] == [1, None]
    assert (lines[0]["ended"], lines[0]["refused"], lines[0]["forwarded"]) == ("route-closed", "route-closed", False)
    time.sleep(2.0)  # the lookup returns, and the worker finishes
    assert s.records() == lines
    assert [record.get("seq") for record in offered] == [1, None]


def test_no_record_holds_the_credential(served):
    exchange(served.port, raw_request(body=message()))
    exchange(served.port, raw_request(body=message(model="other")))
    served.server.close("close")
    text = served.records_path.read_text()
    assert CANARY not in text
    assert json.loads(text.splitlines()[-1]).keys() == {"at", "closed", "last_seq"}


@pytest.mark.parametrize(("mode", "status"), [("garbage", 502), ("hugehead", 502), ("badchunk", 200)])
def test_an_upstream_that_answers_garbage(serve, mode, status):  # Review Focus 2
    s = serve(mode=mode)
    answer = exchange(s.port, raw_request(body=message()))
    s.server.close("close")
    assert status_and_body(answer)[0] == status  # badchunk's head is valid: the actor gets it, then a cut
    line = s.records()[0]
    assert (line["ended"], line["forwarded"]) == ("upstream-error", True)


def test_an_upload_the_upstream_resets_is_recorded_forwarded_and_settled(serve):
    settled = []

    class Spy:
        def admit(self, run, operation, model, request_bytes, in_flight):
            return None

        def settle(self, seq, upstream_request_id, usage):
            settled.append(seq)

    s = serve(mode="reset", allowance=Spy())
    big = json.dumps(message(system="x" * 6_000_000)).encode()
    answer = exchange(s.port, raw_request(body=big), timeout=30)
    s.server.close("close")
    assert status_and_body(answer)[0] == 502
    line = s.records()[0]
    assert (line["ended"], line["forwarded"]) == ("upstream-error", True)
    assert settled == [1]


# Negatives (E21): each mutation shows a check the positive tests depend on. The two the
# spec also lists, routing by Host and forwarding the actor's framing, have no mutation:
# the proxy never reads Host or the actor's framing to route, and the positive tests
# (destination overrides, the chunked smuggle) pin that.

def test_a_deny_list_would_forward_an_unlisted_header(serve, monkeypatch):
    from autonomy.egress.route import always_dropped

    monkeypatch.setattr(server_module, "forwarded_headers",
                        lambda request, route: tuple((n, v) for n, v in request.headers if not always_dropped(n)))
    s = serve()
    exchange(s.port, raw_request(body=message(), headers=[("x-probe", "1")]))
    assert s.upstream.seen[0].headers["x-probe"] == ["1"]


def test_a_model_only_check_would_forward_what_reaches_out(serve, monkeypatch):
    def model_only(body, op):
        if body.get("model") not in op.models:
            raise server_module.Refused("model-refused", "x")

    monkeypatch.setattr(server_module, "check_body", model_only)
    s = serve()
    for body in (message(mcp_servers=[{"type": "url", "url": "https://x", "name": "x"}]),
                 message(tools=[{"type": "web_fetch_20250910", "name": "web_fetch"}]),
                 message(messages=[{"role": "user", "content": [
                     {"type": "image", "source": {"type": "url", "url": "https://x/i.png"}}]}])):
        exchange(s.port, raw_request(body=body))
    assert len(s.upstream.seen) == 3


def test_a_check_keyed_on_url_alone_would_forward_a_file_source(serve, monkeypatch):
    def url_only(body, op):
        if '"url"' in json.dumps(body):
            raise server_module.Refused("body-refused", "x")

    monkeypatch.setattr(server_module, "check_body", url_only)
    s = serve()
    exchange(s.port, raw_request(body=message(messages=[{"role": "user", "content": [
        {"type": "document", "source": {"type": "file", "file_id": "f"}}]}])))
    assert len(s.upstream.seen) == 1


def test_a_first_line_only_beta_check_would_forward_a_second(serve, monkeypatch):
    def first_only(request, route):
        checked, kept = set(), []
        for name, value in request.headers:
            if name not in route.forward_headers:
                continue
            allowed = route.header_tokens.get(name)
            if allowed is not None and name not in checked:
                if any(token.strip(" \t") not in allowed for token in value.split(",")):
                    raise server_module.Refused("header-refused", "x")
                checked.add(name)
            kept.append((name, value))
        return tuple(kept)

    monkeypatch.setattr(server_module, "forwarded_headers", first_only)
    s = serve()
    exchange(s.port, raw_request(body=message(), headers=[
        ("anthropic-beta", PI_BETAS[0]), ("anthropic-beta", "mcp-client-2025-04-04")]))
    assert "mcp-client-2025-04-04" in s.upstream.seen[0].headers["anthropic-beta"]


def test_a_lenient_parser_would_forward_a_duplicate_model(serve, monkeypatch):
    monkeypatch.setattr(server_module, "parse_body", lambda data: json.loads(data))
    s = serve()
    exchange(s.port, raw_request(body=b'{"model": "claude-opus-5-5", "model": "%s", "messages": []}' % MODEL.encode()))
    assert len(s.upstream.seen) == 1  # it checked the last model; a first-key parser upstream reads opus


def test_a_normalizing_matcher_would_forward_a_dot_segment(serve, monkeypatch):
    import posixpath

    s = serve()
    real = s.server.route.operation
    monkeypatch.setattr(type(s.server.route), "operation",
                        lambda self, method, path, query: real(method, posixpath.normpath(path), query))
    exchange(s.port, raw_request(target="/v1/messages/./?beta=true", body=message()))
    assert len(s.upstream.seen) == 1


def test_a_buffering_proxy_would_deliver_the_first_event_late(serve, monkeypatch):
    real = server_module.read_response

    def buffered(gate, sock, **kwargs):
        response = real(gate, sock, **kwargs)
        response.body = iter([b"".join(response.body)])
        return response

    monkeypatch.setattr(server_module, "read_response", buffered)
    s = serve(mode="sse")
    s.upstream.events, s.upstream.gap = 5, 0.3
    first_at = None
    with socket.create_connection(("127.0.0.1", s.port), timeout=10) as sock:
        sock.sendall(raw_request(body=message()))
        received = b""
        while chunk := sock.recv(65536):
            received += chunk
            if first_at is None and b"event: message" in received:
                first_at = time.monotonic()
    assert first_at > s.upstream.last_event_at


# Fix round 1

def test_a_transient_accept_error_does_not_end_accepting(serve, monkeypatch):
    real = socket.socket.accept
    failed = []

    def flaky(self):
        target = getattr(threading.current_thread(), "_target", None)
        if getattr(target, "__qualname__", "") == "ProxyServer._accept" and not failed:
            failed.append(True)
            raise OSError(errno.EMFILE, "too many open files")
        return real(self)

    monkeypatch.setattr(socket.socket, "accept", flaky)
    s = serve()
    assert status_and_body(exchange(s.port, raw_request(body=message())))[0] == 200
    assert failed


def test_a_worker_that_cannot_start_releases_its_connection_and_the_close_completes(serve):
    s = serve()

    class Failing(threading.Thread):
        def start(self):
            if getattr(self, "_target", None) == s.server._handle:
                raise RuntimeError("can't start new thread")
            super().start()

    s.server._thread = Failing
    with socket.create_connection(("127.0.0.1", s.port), timeout=5) as sock:
        sock.sendall(raw_request(body=message()))
        assert sock.recv(65536) == b""  # released, not left hanging
    assert s.server.close("close") is True
    assert s.records()[-1]["closed"] == "close"
    assert not s.server._actors


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_settle_that_raises_still_ends_the_actors_response(serve):
    class Bad:
        def admit(self, run, operation, model, request_bytes, in_flight):
            return None

        def settle(self, seq, upstream_request_id, usage):
            raise RuntimeError("settle failed")

    s = serve(allowance=Bad())
    assert status_and_body(exchange(s.port, raw_request(body=message()), timeout=5))[0] == 200
    s.server.close("close")
    assert s.records()[0]["ended"] == "complete"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_recorder_that_cannot_write_still_closes_the_actors_connection(serve, monkeypatch):
    s = serve()

    def broken(record):
        raise OSError(errno.ENOSPC, "no space")

    monkeypatch.setattr(s.server.recorder, "line", broken)  # undone before the fixture's close
    assert status_and_body(exchange(s.port, raw_request(body=message()), timeout=5))[0] == 200


def test_a_proxy_that_cannot_start_its_accept_thread_says_so_and_closes_the_listener(serve):
    s = serve()
    listener = socket.create_server(("127.0.0.1", 0))

    class Failing(threading.Thread):
        def start(self):
            raise RuntimeError("can't start new thread")

    s.server._thread = Failing
    assert s.server.serve(listener) is False
    assert listener.fileno() == -1
