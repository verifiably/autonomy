import socket
import ssl
import threading
import time

import pytest

from egress_fixtures import FakeUpstream, tls  # noqa: F401  (tls is a fixture)
from autonomy.egress.upstream import (
    POLL, ActorGone, Gate, Response, RouteClosed, UpstreamError, connect, read_response, response_head, send_all,
    tls_context,
)


def test_the_close_transition_is_taken_once():
    gate = Gate()
    assert (gate.next_seq(), gate.next_seq()) == (1, 2)
    assert gate.close("lease") is True
    assert gate.close("close") is False
    assert (gate.is_open, gate.cause, gate.last_seq) == (False, "lease", 2)
    assert gate.next_seq() is None


def stalled_pair() -> tuple[socket.socket, socket.socket]:
    sender, peer = socket.socketpair()
    for end in (sender, peer):
        end.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        end.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    sender.setblocking(False)
    return sender, peer


def test_a_stalled_send_never_holds_the_close():
    gate = Gate()
    sender, peer = stalled_pair()
    payload = b"x" * (4 << 20)
    outcome = {}

    def send():
        try:
            send_all(gate, sender, payload)
        except RouteClosed as closed:
            outcome["sent"] = closed.sent
            outcome["at"] = time.monotonic()

    worker = threading.Thread(target=send)
    worker.start()
    time.sleep(0.5)  # the peer never reads: the send is waiting for room
    started = time.monotonic()
    assert gate.close("lease") is True
    assert time.monotonic() - started < 0.1
    worker.join(POLL + 1)
    assert not worker.is_alive()
    assert 0 < outcome["sent"] < len(payload)
    sender.close()
    peer.close()


def test_a_stalled_tls_upload_is_reported_attempted(tls):
    # A TLS write reports no partial progress: after megabytes went out, `sent` may
    # still be 0, so the record must rely on `attempted`.
    upstream = FakeUpstream(tls, mode="stall")
    gate = Gate()
    sock = connect(gate, "localhost", upstream.port, tls_context(tls.cert))
    payload = b"POST /v1/messages HTTP/1.1\r\ncontent-length: 6000000\r\n\r\n" + b"x" * 6_000_000
    outcome = {}

    def send():
        try:
            send_all(gate, sock, payload)
        except RouteClosed as closed:
            outcome["closed"] = closed

    worker = threading.Thread(target=send)
    worker.start()
    time.sleep(1.0)
    gate.close("lease")
    worker.join(POLL + 2)
    assert not worker.is_alive()
    assert outcome["closed"].attempted is True
    sock.close()
    assert 0 < upstream.stalled_bytes() < len(payload)
    upstream.stop()


def test_no_connection_is_opened_after_the_close(tls, monkeypatch):
    # Not even a SYN: the connect call itself runs under the gate (a connect that is cut
    # before its handshake never reaches the fake's accept, so count the calls).
    upstream = FakeUpstream(tls)
    calls = []
    real = socket.socket.connect_ex
    monkeypatch.setattr(socket.socket, "connect_ex", lambda self, address: calls.append(address) or real(self, address))
    gate = Gate()
    gate.close("close")
    with pytest.raises(RouteClosed):
        connect(gate, "localhost", upstream.port, tls_context(tls.cert))
    time.sleep(0.2)
    assert calls == [] and upstream.connections == 0
    upstream.stop()


def test_an_actor_that_hangs_up_during_the_tcp_connect_ends_it(tls):
    # A listener whose accept queue is full drops SYNs, so the TCP connect hangs: the
    # actor's hangup ends it, not the connect timeout.
    listener = socket.create_server(("127.0.0.1", 0), backlog=0)
    port = listener.getsockname()[1]
    filler = socket.create_connection(("127.0.0.1", port), timeout=5)  # fills the queue
    actor, peer = socket.socketpair()
    threading.Timer(0.5, peer.close).start()
    started = time.monotonic()
    try:
        with pytest.raises(ActorGone):
            connect(Gate(), "127.0.0.1", port, tls_context(tls.cert), timeout=10, watch=actor)
        assert time.monotonic() - started < 3
    finally:
        for sock in (actor, filler, listener):
            sock.close()


def test_each_write_attempt_carries_at_most_a_slice():
    from autonomy.egress.upstream import SLICE

    class Recording:
        def __init__(self):
            self.sizes = []

        def send(self, data):
            self.sizes.append(len(data))
            return len(data)

    sock = Recording()
    send_all(Gate(), sock, b"x" * (SLICE * 3 + 5))
    assert sock.sizes == [SLICE, SLICE, SLICE, 5]


def test_a_blocking_write_under_the_lock_would_hold_the_close():
    # Negative (E22): the lock held across a blocking write. The close transition then
    # waits for the peer to read, which a stalled upstream never does.
    gate = Gate()
    sender, peer = socket.socketpair()
    sender.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)

    def careless():
        with gate._lock:
            sender.sendall(b"x" * (1 << 20))

    holder = threading.Thread(target=careless, daemon=True)
    holder.start()
    time.sleep(0.2)
    closer = threading.Thread(target=gate.close, args=("lease",), daemon=True)
    closer.start()
    closer.join(1.0)
    assert closer.is_alive()  # still waiting on the lock
    peer.setblocking(False)
    deadline = time.monotonic() + 10
    while (holder.is_alive() or closer.is_alive()) and time.monotonic() < deadline:
        try:
            peer.recv(65536)
        except BlockingIOError:
            time.sleep(0.01)
    sender.close()
    peer.close()


def test_after_the_close_nothing_is_written():
    gate = Gate()
    gate.close("close")
    sender, peer = socket.socketpair()
    with pytest.raises(RouteClosed) as closed:
        send_all(gate, sender, b"POST / HTTP/1.1\r\n\r\n")
    assert (closed.value.sent, closed.value.attempted) == (0, False)
    peer.setblocking(False)
    with pytest.raises(BlockingIOError):
        peer.recv(1)
    sender.close()
    peer.close()


def exchange(upstream: FakeUpstream, tls) -> tuple:
    gate = Gate()
    sock = connect(gate, "localhost", upstream.port, tls_context(tls.cert))
    try:
        send_all(gate, sock, b"POST /v1/messages HTTP/1.1\r\nhost: localhost\r\ncontent-length: 2\r\nconnection: close\r\n\r\n{}")
        response = read_response(gate, sock)
        return response, b"".join(response.body)
    finally:
        sock.close()


@pytest.mark.parametrize("mode", ["json", "continue", "close"])
def test_a_response_is_read_whatever_its_framing(tls, mode):
    upstream = FakeUpstream(tls, mode=mode)
    response, body = exchange(upstream, tls)
    assert (response.status, body) == (200, b'{"ok":true}')
    assert upstream.seen[0].body == b"{}"


def test_a_chunked_stream_is_decoded(tls):
    upstream = FakeUpstream(tls, mode="sse")
    response, body = exchange(upstream, tls)
    assert response.request_id == "req_sse"
    assert body.count(b"event: message") == upstream.events


def test_verification_is_never_disabled(tls):
    upstream = FakeUpstream(tls)
    with pytest.raises(UpstreamError) as caught:
        connect(Gate(), "localhost", upstream.port, tls_context(None))
    assert "certificate" in str(caught.value).lower()


@pytest.mark.parametrize("mode", ["garbage", "hugehead", "badchunk", "bare_lf", "bare_cr", "nul_name", "nul_value", "gzip_chunked"])
def test_a_malformed_answer_is_an_upstream_error_never_a_hang(tls, mode):  # Review Focus 2
    upstream = FakeUpstream(tls, mode=mode)
    outcome = {}

    def run():
        try:
            exchange(upstream, tls)
        except UpstreamError as caught:
            outcome["error"] = caught

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(10)
    assert not worker.is_alive()
    assert "error" in outcome


def test_the_response_head_drops_what_connection_names():
    response = Response(200, "OK", (("connection", "x-hop"), ("x-hop", "1"), ("request-id", "r")), iter(()))
    head = response_head(response).decode()
    assert "x-hop" not in head and "request-id: r" in head


def test_the_response_head_drops_hop_and_credential_headers(tls):
    upstream = FakeUpstream(tls, mode="sse")
    response, _ = exchange(upstream, tls)
    head = response_head(response).decode()
    assert head.startswith("HTTP/1.1 200 OK\r\n")
    assert "request-id: req_sse" in head and "retry-after: 1" in head
    assert "set-cookie" not in head and "keep-alive" not in head
    assert head.count("transfer-encoding: chunked\r\n") == 1
    assert head.endswith("connection: close\r\n\r\n")


def test_renegotiation_is_refused():
    # A renegotiating upstream would make recv send a ClientHello outside the gate.
    assert tls_context(None).options & ssl.OP_NO_RENEGOTIATION
