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
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from autonomy.sandbox import bwrap
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


@pytest.mark.parametrize("actor_fsize_bytes", [None, 8192])
def test_the_actor_dies_with_its_orchestrator(tmp_path, actor_fsize_bytes):
    mark = marker()
    orchestrator = textwrap.dedent(f"""
        import os, sys, time
        from pathlib import Path
        from autonomy.sandbox.bwrap import launch
        from autonomy.sandbox.spec import SandboxSpec
        null = os.open(os.devnull, os.O_RDWR)
        launch(SandboxSpec(scratch=Path({str(tmp_path)!r})), {actor(mark)!r}, stdin=null, stdout=null, stderr=null,\n               **{({"actor_fsize_bytes": actor_fsize_bytes} if actor_fsize_bytes is not None else {})!r})
        print("ready", flush=True)
        time.sleep(300)
    """)
    parent = subprocess.Popen([sys.executable, "-c", orchestrator], stdout=subprocess.PIPE, text=True,
                              env={"PATH": "/usr/bin", "HOME": str(tmp_path), "LC_ALL": "C"})
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
            parent.wait(timeout=5)


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

    def spy(spec, argv, *, info_fd, gate_fd=None):
        assert gate_fd is not None
        seen.append(gate_fd)
        return real(spec, argv, info_fd=info_fd, gate_fd=gate_fd)

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


def test_launch_survives_a_caller_with_fds_0_1_2_closed(tmp_path):
    # os.pipe() takes the lowest free fds: with 0-2 closed the gate's and bwrap's pipes
    # would land there and be overwritten by the actor's explicit stdio
    out = tmp_path / "outcome"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    orchestrator = textwrap.dedent(f"""
        import os
        from pathlib import Path
        import autonomy.sandbox.bwrap as bwrap
        from autonomy.sandbox.spec import SandboxSpec
        bwrap.LAUNCH_TIMEOUT = 5
        import fcntl
        null = [fcntl.fcntl(os.open(os.devnull, os.O_RDWR), fcntl.F_DUPFD, 10) for _ in range(3)]
        for fd in (0, 1, 2):
            os.close(fd)
        try:
            s = bwrap.launch(SandboxSpec(scratch=Path({str(scratch)!r})),
                             ["/usr/bin/sh", "-c", "echo ran > ran"], stdin=null[0], stdout=null[1], stderr=null[2])
            result = str(s.wait(timeout=10))
            s.close()
        except BaseException as caught:
            result = repr(caught)
        Path({str(out)!r}).write_text(result)
    """)
    subprocess.run([sys.executable, "-c", orchestrator], stdin=subprocess.DEVNULL, timeout=60)
    assert out.read_text() == "0"
    assert (scratch / "ran").exists()


@pytest.mark.parametrize("identity", ["different-device", "different-inode", "same", "unreadable"])
def test_launch_requires_distinct_network_namespace_evidence(tmp_path, stdio, monkeypatch, identity):
    real_stat = os.stat
    host = real_stat("/proc/self/ns/net")
    flag = tmp_path / "ran"

    def stat(path, *args, **kwargs):
        if isinstance(path, str) and path.startswith("/proc/") and path.endswith("/ns/net"):
            pid = path.split("/")[2]
            if pid.isdecimal():
                if identity == "unreadable":
                    raise PermissionError("namespace evidence unavailable")
                return SimpleNamespace(
                    st_dev=host.st_dev + (identity == "different-device"),
                    st_ino=host.st_ino + (identity == "different-inode"),
                )
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)
    spec = SandboxSpec(scratch=tmp_path)
    attached = []
    actor_argv = ["/usr/bin/touch", str(flag)]

    def attach(child_pid, _pidfd):
        attached.append(child_pid)

    if identity.startswith("different"):
        with closing(launch(spec, actor_argv, before_release=attach, **stdio)) as sandbox:
            assert sandbox.wait(timeout=10) == 0
        assert attached == [sandbox.child_pid]
        assert flag.exists()
    else:
        with pytest.raises(SandboxUnproven) as caught:
            with closing(launch(spec, actor_argv, before_release=attach, **stdio)) as sandbox:
                sandbox.wait(timeout=10)
        assert caught.value.code == "probe-network"
        assert attached == []
        assert not flag.exists()


def test_launch_refuses_a_real_shared_network_namespace(tmp_path, stdio, monkeypatch):
    build = bwrap.build_argv
    flag = tmp_path / "ran"

    def share_network(*args, **kwargs):
        argv = build(*args, **kwargs)
        return [*argv[:2], "--share-net", *argv[2:]]

    monkeypatch.setattr(bwrap, "build_argv", share_network)
    with pytest.raises(SandboxUnproven) as caught:
        with closing(launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/touch", str(flag)], **stdio)) as sandbox:
            sandbox.wait(timeout=10)
    assert caught.value.code == "probe-network"
    assert not flag.exists()


def test_launch_refuses_namespace_evidence_from_an_exited_child(tmp_path, stdio, monkeypatch):
    real_stat = os.stat
    real_open = os.pidfd_open
    child_namespace = None
    pidfd = None
    flag = tmp_path / "ran"

    def pidfd_open(pid):
        nonlocal child_namespace, pidfd
        child_namespace = f"/proc/{pid}/ns/net"
        pidfd = real_open(pid)
        return pidfd

    def stat(path, *args, **kwargs):
        info = real_stat(path, *args, **kwargs)
        if path == child_namespace:
            signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            poll = select.poll()
            poll.register(pidfd, select.POLLIN)
            assert poll.poll(5000), "namespace init did not exit"
        return info

    monkeypatch.setattr(os, "pidfd_open", pidfd_open)
    monkeypatch.setattr(os, "stat", stat)
    with pytest.raises(SandboxUnproven, match="exited") as caught:
        with closing(launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/touch", str(flag)], **stdio)) as sandbox:
            sandbox.wait(timeout=10)
    assert caught.value.code == "probe-network"
    assert not flag.exists()


def test_before_release_runs_while_the_gate_still_holds_the_actor(tmp_path, stdio):
    flag = tmp_path / "ran"
    spec = SandboxSpec(scratch=tmp_path)
    seen = {}

    def hook(child_pid: int, pidfd: int) -> None:
        seen["child"] = child_pid
        seen["pidfd_alive"] = signal.pidfd_send_signal(pidfd, 0) is None
        time.sleep(0.5)  # an actor already released would have touched the flag by now
        seen["ran_before_release"] = flag.exists()

    sandbox = launch(spec, ["/usr/bin/touch", str(flag)], before_release=hook, **stdio)
    try:
        assert sandbox.wait(timeout=30) == 0
    finally:
        sandbox.close()
    assert seen == {"child": sandbox.child_pid, "pidfd_alive": True, "ran_before_release": False}
    assert flag.exists()


class HookFailed(Exception):
    pass


def test_a_failing_hook_aborts_and_propagates_unchanged(tmp_path, stdio):
    flag = tmp_path / "ran"

    def hook(child_pid: int, pidfd: int) -> None:
        time.sleep(0.5)  # an actor already released would run in this time
        raise HookFailed("no listener")

    with pytest.raises(HookFailed):
        launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/touch", str(flag)], before_release=hook, **stdio)
    time.sleep(0.5)
    assert not flag.exists()


def test_a_hook_that_swallows_its_failure_releases_the_actor(tmp_path, stdio):
    # Negative: a launch that ignores a helper failure runs the actor anyway,
    # which is why `before_release` must propagate, never be wrapped in a try.
    flag = tmp_path / "ran"

    def careless(child_pid: int, pidfd: int) -> None:
        try:
            raise HookFailed("no listener")
        except HookFailed:
            pass

    sandbox = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/touch", str(flag)], before_release=careless, **stdio)
    try:
        assert sandbox.wait(timeout=30) == 0
    finally:
        sandbox.close()
    assert flag.exists()


def test_science_binding_failure_cannot_release_the_actor(tmp_path, stdio):
    from autonomy.endpoint import EndpointError

    marker_path = tmp_path / "started"
    ready = threading.Event()

    def refuse_binding(_pid, _pidfd):
        ready.set()
        raise EndpointError("missing bound acknowledgement")

    with pytest.raises(EndpointError, match="missing bound"):
        launch(SandboxSpec(scratch=tmp_path),
               ["/usr/bin/touch", str(marker_path)], before_release=refuse_binding, **stdio)
    assert ready.is_set()
    assert not marker_path.exists()


@pytest.mark.parametrize("size", [1, 70 * 1024])
def test_actor_receives_exact_environment(tmp_path, stdio, size):
    home = tmp_path / "home"
    home.mkdir()
    output = tmp_path / "environment"
    with output.open("wb") as stream:
        with closing(launch(SandboxSpec(scratch=tmp_path, env={"HOME": str(home), "A": "a" * size, "B": "b" * size}),
                            ["/usr/bin/env", "-0"], **{**stdio, "stdout": stream.fileno()})) as sandbox:
            assert sandbox.wait(timeout=10) == 0
    assert set(output.read_bytes().rstrip(b"\0").split(b"\0")) == {
        b"PATH=/usr/bin", os.fsencode(f"HOME={home}"), b"A=" + b"a" * size, b"B=" + b"b" * size,
    }


def test_gate_passes_a_leading_dash_as_the_actor_name(tmp_path, stdio):
    executable = tmp_path / "-actor"
    executable.write_text("#!/usr/bin/sh\nexit 12\n")
    executable.chmod(0o700)
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path)}
    with closing(launch(SandboxSpec(scratch=tmp_path, env=env), ["-actor"], **stdio)) as sandbox:
        assert sandbox.wait(timeout=10) == 12


def test_launch_rejects_empty_actor_argv(tmp_path, stdio, monkeypatch):
    def no_child(*args, **kwargs):
        pytest.fail("invalid argv reached Popen")

    monkeypatch.setattr(subprocess, "Popen", no_child)
    with pytest.raises(SandboxUnproven) as caught:
        launch(SandboxSpec(scratch=tmp_path), iter(()), **stdio)
    assert caught.value.code == "launch-failed"


def test_launch_discards_a_pidfd_when_bwrap_has_exited(tmp_path, stdio, monkeypatch):
    started = recording_popen(monkeypatch)
    handle = os.open(os.devnull, os.O_RDONLY)
    signalled = []
    checked = []

    def acquire(pid):
        started[0].kill()
        started[0].wait(timeout=5)
        return handle

    def namespace_check(*args):
        checked.append(args)
        raise SandboxUnproven("probe-network", "test", "unexpected namespace check")

    monkeypatch.setattr(os, "pidfd_open", acquire)
    monkeypatch.setattr(bwrap, "_check_network_namespace", namespace_check)
    monkeypatch.setattr(signal, "pidfd_send_signal", lambda *args: signalled.append(args))
    with pytest.raises(SandboxUnproven) as caught:
        launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"], **stdio)
    assert caught.value.code == "launch-failed"
    assert not signalled and not checked
    with pytest.raises(OSError):
        os.fstat(handle)


@pytest.mark.parametrize("failure", ["signal", "timeout"])
def test_abort_closes_pidfd_and_bounds_reaping(monkeypatch, failure):
    handle = os.open(os.devnull, os.O_RDONLY)
    killed = []

    def send(*args):
        if failure == "signal":
            raise PermissionError("pidfd signal refused")

    def wait(timeout=None):
        assert timeout is not None
        if failure == "timeout":
            raise subprocess.TimeoutExpired("bwrap", timeout)
        return -signal.SIGKILL

    process = SimpleNamespace(poll=lambda: None, kill=lambda: killed.append(True), wait=wait)
    monkeypatch.setattr(signal, "pidfd_send_signal", send)
    try:
        with pytest.raises(SandboxUnproven, match="cleanup"):
            bwrap._abort(process, handle)
        assert killed == [True]
        with pytest.raises(OSError):
            os.fstat(handle)
    finally:
        if not killed:
            os.close(handle)


def test_second_pipe_failure_releases_the_first_pipe(tmp_path, stdio, monkeypatch):
    create = bwrap._pipe_above_stdio
    calls = 0

    def one_pipe():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("pipe allocation failed")
        return create()

    monkeypatch.setattr(bwrap, "_pipe_above_stdio", one_pipe)
    before = open_fds()
    try:
        with pytest.raises(OSError, match="allocation"):
            launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"], **stdio)
        assert open_fds() == before
    finally:
        for fd in open_fds() - before:
            try:
                os.close(fd)
            except OSError:
                pass


def test_cleanup_failure_keeps_the_launch_callback_error(tmp_path, stdio, monkeypatch):
    original_abort = bwrap._abort

    class HookFailed(Exception):
        pass

    error = HookFailed("callback error")

    def hook(*args):
        raise error

    def abort_with_failure(*args):
        original_abort(*args)
        raise SandboxUnproven("launch-failed", "bwrap", "cleanup failed")

    monkeypatch.setattr(bwrap, "_abort", abort_with_failure)
    with pytest.raises(HookFailed) as caught:
        launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"], before_release=hook, **stdio)
    assert caught.value is error
    assert isinstance(error.__cause__, SandboxUnproven)
    assert "cleanup" in str(error.__cause__)


def test_pinned_worker_receives_term_below_namespace_init(tmp_path, stdio):
    import time
    from autonomy.science_run._supervisor import _stop_actor

    actor_code = """import pathlib,signal,time
p=pathlib.Path.cwd()
def stopped(*args):
    (p/'flushed').write_text('closed')
    raise SystemExit(0)
signal.signal(signal.SIGTERM,stopped)
(p/'ready').touch()
while True: time.sleep(1)
"""
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    actor = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/python3", "-I", "-c", actor_code],
                   track_worker=True, **stdio)
    try:
        deadline = time.monotonic() + 4
        while not (tmp_path / "ready").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (tmp_path / "ready").exists()
        _stop_actor(actor, run_dir)
        assert (tmp_path / "flushed").read_text() == "closed"
    finally:
        actor.close()


@pytest.mark.parametrize("bounded", [False, True])
def test_supervisor_environment_never_reaches_proc_in_launch(tmp_path, bounded):
    canary = f"va-supervisor-canary-{secrets.token_hex(16)}"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    supervisor = textwrap.dedent(r"""
        import json, os, sys
        from contextlib import closing
        from pathlib import Path
        from autonomy.sandbox.bwrap import launch
        from autonomy.sandbox.spec import SandboxSpec, Storage

        scratch = Path(sys.argv[1])
        needle_hex = sys.argv[2]
        bounded = sys.argv[3] == "1"
        actor_code = '''
        import json, os, sys
        needle = bytes.fromhex(sys.argv[1])
        leaked = []
        for pid in sorted(os.listdir("/proc")):
            if not pid.isdigit():
                continue
            for part in ("environ", "cmdline"):
                raw = open(f"/proc/{pid}/{part}", "rb").read()
                if needle in raw:
                    leaked.append(f"/proc/{pid}/{part}")
        def parse_env(path):
            entries = open(path, "rb").read().rstrip(b"\\x00").split(b"\\x00")
            return dict(item.decode("utf-8").split("=", 1) for item in entries if item)
        init_cmd = open("/proc/1/cmdline", "rb").read()
        print(json.dumps({
            "leaked": leaked,
            "init_env": parse_env("/proc/1/environ"),
            "self_env": parse_env("/proc/self/environ"),
            "declared_in_init_cmdline": b"allowed-value" in init_cmd,
        }))
        '''
        storage = Storage(256 * os.sysconf("SC_PAGE_SIZE"), 64) if bounded else None
        spec = SandboxSpec(
            scratch=scratch,
            env={"ACTOR_DECLARED": "allowed-value"},
            disable_nested_userns=bounded,
            storage=storage,
        )
        out_read, out_write = os.pipe()
        null = os.open(os.devnull, os.O_RDWR)
        try:
            with closing(launch(
                spec,
                ["/usr/bin/python3", "-I", "-c", actor_code, needle_hex],
                stdin=null,
                stdout=out_write,
                stderr=null,
                actor_fsize_bytes=65536 if bounded else None,
            )) as sandbox:
                os.close(out_write)
                out_write = -1
                data = b""
                while chunk := os.read(out_read, 4096):
                    data += chunk
                assert sandbox.wait(timeout=15) == 0
            sys.stdout.buffer.write(data)
        finally:
            if out_write >= 0:
                os.close(out_write)
            os.close(out_read)
            os.close(null)
    """)
    result = subprocess.run(
        [sys.executable, "-c", supervisor, str(scratch), canary.encode().hex(), "1" if bounded else "0"],
        env={"PATH": "/usr/bin", "HOME": str(tmp_path), "LC_ALL": "C", "SUPERVISOR_CANARY": canary},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    report = __import__("json").loads(result.stdout)
    assert report["leaked"] == []
    assert report["init_env"] == {"PATH": "/usr/bin", "LC_ALL": "C"}
    assert report["self_env"] == {"PATH": "/usr/bin", "ACTOR_DECLARED": "allowed-value"}
    assert report["declared_in_init_cmdline"] is True

