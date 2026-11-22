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
    from autonomy.science_run._supervisor import Heartbeat

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
        with Heartbeat(control, 0.05) as beat:
            assert seen.wait(2)
            remote.result(timeout=2)
        assert not beat.failed.is_set()
