import os
import secrets
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from autonomy.sandbox.bwrap import launch
from autonomy.sandbox.spec import SandboxSpec
from autonomy.sandbox.static import SandboxUnproven

pytestmark = pytest.mark.bwrap


def marker() -> str:
    # a sleep duration no other process on the host is using
    return f"{4000 + secrets.randbelow(1000)}.{secrets.randbelow(10**6)}"


def alive(mark: str) -> list[int]:
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if mark.encode() in cmdline and b"sleep" in cmdline:
            found.append(int(entry.name))
    return found


def gone_within(mark: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(mark):
            return True
        time.sleep(0.1)
    return not alive(mark)


def actor(mark: str) -> list[str]:
    return ["/usr/bin/sh", "-c", f"/usr/bin/sleep {mark} & /usr/bin/sleep {mark}"]


def test_terminate_kills_every_process_in_the_namespace(tmp_path):
    mark = marker()
    sandboxed = launch(SandboxSpec(scratch=tmp_path), actor(mark))
    try:
        deadline = time.monotonic() + 5
        while len(alive(mark)) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        # two sleepers, plus the shell unless it exec'd its last command
        assert len(alive(mark)) >= 2
        sandboxed.terminate(grace=1.0)
        assert gone_within(mark, 5)
    finally:
        sandboxed.close()


def test_the_actor_dies_with_its_orchestrator(tmp_path):
    mark = marker()
    orchestrator = textwrap.dedent(f"""
        import sys, time
        from pathlib import Path
        from autonomy.sandbox.bwrap import launch
        from autonomy.sandbox.spec import SandboxSpec
        launch(SandboxSpec(scratch=Path({str(tmp_path)!r})), {actor(mark)!r})
        print("ready", flush=True)
        time.sleep(300)
    """)
    parent = subprocess.Popen([sys.executable, "-c", orchestrator], stdout=subprocess.PIPE, text=True)
    try:
        assert parent.stdout.readline().strip() == "ready"
        deadline = time.monotonic() + 5
        while not alive(mark) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert alive(mark)
        parent.send_signal(signal.SIGKILL)
        parent.wait()
        assert gone_within(mark, 5)
    finally:
        if parent.poll() is None:
            parent.kill()


def test_launch_refuses_any_thread_but_the_main_one(tmp_path):
    # PR_SET_PDEATHSIG fires when the spawning thread exits; a short-lived thread would
    # kill the actor early, so the rule is enforced rather than documented
    caught: list[BaseException] = []

    def body():
        try:
            launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"])
        except BaseException as error:
            caught.append(error)

    thread = threading.Thread(target=body)
    thread.start()
    thread.join()
    assert len(caught) == 1 and isinstance(caught[0], RuntimeError)


def test_a_fast_child_is_held_until_its_handle_exists(tmp_path, monkeypatch):
    # the reviewer's reproduction: delay the handle; without --block-fd the child of
    # /usr/bin/true is gone first and pidfd_open raises ProcessLookupError
    real = os.pidfd_open

    def slow(pid, *args):
        time.sleep(0.3)
        return real(pid, *args)

    monkeypatch.setattr(os, "pidfd_open", slow)
    sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"])
    try:
        assert sandboxed.wait(timeout=10) == 0
    finally:
        sandboxed.close()


def test_a_child_lost_before_release_is_reaped(tmp_path, monkeypatch):
    started: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    class Recording(real_popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            started.append(self)

    def vanished(pid, *args):
        raise ProcessLookupError(pid)

    monkeypatch.setattr(subprocess, "Popen", Recording)
    monkeypatch.setattr(os, "pidfd_open", vanished)
    with pytest.raises(SandboxUnproven) as caught:
        launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"])
    assert caught.value.code == "launch-failed"
    assert len(started) == 1 and started[0].returncode is not None  # killed and reaped


def test_a_binary_missing_from_the_sandbox_fails_promptly(tmp_path):  # Review Focus 5
    started = time.monotonic()
    try:
        sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/opt/not-in-sandbox"])
    except SandboxUnproven as error:
        assert error.code == "launch-failed"
    else:
        try:
            assert sandboxed.wait(timeout=10) != 0
        finally:
            sandboxed.close()
    assert time.monotonic() - started < 10


@pytest.mark.parametrize(("module", "name"), [(os, "pidfd_open"), (signal, "pidfd_send_signal")])
def test_an_interpreter_without_pidfds_is_refused_before_anything_starts(tmp_path, monkeypatch, module, name):
    # uv's managed CPython builds omit both calls; the run must fail early, not fall back
    started: list[object] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a))
    monkeypatch.delattr(module, name)
    with pytest.raises(SandboxUnproven) as caught:
        launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"])
    assert caught.value.code == "pidfd-unavailable"
    assert started == []
