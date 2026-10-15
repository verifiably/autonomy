"""The bwrap driver (envelope design §7, §8): argv, preflight, the denial probe,
and (Task 7) launch and kill."""

from __future__ import annotations

import fcntl
import json
import os
import select
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from autonomy.sandbox.spec import IN_SANDBOX_SOCKET, IN_SANDBOX_TOKEN, SYSTEM_RO, SYSTEM_SYMLINKS, SandboxSpec
from autonomy.sandbox.static import SandboxUnproven, check_binds

_PROBE = """\
import errno, os, sys
for path in sys.argv[1:]:
    try:
        os.stat(path)
        print("REACHABLE", path)
    except OSError as caught:
        print(errno.errorcode.get(caught.errno, str(caught.errno)), path)
"""


def preflight(which: Callable[[str], str | None] = shutil.which) -> None:
    if which("bwrap") is None:
        raise SandboxUnproven("bwrap-missing", "bwrap", "bubblewrap is not on PATH")
    trial = [
        "bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr",
        *[arg for target, link in SYSTEM_SYMLINKS for arg in ("--symlink", target, link)],
        "--", "/usr/bin/true",
    ]
    try:
        result = subprocess.run(trial, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise SandboxUnproven("userns-unavailable", "bwrap", "the trial sandbox did not exit in 30 s") from None
    if result.returncode != 0:
        raise SandboxUnproven("userns-unavailable", "bwrap", result.stderr.strip() or f"exit {result.returncode}")


def build_argv(
    spec: SandboxSpec, argv: Iterable[str], *, info_fd: int | None
) -> list[str]:
    args = ["bwrap", "--unshare-all"]
    if spec.network == "host":
        args.append("--share-net")
    args += ["--die-with-parent", "--new-session", "--clearenv", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for path in SYSTEM_RO:
        args += ["--ro-bind", str(path), str(path)]
    for target, link in SYSTEM_SYMLINKS:
        args += ["--symlink", target, link]
    for path in spec.ro_binds:
        args += ["--ro-bind", str(path), str(path)]
    args += ["--bind", str(spec.scratch), str(spec.scratch)]
    if spec.socket is not None or spec.token is not None:
        args += ["--dir", "/run/va"]
    if spec.socket is not None:
        args += ["--bind", str(spec.socket), str(IN_SANDBOX_SOCKET)]
    if spec.token is not None:
        args += ["--ro-bind", str(spec.token), str(IN_SANDBOX_TOKEN)]
    env = {"PATH": "/usr/bin", **spec.env}
    for key, value in sorted(env.items()):
        args += ["--setenv", key, value]
    args += ["--chdir", str(spec.scratch)]
    if info_fd is not None:
        args += ["--info-fd", str(info_fd)]
    return [*args, "--", *argv]


def probe(spec: SandboxSpec, denied: Iterable[Path]) -> None:
    paths = [str(p.resolve()) for p in denied]
    argv = build_argv(spec, ["/usr/bin/python3", "-I", "-c", _PROBE, *paths], info_fd=None)
    try:
        result = subprocess.run(argv, capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise SandboxUnproven("probe-failed", "bwrap", "the probe did not exit in 60 s") from None
    stdout = result.stdout.decode("utf-8", errors="replace")
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise SandboxUnproven("probe-failed", "bwrap", stderr or f"exit {result.returncode}")
    lines = stdout.splitlines()
    if len(lines) != len(paths):
        raise SandboxUnproven("probe-failed", "bwrap", f"expected {len(paths)} lines, got {len(lines)}")
    for path, line in zip(paths, lines, strict=True):
        status, _, reported = line.partition(" ")
        if reported != path or status != "ENOENT":
            raise SandboxUnproven("probe-reachable", path, f"stat inside the sandbox gave {status}, not ENOENT")


def prove(spec: SandboxSpec, denied: Iterable[Path], *, which: Callable[[str], str | None] = shutil.which) -> None:
    denied = tuple(denied)
    preflight(which)
    check_binds(spec, denied)
    probe(spec, denied)


@dataclass
class Sandboxed:
    """A running sandbox: the outer bwrap process and a pidfd on the namespace's
    init, opened as soon as bwrap reports it, so a reused pid is never signalled."""

    process: subprocess.Popen
    child_pid: int
    pidfd: int

    def _signal(self, sig: int) -> None:
        if self.pidfd < 0:  # closed: its number may now belong to another object
            return
        try:
            signal.pidfd_send_signal(self.pidfd, sig)
        except ProcessLookupError:
            pass

    def terminate(self, grace: float = 10.0) -> int:
        """SIGTERM, then SIGKILL after `grace`. bwrap's PID 1 need not forward
        SIGTERM, so SIGKILL is the path relied on: killing the namespace's init
        kills every process in it (spec §8)."""
        self._signal(signal.SIGTERM)
        try:
            return self.process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self._signal(signal.SIGKILL)
            return self.process.wait()

    def wait(self, timeout: float | None = None) -> int:
        return self.process.wait(timeout=timeout)

    def close(self) -> None:
        """Kill if still running, reap, and release the pidfd; safe to call twice."""
        if self.pidfd < 0:
            return
        if self.process.poll() is None:
            self._signal(signal.SIGKILL)
            self.process.wait()
        os.close(self.pidfd)
        self.pidfd = -1


LAUNCH_TIMEOUT = 30.0
"""Seconds bwrap may take to report its child before the launch is abandoned."""


def _read_info(fd: int, process: subprocess.Popen) -> dict[str, object] | None:
    """Read bwrap's --info-fd JSON object; None when bwrap exits without one or does
    not report within LAUNCH_TIMEOUT (a stuck bind source must not hang the caller)."""
    decoder = json.JSONDecoder()
    buffer = ""
    deadline = time.monotonic() + LAUNCH_TIMEOUT
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            return None
        chunk = os.read(fd, 4096)
        if not chunk:
            return None
        buffer += chunk.decode("utf-8", errors="replace")
        try:
            value, _ = decoder.raw_decode(buffer.lstrip())
        except ValueError:
            continue
        return value if isinstance(value, dict) else None


RELEASE = b"run\n"
"""The one line that lets the gate exec the actor."""

_GATE = r"""
import os, signal, sys
gate = int(sys.argv[1])
line = b""
while len(line) < 4 and not line.endswith(b"\n"):
    chunk = os.read(gate, 1)
    if not chunk:
        break
    line += chunk
os.close(gate)
if line != b"run\n":
    os._exit(125)
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
try:
    os.execvp(sys.argv[2], sys.argv[2:])
except OSError as caught:
    os.write(2, f"va-gate: {sys.argv[2]}: {caught.strerror}\n".encode("utf-8", "replace"))
    os._exit(127)
"""
"""The program bwrap runs in front of the actor, under `/usr/bin/python3 -I` (spec §7).
It reads one line from its own pipe, named by number in its argv, closes that pipe,
and execs the actor only on `run`. EOF exits 125 without running the actor. It never
touches stdin, so the release cannot come from the caller and the caller's bytes reach
the actor intact. Not a shell: the pipe's number is often above 9, which dash rejects
(`Bad fd number`). CPython ignores SIGPIPE and SIGXFSZ at startup, and an ignored
disposition survives exec, so the gate restores both before it execs."""


def _pipe_above_stdio() -> tuple[int, int]:
    """`os.pipe()` with both ends above fd 2. The lowest free descriptors go first, so
    in a caller whose fd 0, 1 or 2 is closed an end would land there, and Popen's
    dup2 of the actor's explicit stdio would overwrite it (or the gate would read the
    caller's stdin)."""
    ends = os.pipe()
    moved: list[int] = []
    try:
        for fd in ends:
            moved.append(fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 3) if fd < 3 else fd)
    except BaseException:
        for fd in (*ends, *moved):
            try:
                os.close(fd)
            except OSError:
                pass
        raise
    for fd, new in zip(ends, moved):
        if new != fd:
            os.close(fd)
    return moved[0], moved[1]


def _require_open(**streams: int) -> None:
    for name, fd in streams.items():
        try:
            os.fstat(fd)
        except OSError as caught:
            raise ValueError(f"the actor's {name}, fd {fd}, is not open: {caught.strerror}") from caught


def _abort(process: subprocess.Popen, pidfd: int) -> None:
    """Undo a launch whose gate was never released: kill the namespace through the
    pidfd when one is held (never by pid), kill and reap bwrap, close the pidfd. The
    gate's write end closes after this, and EOF makes the gate exit 125 without running
    the actor even if something survived."""
    if pidfd >= 0:
        try:
            signal.pidfd_send_signal(pidfd, signal.SIGKILL)
        except ProcessLookupError:
            pass
        os.close(pidfd)
    if process.poll() is None:
        process.kill()
    process.wait()


def launch(spec: SandboxSpec, argv: Iterable[str], *, stdin: int, stdout: int, stderr: int) -> Sandboxed:
    """Start the actor so that its handle exists before it can run.

    bwrap runs the gate (`_GATE`) holding the read end of a dedicated pipe. bwrap
    reports the namespace's init on --info-fd, the pidfd is opened while the gate still
    waits, and only then is `RELEASE` written. Every failure before that aborts through
    the pidfd or by killing bwrap, and the gate, seeing EOF, never runs the actor.

    The actor's fds 0, 1 and 2 are `stdin`, `stdout` and `stderr`, and it holds no
    other descriptor (decision 12). A closed one is refused, so a library caller never
    passes a stray descriptor. bwrap starts in a process group of its own, so a signal
    to the caller's group cannot kill the actor before the seal (§3 step 9)."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError(
            "launch the sandbox from the main thread: --die-with-parent is PR_SET_PDEATHSIG, "
            "which fires when the spawning thread exits"
        )
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise SandboxUnproven(
            "pidfd-unavailable",
            "python",
            "this interpreter lacks os.pidfd_open or signal.pidfd_send_signal; the actor cannot be "
            "held by a handle that survives pid reuse",
        )
    _require_open(stdin=stdin, stdout=stdout, stderr=stderr)
    info_read, info_write = _pipe_above_stdio()
    gate_read, gate_write = _pipe_above_stdio()
    gated = ["/usr/bin/python3", "-I", "-c", _GATE, str(gate_read), *argv]
    try:
        process = subprocess.Popen(
            build_argv(spec, gated, info_fd=info_write),
            pass_fds=(info_write, gate_read),
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            process_group=0,
        )
    except BaseException:
        os.close(info_read)
        os.close(gate_write)
        raise
    finally:
        os.close(info_write)
        os.close(gate_read)
    pidfd = -1
    try:
        try:
            info = _read_info(info_read, process)
        finally:
            os.close(info_read)
        child = None if info is None else info.get("child-pid")
        if type(child) is not int:
            raise SandboxUnproven("launch-failed", "bwrap", "bwrap reported no child in time")
        try:
            pidfd = os.pidfd_open(child)
        except OSError as caught:
            raise SandboxUnproven("launch-failed", "bwrap", f"no handle on child {child}: {caught.strerror}") from caught
        os.write(gate_write, RELEASE)
    except BaseException as caught:
        _abort(process, pidfd)
        if isinstance(caught, SandboxUnproven) or not isinstance(caught, Exception):
            raise
        raise SandboxUnproven("launch-failed", "bwrap", f"{type(caught).__name__}: {caught}") from caught
    finally:
        os.close(gate_write)
    return Sandboxed(process, child, pidfd)
