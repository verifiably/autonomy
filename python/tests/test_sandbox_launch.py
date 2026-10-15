import fcntl
import os
import secrets
import select
import signal
import socket
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


@pytest.fixture
def stdio():
    """The actor's three descriptors, each on /dev/null."""
    fds = {name: os.open(os.devnull, os.O_RDWR) for name in ("stdin", "stdout", "stderr")}
    yield fds
    for fd in fds.values():
        os.close(fd)


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


def test_terminate_kills_every_process_in_the_namespace(tmp_path, stdio):
    mark = marker()
    sandboxed = launch(SandboxSpec(scratch=tmp_path), actor(mark), **stdio)
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
        import os, sys, time
        from pathlib import Path
        from autonomy.sandbox.bwrap import launch
        from autonomy.sandbox.spec import SandboxSpec
        null = os.open(os.devnull, os.O_RDWR)
        launch(SandboxSpec(scratch=Path({str(tmp_path)!r})), {actor(mark)!r}, stdin=null, stdout=null, stderr=null)
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


def test_launch_refuses_any_thread_but_the_main_one(tmp_path, stdio):
    # PR_SET_PDEATHSIG fires when the spawning thread exits; a short-lived thread would
    # kill the actor early, so the rule is enforced rather than documented
    caught: list[BaseException] = []

    def body():
        try:
            launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"], **stdio)
        except BaseException as error:
            caught.append(error)

    thread = threading.Thread(target=body)
    thread.start()
    thread.join()
    assert len(caught) == 1 and isinstance(caught[0], RuntimeError)


def test_a_fast_child_is_held_until_its_handle_exists(tmp_path, stdio, monkeypatch):
    # the reviewer's reproduction: delay the handle; without --block-fd the child of
    # /usr/bin/true is gone first and pidfd_open raises ProcessLookupError
    real = os.pidfd_open

    def slow(pid, *args):
        time.sleep(0.3)
        return real(pid, *args)

    monkeypatch.setattr(os, "pidfd_open", slow)
    sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"], **stdio)
    try:
        assert sandboxed.wait(timeout=10) == 0
    finally:
        sandboxed.close()


def test_a_child_lost_before_release_is_reaped(tmp_path, stdio, monkeypatch):
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
        launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"], **stdio)
    assert caught.value.code == "launch-failed"
    assert len(started) == 1 and started[0].returncode is not None  # killed and reaped


def test_a_binary_missing_from_the_sandbox_fails_promptly(tmp_path, stdio):  # Review Focus 5
    started = time.monotonic()
    try:
        sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/opt/not-in-sandbox"], **stdio)
    except SandboxUnproven as error:
        assert error.code == "launch-failed"
    else:
        try:
            assert sandboxed.wait(timeout=10) != 0
        finally:
            sandboxed.close()
    assert time.monotonic() - started < 10


@pytest.mark.parametrize(("module", "name"), [(os, "pidfd_open"), (signal, "pidfd_send_signal")])
def test_an_interpreter_without_pidfds_is_refused_before_anything_starts(tmp_path, stdio, monkeypatch, module, name):
    # uv's managed CPython builds omit both calls; the run must fail early, not fall back
    started: list[object] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a))
    monkeypatch.delattr(module, name)
    with pytest.raises(SandboxUnproven) as caught:
        launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"], **stdio)
    assert caught.value.code == "pidfd-unavailable"
    assert started == []


def recording_popen(monkeypatch) -> list[subprocess.Popen]:
    started: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    class Recording(real_popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            started.append(self)

    monkeypatch.setattr(subprocess, "Popen", Recording)
    return started


def test_an_unexpected_error_after_popen_never_releases_the_actor(tmp_path, stdio, monkeypatch):
    import errno

    started = recording_popen(monkeypatch)

    def exhausted(pid, *args):
        raise OSError(errno.EMFILE, "Too many open files")

    monkeypatch.setattr(os, "pidfd_open", exhausted)
    with pytest.raises(SandboxUnproven) as caught:
        launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/sh", "-c", "echo ran > ran"], **stdio)
    assert caught.value.code == "launch-failed"
    assert len(started) == 1 and started[0].returncode is not None  # killed and reaped
    time.sleep(0.3)
    assert not (tmp_path / "ran").exists()  # the held command never ran


def test_a_bwrap_that_never_reports_its_child_is_reaped(tmp_path, stdio, monkeypatch):
    import autonomy.sandbox.bwrap as bwrap

    started = recording_popen(monkeypatch)
    monkeypatch.setattr(bwrap, "LAUNCH_TIMEOUT", 0.5)
    monkeypatch.setattr(bwrap, "build_argv", lambda *a, **k: ["/usr/bin/sleep", "30"])
    begun = time.monotonic()
    with pytest.raises(SandboxUnproven) as caught:
        launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"], **stdio)
    assert caught.value.code == "launch-failed"
    assert time.monotonic() - begun < 5
    assert started[0].returncode is not None


def test_close_twice_never_touches_an_unrelated_fd(tmp_path, stdio):
    sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"], **stdio)
    sandboxed.wait(timeout=10)
    sandboxed.close()
    read_fd, write_fd = os.pipe()  # likely reuses the pidfd's number
    try:
        sandboxed.close()
        assert sandboxed.terminate(grace=0.1) == 0
        os.write(write_fd, b"x")  # still open
        assert os.read(read_fd, 1) == b"x"
    finally:
        os.close(read_fd)
        os.close(write_fd)


def open_fds() -> set[int]:
    return {int(name) for name in os.listdir("/proc/self/fd")}


@pytest.mark.parametrize("failure", [BrokenPipeError, KeyboardInterrupt])
def test_a_failed_release_never_runs_the_actor_and_leaks_nothing(tmp_path, stdio, monkeypatch, failure):
    import autonomy.sandbox.bwrap as bwrap

    started = recording_popen(monkeypatch)
    real_write = os.write

    def failing_release(fd, data):
        if data == bwrap.RELEASE:
            raise failure()
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", failing_release)
    before = open_fds()
    with pytest.raises((SandboxUnproven, KeyboardInterrupt)) as caught:
        launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/sh", "-c", "echo ran > ran"], **stdio)
    if failure is BrokenPipeError:
        assert caught.value.code == "launch-failed"
    assert started[0].returncode is not None  # reaped
    assert open_fds() <= before  # the pidfd and pipes are closed
    time.sleep(0.3)
    assert not (tmp_path / "ran").exists()


def test_the_actor_never_sees_the_gate(tmp_path, stdio):
    sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/sh", "-c", "ls /proc/self/fd > fds"], **stdio)
    try:
        assert sandboxed.wait(timeout=10) == 0
    finally:
        sandboxed.close()
    assert sorted((tmp_path / "fds").read_text().split()) == ["0", "1", "2", "3"]  # 3 is ls's own dir fd


def read_all(fd: int, timeout: float = 10.0) -> bytes:
    data = b""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        assert remaining > 0, f"no EOF on fd {fd} within {timeout} s"
        if not select.select([fd], [], [], remaining)[0]:
            continue
        chunk = os.read(fd, 65536)
        if not chunk:
            return data
        data += chunk


@pytest.fixture
def gate_fds(monkeypatch):
    """The gate's release fd, as launch hands it to bwrap."""
    import autonomy.sandbox.bwrap as bwrap

    seen: list[int] = []
    real = bwrap.build_argv

    def spy(spec, argv, *, info_fd):
        seen.append(int(argv[4]))  # ["/usr/bin/python3", "-I", "-c", _GATE, <fd>, *actor]
        return real(spec, argv, info_fd=info_fd)

    monkeypatch.setattr(bwrap, "build_argv", spy)
    return seen


def channel_pair(kind: str) -> tuple[int, int, int, int]:
    """(actor's stdin, caller's writer, caller's reader, actor's stdout)."""
    if kind == "pipe":
        in_read, in_write = os.pipe()
        out_read, out_write = os.pipe()
        return in_read, in_write, out_read, out_write
    a, b = socket.socketpair()
    c, d = socket.socketpair()
    return a.detach(), b.detach(), c.detach(), d.detach()


@pytest.mark.parametrize("kind", ["pipe", "socket"])
def test_bytes_reach_the_actor_across_the_gate(tmp_path, gate_fds, kind):
    held = [os.open(os.devnull, os.O_RDONLY) for _ in range(14)]  # fds 3–16: the gate's pipe lands above 9
    actor_in, caller_in, caller_out, actor_out = channel_pair(kind)
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        os.write(caller_in, b"before\n")
        sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/cat"], stdin=actor_in, stdout=actor_out, stderr=null)
        os.close(actor_in)
        os.close(actor_out)
        try:
            os.write(caller_in, b"after\n")
            os.close(caller_in)
            assert read_all(caller_out) == b"before\nafter\n"
            assert sandboxed.wait(timeout=10) == 0
        finally:
            sandboxed.close()
    finally:
        for fd in (*held, null, caller_out):
            os.close(fd)
    assert gate_fds and gate_fds[0] > 9


SIGPIPE_BIT = 1 << (signal.SIGPIPE - 1)
SIGXFSZ_BIT = 1 << (signal.SIGXFSZ - 1)


def ignored_signals(tmp_path, stdio) -> int:
    sandboxed = launch(
        SandboxSpec(scratch=tmp_path), ["/usr/bin/sh", "-c", "grep SigIgn /proc/self/status > sigign"], **stdio
    )
    try:
        assert sandboxed.wait(timeout=10) == 0
    finally:
        sandboxed.close()
    return int((tmp_path / "sigign").read_text().split()[1], 16)


def test_the_actor_inherits_no_ignored_sigpipe_or_sigxfsz(tmp_path, stdio):  # Review Focus 1
    assert ignored_signals(tmp_path, stdio) & (SIGPIPE_BIT | SIGXFSZ_BIT) == 0


def test_a_gate_that_keeps_pythons_dispositions_ignores_sigpipe(tmp_path, stdio, monkeypatch):
    import autonomy.sandbox.bwrap as bwrap

    kept = "\n".join(line for line in bwrap._GATE.splitlines() if "SIG_DFL" not in line)
    monkeypatch.setattr(bwrap, "_GATE", kept)
    assert ignored_signals(tmp_path, stdio) & SIGPIPE_BIT


def test_a_gate_that_keeps_its_fd_shows_a_fifth_descriptor(tmp_path, stdio, monkeypatch):
    import autonomy.sandbox.bwrap as bwrap

    monkeypatch.setattr(bwrap, "_GATE", bwrap._GATE.replace("os.close(gate)\n", ""))
    sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/sh", "-c", "ls /proc/self/fd > fds"], **stdio)
    try:
        assert sandboxed.wait(timeout=10) == 0
    finally:
        sandboxed.close()
    assert len((tmp_path / "fds").read_text().split()) == 5


def test_run_on_stdin_never_releases_the_actor(tmp_path, monkeypatch):
    import autonomy.sandbox.bwrap as bwrap

    real_write = os.write
    monkeypatch.setattr(os, "write", lambda fd, data: len(data) if data == bwrap.RELEASE else real_write(fd, data))
    in_read, in_write = os.pipe()
    real_write(in_write, b"run\n")
    os.close(in_write)
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        sandboxed = launch(
            SandboxSpec(scratch=tmp_path), ["/usr/bin/sh", "-c", "echo ran > ran"], stdin=in_read, stdout=null, stderr=null
        )
        try:
            assert sandboxed.wait(timeout=10) == 125
        finally:
            sandboxed.close()
    finally:
        os.close(in_read)
        os.close(null)
    assert not (tmp_path / "ran").exists()


def test_a_report_fd_never_reaches_the_actor(tmp_path, stdio, monkeypatch):
    report_read, report_write = os.pipe()
    os.set_inheritable(report_write, True)  # even an inheritable one
    try:
        sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/sh", "-c", "ls /proc/self/fd > fds"], **stdio)
        try:
            assert sandboxed.wait(timeout=10) == 0
        finally:
            sandboxed.close()
        assert sorted((tmp_path / "fds").read_text().split()) == ["0", "1", "2", "3"]

        real = subprocess.Popen

        class Passing(real):
            def __init__(self, *args, **kwargs):
                kwargs["pass_fds"] = (*kwargs.get("pass_fds", ()), report_write)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(subprocess, "Popen", Passing)
        (tmp_path / "fds").unlink()
        sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/sh", "-c", "ls /proc/self/fd > fds"], **stdio)
        try:
            assert sandboxed.wait(timeout=10) == 0
        finally:
            sandboxed.close()
        assert len((tmp_path / "fds").read_text().split()) == 5  # a launch that passes it shows a fifth
    finally:
        os.close(report_read)
        os.close(report_write)


def test_bwrap_runs_in_a_process_group_of_its_own(tmp_path, stdio):
    sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/sleep", "5"], **stdio)
    try:
        assert os.getpgid(sandboxed.process.pid) == sandboxed.process.pid != os.getpgid(0)
    finally:
        sandboxed.close()


def test_a_closed_actor_descriptor_is_refused_before_anything_starts(tmp_path, stdio, monkeypatch):
    started: list[object] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a))
    closed = os.open(os.devnull, os.O_RDONLY)
    os.close(closed)
    with pytest.raises(ValueError, match="stdout"):
        launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"], **{**stdio, "stdout": closed})
    assert started == []


@pytest.mark.skipif(not Path("/usr/bin/dash").exists(), reason="needs /usr/bin/dash")
def test_a_shell_gate_under_dash_fails_on_an_fd_above_9():
    gate_read, gate_write = os.pipe()
    # a fresh descriptor above 9, never one another fixture or pytest already holds
    high = fcntl.fcntl(gate_read, fcntl.F_DUPFD_CLOEXEC, 10)
    os.close(gate_read)
    try:
        os.write(gate_write, b"run\n")
        result = subprocess.run(
            ["/usr/bin/dash", "-c", f"read -r go <&{high}"], pass_fds=(high,), capture_output=True, text=True,
            stdin=subprocess.DEVNULL,
        )
    finally:
        os.close(high)
        os.close(gate_write)
    assert high > 9
    assert result.returncode != 0 and "Bad fd number" in result.stderr


def test_a_release_read_on_stdin_eats_the_callers_first_line():
    in_read, in_write = os.pipe()
    os.write(in_write, b"before\nafter\n")
    os.close(in_write)
    try:
        result = subprocess.run(
            ["/usr/bin/sh", "-c", 'read -r go; [ "$go" = run ] || exit 125; exec cat'], stdin=in_read, capture_output=True
        )
    finally:
        os.close(in_read)
    assert result.returncode == 125 and result.stdout == b""


def test_a_gate_that_reopens_stdin_gives_the_actor_immediate_eof():
    in_read, in_write = os.pipe()
    os.write(in_write, b"before\n")
    os.close(in_write)
    try:
        result = subprocess.run(["/usr/bin/sh", "-c", "exec </dev/null; exec cat"], stdin=in_read, capture_output=True)
    finally:
        os.close(in_read)
    assert result.returncode == 0 and result.stdout == b""
