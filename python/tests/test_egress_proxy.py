import base64
import json
import os
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

import autonomy
from egress_fixtures import (  # noqa: F401  (tls is a fixture)
    CANARY, FakeUpstream, exchange, message, pi_route, raw_request, status_and_body, tls, to_toml, write_credential,
)
from autonomy.egress.errors import EgressUnproven
from autonomy.egress.proxy import control_loop, read_credential, receive_message, send_message
from autonomy.egress.route import parse_route
from autonomy.egress.server import Hooks, ProxyServer, Recorder
from autonomy.egress.upstream import tls_context


@pytest.mark.parametrize("data", [b"sk-key\n", b"sk-key"])
def test_a_credential_of_one_line(tmp_path, data):  # Review Focus 5
    path = tmp_path / "credential"
    path.write_bytes(data)
    assert read_credential(path) == "sk-key"


@pytest.mark.parametrize("data", [b"sk-key\r\n", b"a\nb\n", b"", b"\n", b"sk key\n", "sk-kéy\n".encode()])
def test_a_credential_that_is_not_one_visible_line(tmp_path, data):  # Review Focus 5
    path = tmp_path / "credential"
    path.write_bytes(data)
    with pytest.raises(EgressUnproven) as caught:
        read_credential(path)
    assert caught.value.code == "credential-invalid"


@pytest.fixture(autouse=True)
def stop_upstreams(monkeypatch):
    made = []
    real_init = FakeUpstream.__init__

    def tracking(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        made.append(self)

    monkeypatch.setattr(FakeUpstream, "__init__", tracking)
    yield
    for upstream in made:
        upstream.stop()


def fresh(tmp_path, tls, *, mode="json", hooks=Hooks()):
    upstream = FakeUpstream(tls, mode=mode)
    route = parse_route(to_toml(pi_route(credential=tmp_path / "c", upstream=upstream.origin, ca_file=tls.cert)).encode())
    records = tmp_path / "egress.jsonl"
    fd = os.open(records, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    server = ProxyServer(route, CANARY, Recorder(fd), context=tls_context(tls.cert), hooks=hooks)
    return server, upstream, records


def pair():
    return socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)


def run_loop(server, control, wake, lease):
    outcome = {}
    thread = threading.Thread(
        target=lambda: outcome.update(cause=control_loop(server, control, wake, lease), at=time.monotonic()),
        daemon=True,
    )
    thread.start()
    return thread, outcome


def test_the_loop_hands_the_listener_to_the_server_and_says_so(tmp_path, tls):
    server, upstream, _ = fresh(tmp_path, tls)
    ours, theirs = pair()
    wake_read, wake_write = os.pipe()
    thread, outcome = run_loop(server, theirs, wake_read, 30)
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    send_message(ours, {"op": "listener"}, [listener.fileno()])
    listener.close()
    reply, _ = receive_message(ours)
    assert reply == {"op": "listening"}
    assert status_and_body(exchange(port, raw_request(body=message())))[0] == 200
    send_message(ours, {"op": "close"})
    thread.join(5)
    assert outcome["cause"] == "close"
    server.close("close")


@pytest.mark.parametrize("cause", ["eof", "term", "lease"])
def test_each_close_cause(tmp_path, tls, cause):
    server, _, _ = fresh(tmp_path, tls)
    ours, theirs = pair()
    wake_read, wake_write = os.pipe()
    started = time.monotonic()
    thread, outcome = run_loop(server, theirs, wake_read, 1.0 if cause == "lease" else 30)
    if cause == "eof":
        ours.close()
    if cause == "term":
        os.write(wake_write, b"\0")
    thread.join(5)
    assert outcome["cause"] == cause
    if cause == "lease":
        assert 0.9 < outcome["at"] - started < 1.5


def test_renewal_extends_the_lease(tmp_path, tls):
    server, _, _ = fresh(tmp_path, tls)
    ours, theirs = pair()
    wake_read, _ = os.pipe()
    started = time.monotonic()
    thread, outcome = run_loop(server, theirs, wake_read, 1.0)
    for _ in range(4):
        time.sleep(0.5)
        send_message(ours, {"op": "renew"})
    thread.join(5)
    assert outcome["cause"] == "lease" and outcome["at"] - started > 2.5


class Holder:
    def __init__(self, stage, seq):
        self.stage, self.seq = stage, seq
        self.reached, self.release = threading.Event(), threading.Event()

    def __call__(self, stage, seq):
        if (stage, seq) == (self.stage, self.seq):
            self.reached.set()
            assert self.release.wait(20)


def test_the_lease_closes_a_stalled_upstream_without_its_progress(tmp_path, tls):  # E22
    holder = Holder("before-send", 2)
    server, upstream, records = fresh(tmp_path, tls, mode="stall", hooks=Hooks(hold=holder))
    ours, theirs = pair()
    wake_read, _ = os.pipe()
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    started = time.monotonic()
    thread, outcome = run_loop(server, theirs, wake_read, 3.0)  # nobody renews: the orchestrator is stopped
    send_message(ours, {"op": "listener"}, [listener.fileno()])
    listener.close()
    assert receive_message(ours)[0] == {"op": "listening"}
    big = json.dumps(message(system="x" * 6_000_000)).encode()
    first = threading.Thread(target=lambda: exchange(port, raw_request(body=big), timeout=30), daemon=True)
    first.start()
    deadline = time.monotonic() + 10
    while not upstream.seen and time.monotonic() < deadline:  # the big request has seq 1 and is upstream
        time.sleep(0.05)
    second = {}
    second_client = threading.Thread(
        target=lambda: second.setdefault("raw", exchange(port, raw_request(body=message()))), daemon=True,
    )
    second_client.start()
    assert holder.reached.wait(10)
    thread.join(5)
    assert outcome["cause"] == "lease"
    closer = threading.Thread(target=server.close, args=("lease",))
    closer.start()
    while server.gate.is_open:
        time.sleep(0.01)
    closed_at = time.monotonic()
    assert closed_at - started < 3.0 + 1.0
    holder.release.set()
    closer.join(5)
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", port), timeout=2)
    second_client.join(5)
    status, body = status_and_body(second["raw"])
    assert status == 403 and json.loads(body)["error"]["code"] == "route-closed"
    lines = [json.loads(line) for line in records.read_text().splitlines()]
    stalled = next(line for line in lines if line.get("seq") == 1)
    assert stalled["ended"] == "route-closed"
    assert lines[-1]["closed"] == "lease"
    assert upstream.stalled_bytes() < len(big)


def test_without_its_own_deadline_a_proxy_forwards_past_the_lease(tmp_path, tls):
    # Negative (E22): a loop with no deadline keeps serving for a stopped orchestrator.
    server, _, _ = fresh(tmp_path, tls)
    ours, theirs = pair()
    wake_read, _ = os.pipe()
    thread, outcome = run_loop(server, theirs, wake_read, float("inf"))
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    send_message(ours, {"op": "listener"}, [listener.fileno()])
    listener.close()
    receive_message(ours)
    time.sleep(2.0)
    assert "cause" not in outcome
    assert status_and_body(exchange(port, raw_request(body=message())))[0] == 200
    ours.close()
    thread.join(5)
    server.close("eof")


def spawn_proxy(tmp_path: Path, tls, credential_text: str):
    """The proxy's `main` as a process, unsandboxed: its fixed paths patched to files here."""
    credential = tmp_path / "credential"
    credential.write_text(credential_text)
    os.chmod(credential, 0o600)
    upstream = FakeUpstream(tls)
    route_bytes = to_toml(pi_route(credential=credential, upstream=upstream.origin, ca_file=tls.cert)).encode()
    records = tmp_path / "egress.jsonl"
    records_fd = os.open(records, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    ours, theirs = pair()
    package_parent = str(Path(autonomy.__file__).resolve().parent.parent)
    code = (
        "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
        "import autonomy.egress.proxy as p; "
        f"p.IN_SANDBOX_CREDENTIAL = Path({str(credential)!r}); p.IN_SANDBOX_CA = Path({str(tls.cert)!r}); "
        "raise SystemExit(p.main(sys.argv[2:]))"
    )
    process = subprocess.Popen(
        ["/usr/bin/python3", "-I", "-c", code, package_parent, str(theirs.fileno()), str(records_fd)],
        pass_fds=(theirs.fileno(), records_fd), stdin=subprocess.DEVNULL, start_new_session=True,
    )
    theirs.close()
    os.close(records_fd)
    send_message(ours, {"op": "route", "route": base64.b64encode(route_bytes).decode(), "lease": 30})
    return process, ours, records


def test_the_process_serves_and_closes_on_sigterm(tmp_path, tls):
    process, ours, records = spawn_proxy(tmp_path, tls, "sk-canary-proc\n")
    assert receive_message(ours)[0] == {"op": "ready"}
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    send_message(ours, {"op": "listener"}, [listener.fileno()])
    listener.close()
    assert receive_message(ours)[0] == {"op": "listening"}
    assert status_and_body(exchange(port, raw_request(body=message())))[0] == 200
    process.send_signal(signal.SIGTERM)
    assert receive_message(ours)[0] == {"op": "closed", "cause": "term", "last_seq": 1}
    assert process.wait(10) == 0
    assert json.loads(records.read_text().splitlines()[-1])["closed"] == "term"


def test_the_process_closes_on_eof(tmp_path, tls):
    process, ours, records = spawn_proxy(tmp_path, tls, "sk-canary-proc\n")
    assert receive_message(ours)[0] == {"op": "ready"}
    ours.close()
    assert process.wait(10) == 0
    assert json.loads(records.read_text().splitlines()[-1])["closed"] == "eof"


def test_a_two_line_credential_is_reported_and_never_served(tmp_path, tls):
    process, ours, _ = spawn_proxy(tmp_path, tls, "sk-one\nsk-two\n")
    reply, _ = receive_message(ours)
    assert (reply["op"], reply["code"]) == ("error", "credential-invalid")
    assert process.wait(10) == 3
