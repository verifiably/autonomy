"""Bounded loopback comparison; prototypes patch only the actor-side wire/close.

Run on the pre-fix tree: just test-one tests/test_completion_probe.py -q -s
"""
import http.client
import socket
import struct
import threading

import pytest

import autonomy.egress.server as server_module
from egress_fixtures import message, raw_request, serve, tls  # noqa: F401


@pytest.mark.parametrize("mechanism", ["current", "chunked", "reset"])
@pytest.mark.parametrize("case", ["stop", "survivor", "badchunk", "json", "close"])
@pytest.mark.parametrize("client", ["raw", "http"])
def test_completion_probe(serve, monkeypatch, mechanism, case, client):
    s = serve(mode="sse" if case in ("stop", "survivor") else case)
    s.upstream.events, s.upstream.gap = 100, 0.05
    actors = set()
    completed = set()
    local = threading.local()
    reset_lock = threading.Lock()
    send = s.server._to_actor
    finish = s.server._finish
    cut = server_module.cut
    head = server_module.response_head

    def actor_send(conn, data):
        actors.add(conn)
        local.conn = conn
        if mechanism == "chunked" and not data.startswith(b"HTTP/1.1 "):
            data = b"%x\r\n%s\r\n" % (len(data), data)
        send(conn, data)

    def actor_finish(record):
        if record["ended"] == "complete" and hasattr(local, "conn"):
            completed.add(local.conn)
        if mechanism == "chunked" and record["ended"] == "complete" and record["forwarded"]:
            send(local.conn, b"0\r\n\r\n")
        finish(record)

    def actor_cut(sock, how=socket.SHUT_RDWR):
        if mechanism == "reset" and sock in actors and sock not in completed and how == socket.SHUT_RDWR:
            with reset_lock:
                if sock.fileno() >= 0:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                    sock.close()
        else:
            cut(sock, how)

    monkeypatch.setattr(s.server, "_to_actor", actor_send)
    monkeypatch.setattr(s.server, "_finish", actor_finish)
    monkeypatch.setattr(server_module, "cut", actor_cut)
    if mechanism == "chunked":
        monkeypatch.setattr(server_module, "response_head", lambda r: head(r).replace(
            b"connection: close", b"transfer-encoding: chunked\r\nconnection: close"))
    if case == "survivor":
        monkeypatch.setattr(server_module, "JOIN_TIMEOUT", 0)

    error = None
    received = b""
    with socket.create_connection(("127.0.0.1", s.port), timeout=5) as sock:
        sock.sendall(raw_request(body=message()))
        response = http.client.HTTPResponse(sock) if client == "http" else None
        try:
            if response is not None:
                response.begin()
                if case in ("stop", "survivor"):
                    received = response.read(1)
                    s.server.close("close")
                received += response.read()
            else:
                if case in ("stop", "survivor"):
                    while b"event: message" not in received:
                        part = sock.recv(65536)
                        assert part
                        received += part
                    s.server.close("close")
                while part := sock.recv(65536):
                    received += part
        except (ConnectionResetError, http.client.IncompleteRead) as caught:
            error = type(caught).__name__
        finally:
            if response is not None:
                response.close()
    s.server.close("close")
    s.server._join(list(s.server._threads), 2)
    failed = case in ("stop", "survivor", "badchunk")
    if mechanism == "reset" and failed:
        assert error == "ConnectionResetError"
    elif mechanism == "chunked" and failed and client == "http":
        assert error == "IncompleteRead"
    else:
        assert error is None
    if mechanism == "chunked" and client == "raw":
        assert received.endswith(b"0\r\n\r\n") is not failed
    assert s.records()[0]["ended"] == (
        "route-closed" if case in ("stop", "survivor") else "upstream-error" if failed else "complete")
    print(f"{mechanism:7} {case:8} {client:4} {error or 'clean EOF'} bytes={len(received)}")
