"""Private supervisor stream and endpoint startup against the pinned wire."""

import concurrent.futures
import json
import os
from pathlib import Path
import socket
import sys
import time

import pytest


FIXTURES = Path(__file__).parent / "fixtures" / "run_endpoint"
CONTROL = (FIXTURES / "control.v1.jsonl").read_bytes().splitlines(keepends=True)
SEALED = (FIXTURES / "sealed.control.v1.jsonl").read_bytes()


def test_control_reads_a_fragmented_frame_and_consumes_one_reply_at_a_time():
    from autonomy.endpoint import Control

    left, right = socket.socketpair()
    with left, right, concurrent.futures.ThreadPoolExecutor(1) as worker:
        control = Control(left, lease=60)
        right.settimeout(2)

        def peer():
            with right.makefile("rb") as stream:
                assert json.loads(stream.readline()) == json.loads(CONTROL[3])
                right.sendall(CONTROL[4][:12])
                right.sendall(CONTROL[4][12:])
                assert json.loads(stream.readline()) == json.loads(CONTROL[5])
                right.sendall(SEALED)

        remote = worker.submit(peer)
        control.renew()
        assert control.seal(time.monotonic() + 2) == json.loads(SEALED)
        remote.result(timeout=2)


def test_seal_is_sent_while_renew_is_waiting_and_preserves_an_existing_cause():
    from autonomy.endpoint import Control, EndpointError

    left, right = socket.socketpair()
    with left, right, concurrent.futures.ThreadPoolExecutor(2) as worker:
        control = Control(left, lease=60)
        right.settimeout(2)
        with right.makefile("rb") as stream:
            renewing = worker.submit(control.renew)
            assert json.loads(stream.readline()) == json.loads(CONTROL[3])
            closing = worker.submit(control.seal, time.monotonic() + 2)
            assert json.loads(stream.readline()) == json.loads(CONTROL[5])
            right.sendall(b'{"code":"run-sealed","type":"refused","version":"control.v1"}\n' + SEALED)
            with pytest.raises(EndpointError, match="run-sealed"):
                renewing.result(timeout=2)
            assert closing.result(timeout=2)["cause"] == "eof"


def test_control_rejects_a_duplicate_ack_before_actor_binding():
    from autonomy.endpoint import Control, EndpointError

    left, right = socket.socketpair()
    with left, right, concurrent.futures.ThreadPoolExecutor(1) as worker:
        control = Control(left, lease=60)
        right.settimeout(2)

        def peer():
            with right.makefile("rb") as stream:
                stream.readline()
                right.sendall(CONTROL[4] + CONTROL[4])
                right.recv(4096)

        remote = worker.submit(peer)
        control.renew()
        descriptor = os.open("/proc/self/ns/pid", os.O_RDONLY | os.O_CLOEXEC)
        try:
            with pytest.raises(EndpointError, match="expected bound"):
                control.bind(descriptor)
        finally:
            os.close(descriptor)
        remote.result(timeout=2)


def test_an_expired_lease_never_sends_a_bind_frame():
    from autonomy.endpoint import Control, EndpointError

    left, right = socket.socketpair()
    with left, right:
        control = Control(left, lease=60, now=lambda: 100)
        control.expires = 99
        with pytest.raises(EndpointError, match="lease expired"):
            control.bind(-1)
        right.setblocking(False)
        with pytest.raises(BlockingIOError):
            right.recv(4096)


FAKE_ENDPOINT = r'''
import json, os, socket, sys
from pathlib import Path
assert sys.argv[1:3] == ["serve", "--run"]
assert "SCIENCE_CONFIG" not in os.environ
assert sys.stdin.read() == ""
run = Path(sys.argv[3]).parent
events = [json.loads(row) for row in (run / "events.jsonl").read_text().splitlines()]
assert any(row.get("event") == "endpoint-starting" and row["pid"] == os.getpid() for row in events)
launch = json.loads(Path(sys.argv[3]).read_text())
assert set(launch) == set(json.loads(os.environ["LAUNCH_FIXTURE"])) | {"lease_seconds", "seal_timeout_seconds"}
assert launch["version"] == "launch.v1"
assert launch["permit"] == {"kinds": [], "act_families": [], "ungoverned": False}
assert len(launch["written_chains"]) == 1
token = Path(launch["token_file"])
assert token.stat().st_mode & 0o777 == 0o600
assert len(token.read_bytes()) == 64 and set(token.read_bytes()) <= set(b"0123456789abcdef")
with socket.socket(socket.AF_UNIX) as stream:
    stream.connect(launch["control_socket"])
    opened = json.loads(os.environ["OPEN_FIXTURE"])
    opened["ledger_path"] = os.environ["LEDGER"]
    opened["session_id"] = "a" * 32
    stream.sendall(json.dumps(opened).encode() + b"\n")
    stream.settimeout(5)
    stream.recv(16384)
'''


@pytest.mark.parametrize("invalid", [None, "actor-mismatch", "permit-mismatch"])
def test_endpoint_exec_waits_for_identity_and_validates_session_ledger(tmp_path, invalid):
    from tempfile import TemporaryDirectory

    from autonomy.endpoint import Endpoint, EndpointError, Launch
    from autonomy.run import RunDirs
    from autonomy.science_reads import ChainHead
    from autonomy.tiers import COORDINATION, REPORT_ONLY

    root = tmp_path.resolve()
    run, scratch, operations = (root / name for name in ("run", "scratch", "operations"))
    run.mkdir(0o700)
    scratch.mkdir(0o700)
    config = root / "config.toml"
    config.touch()
    ledger = operations / "sessions" / ("a" * 32) / "ledger.v1"
    ledger.parent.mkdir(parents=True)
    row = {"line": "session-open", "session": "a" * 32, "actor": "session:" + "a" * 32,
           "permit": REPORT_ONLY.permit.to_json(), "world": {}, "at": "2026-11-22T15:30:00Z"}
    if invalid == "actor-mismatch":
        row["actor"] = "session:" + "b" * 32
    elif invalid == "permit-mismatch":
        row["permit"] = COORDINATION.permit.to_json()
    ledger.write_text(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
                      encoding="utf-8")
    executable = root / "science"
    executable.write_text(f"#!{sys.executable}\n" + FAKE_ENDPOINT)
    executable.chmod(0o700)
    env = {"PATH": "/usr/bin", "HOME": str(root), "SCIENCE_CONFIG": str(config),
           "LAUNCH_FIXTURE": (FIXTURES / "launch.v1.json").read_text(),
           "OPEN_FIXTURE": CONTROL[0].decode(), "LEDGER": str(ledger)}
    with TemporaryDirectory(dir="/tmp", prefix="va-endpoint-") as runtime:
        dirs = RunDirs("1" * 32, run, scratch, Path(runtime).resolve())
        chain = ChainHead("corpus", "a" * 32, root / "corpus", "1" * 64, "1" * 64, ())
        launch = Launch(dirs, executable, config, operations, REPORT_ONLY.permit, (chain,), 60, 1)
        if invalid is None:
            endpoint = Endpoint.start(launch, env, timeout=2)
            try:
                assert endpoint.opened.session_id == "a" * 32
                assert endpoint.opened.ledger_path == ledger
                assert os.getsid(endpoint.process.pid) == endpoint.process.pid
            finally:
                endpoint.close()
            assert endpoint.process.returncode is not None
        else:
            with pytest.raises(EndpointError) as caught:
                Endpoint.start(launch, env, timeout=2)
            assert caught.value.code == invalid


def test_recorded_process_identity_refuses_a_reused_pid():
    from autonomy.process import ProcessIdentity

    running = ProcessIdentity.capture(os.getpid())
    replaced = ProcessIdentity(running.pid, running.start_time + 1, running.boot_id)
    assert replaced.pin() is None
    pidfd = running.pin()
    assert pidfd is not None
    os.close(pidfd)
