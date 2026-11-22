"""The close transition and actor release guards."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
import signal
import socket
import threading
import time
from pathlib import Path

import pytest

from autonomy.egress.session import EgressClosed
from autonomy.endpoint import Control
from autonomy.science_reads import ChainHead

FIXTURES = Path(__file__).parents[1] / "fixtures" / "run_endpoint"
STORE = ChainHead("store", "b" * 32, Path("/store"), "2" * 64, "6" * 64, ())
CORPUS = ChainHead("corpus", "a" * 32, Path("/corpus"), "1" * 64, "1" * 64, ())


@pytest.mark.parametrize("blocked", ["endpoint", "proxy"])
def test_close_dispatches_both_participants_even_when_one_send_is_blocked(tmp_path, blocked):
    from autonomy.science_run._supervisor import finish

    endpoint_sent = threading.Event()
    proxy_sent = threading.Event()
    endpoint_closed = threading.Event()
    ack = json.loads((FIXTURES / "sealed.control.v1.jsonl").read_bytes())
    log = []

    class Endpoint:
        seal_timeout = 2
        pidfd = 1

        @property
        def control(self):
            return self

        def seal(self, deadline):
            if blocked == "endpoint":
                assert proxy_sent.wait(2)
            endpoint_sent.set()
            assert time.monotonic() < deadline
            return ack

        def close(self, *, grace=None):
            log.append("endpoint dead")
            self.pidfd = -1
            endpoint_closed.set()

    class Proxy:
        def send_close(self):
            if blocked == "proxy":
                assert endpoint_sent.wait(2)
            proxy_sent.set()

        def wait_close(self, deadline):
            assert time.monotonic() < deadline
            return EgressClosed("close", 0, False)

    cause = "actor-exit"
    findings = finish(tmp_path, Endpoint(), Proxy(), None, (CORPUS, STORE), cause)
    assert not findings
    assert endpoint_closed.is_set() and proxy_sent.is_set()
    assert log == ["endpoint dead"]
    events = [json.loads(row) for row in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [row["event"] for row in events] == ["close-start", "seal-request", "sealed"]
    assert events[0]["cause"] == cause
    assert events[-1]["seal"]["cause"] == "eof"


def test_timed_out_seal_still_closes_the_endpoint_and_records_timeout(tmp_path):
    from autonomy.science_run._supervisor import finish

    closed = threading.Event()

    class Endpoint:
        seal_timeout = 0.1
        pidfd = 1

        @property
        def control(self):
            return self

        def seal(self, deadline):
            raise TimeoutError("no endpoint seal")

        def close(self, *, grace=None):
            closed.set()
            self.pidfd = -1

    findings = finish(tmp_path, Endpoint(), None, None, (CORPUS,), "deadline")
    assert closed.is_set()
    assert [finding.code for finding in findings] == ["seal-timeout"]
    assert json.loads((tmp_path / "events.jsonl").read_text().splitlines()[-1])["event"] == "seal-timeout"


def test_sigterm_latches_a_stop_during_opening():
    from autonomy.science_run._supervisor import Stop

    former = signal.getsignal(signal.SIGTERM)
    with Stop(30) as stop:
        assert stop.cause() is None
        os.kill(os.getpid(), signal.SIGTERM)
        assert stop.cause() == "sigterm"
    assert signal.getsignal(signal.SIGTERM) is former


def test_deadline_stays_latched():
    from autonomy.science_run._supervisor import Stop

    now = [100.0]
    with Stop(2.0, now=lambda: now[0]) as stop:
        assert stop.cause() is None
        now[0] = 102.0
        assert stop.cause() == "deadline"
        os.kill(os.getpid(), signal.SIGINT)
        assert stop.cause() == "deadline"


def test_heartbeat_keeps_a_waiting_endpoint_alive_then_stops():
    from autonomy.science_run._supervisor import Heartbeat, Stop

    left, right = socket.socketpair()
    with left, right, ThreadPoolExecutor(1) as worker:
        control = Control(left, lease=1)
        right.settimeout(3)
        seen = threading.Event()

        def peer():
            with right.makefile("rb") as stream:
                request = json.loads(stream.readline())
                assert request == {"version": "control.v1", "type": "renew"}
                right.sendall(b'{"version":"control.v1","type":"renewed"}\n')
                seen.set()

        remote = worker.submit(peer)
        with Stop(30) as stop, Heartbeat(control, 0.05, stop=stop) as beat:
            assert seen.wait(2)
            remote.result(timeout=2)
        assert not beat.failed.is_set()


def test_heartbeat_never_renews_after_stop_is_requested():
    from autonomy.science_run._supervisor import Heartbeat, Stop

    left, right = socket.socketpair()
    with left, right, Stop(30) as stop:
        control = Control(left, lease=1.0)
        os.kill(os.getpid(), signal.SIGTERM)
        with Heartbeat(control, 0.05, stop=stop):
            right.settimeout(0.2)
            with pytest.raises(TimeoutError):
                right.recv(4096)


def test_journal_failure_still_dispatches_both_closes(tmp_path, monkeypatch):
    from autonomy.science_run import _supervisor

    observed = []

    def unavailable(*args, **kwargs):
        raise OSError("close journal unavailable")

    monkeypatch.setattr(_supervisor, "append_event", unavailable)

    class Endpoint:
        seal_timeout = 1

        @property
        def control(self):
            return self

        def seal(self, deadline):
            observed.append("seal")
            raise EOFError

        def close(self, *, grace=None):
            observed.append("endpoint closed")

    class Proxy:
        def send_close(self):
            observed.append("proxy close")

        def wait_close(self, deadline):
            return EgressClosed("close", 0, False)

    with pytest.raises(OSError, match="close journal unavailable"):
        _supervisor.finish(tmp_path, Endpoint(), Proxy(), None, (), "sigterm")
    assert sorted(observed) == ["endpoint closed", "proxy close", "seal"]


def test_selected_route_denies_credentials_from_every_configured_route(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from autonomy.egress.route import load_route
    from autonomy.science_run import _supervisor
    from egress_fixtures import pi_route, write_credential, write_route

    config = tmp_path / "config"
    selected = write_credential(tmp_path / "chosen")
    other = write_credential(tmp_path / "another")
    for name, credential in (("one", selected), ("two", other)):
        write_route(config, name, pi_route(credential=credential, upstream="https://127.0.0.1:1"))
    route = load_route(config, "one")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    opened = SimpleNamespace(route=route, dirs=SimpleNamespace(scratch=scratch, run_dir=scratch),
                             places=SimpleNamespace(config=config, state=tmp_path / "state"))
    endpoint = SimpleNamespace(actor_socket=tmp_path / "sock", token=tmp_path / "token")
    opening = SimpleNamespace(config=SimpleNamespace(denied=()), heads=SimpleNamespace(chains=()), toolchain=())

    class Inspected(Exception):
        pass

    def check(_spec, denied):
        assert selected in denied and other in denied
        raise Inspected

    monkeypatch.setattr(_supervisor.bwrap, "preflight", lambda: None)
    monkeypatch.setattr(_supervisor, "check_binds", check)
    with pytest.raises(Inspected):
        _supervisor._prove(opened, opening, endpoint, None)


def test_failed_postclaim_read_does_not_assert_a_baseline_race(tmp_path):
    from types import SimpleNamespace

    from autonomy.endpoint import EndpointError
    from autonomy.science_reads import ReadUnavailable
    from autonomy.science_run._supervisor import _checked_heads

    def fail(**_):
        raise ReadUnavailable("unavailable fixture heads")

    opening = SimpleNamespace(config=SimpleNamespace(verify=lambda: None),
                              reader=SimpleNamespace(heads=fail))
    with pytest.raises(EndpointError) as caught:
        _checked_heads(opening, tmp_path)
    assert caught.value.code == "read-unavailable"
    assert not (tmp_path / "events.jsonl").exists()
