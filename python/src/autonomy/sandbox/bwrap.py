"""The bwrap driver (envelope design §7, §8): argv, preflight, the denial probe,
and (Task 7) launch and kill."""

from __future__ import annotations

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
        result = subprocess.run(trial, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise SandboxUnproven("userns-unavailable", "bwrap", "the trial sandbox did not exit in 30 s") from None
    if result.returncode != 0:
        raise SandboxUnproven("userns-unavailable", "bwrap", result.stderr.strip() or f"exit {result.returncode}")


def build_argv(
    spec: SandboxSpec, argv: Iterable[str], *, info_fd: int | None, block_fd: int | None = None
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
    if block_fd is not None:
        # bwrap reports the child on --info-fd, then holds the command until this fd
        # has data: the window in which launch() takes its pidfd (Task 7)
        args += ["--block-fd", str(block_fd)]
    return [*args, "--", *argv]


def probe(spec: SandboxSpec, denied: Iterable[Path]) -> None:
    paths = [str(p.resolve()) for p in denied]
    argv = build_argv(spec, ["/usr/bin/python3", "-I", "-c", _PROBE, *paths], info_fd=None)
    try:
        result = subprocess.run(argv, capture_output=True, timeout=60)
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


def _abort(process: subprocess.Popen, message: str, child: int | None = None) -> SandboxUnproven:
    """Reap a launch that failed before its command was released.

    Called while block_write is still open: a reported child is then still blocked,
    so it is alive and its pid cannot have been reused, and it is killed by pid before
    anything closes the fd that would release it."""
    if child is not None:
        try:
            os.kill(child, signal.SIGKILL)  # the namespace's init: every process in it
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()  # the outer bwrap; --die-with-parent takes the held child with it
    process.wait()
    return SandboxUnproven("launch-failed", "bwrap", f"{message} (exit {process.returncode})")


def launch(spec: SandboxSpec, argv: Iterable[str]) -> Sandboxed:
    """Start the actor so that its handle exists before it can run.

    bwrap writes the child's pid on --info-fd and then holds the command until
    --block-fd has data. The pidfd is opened inside that window, so a command that
    exits at once (or a reused pid) can never be missed; only then is the command
    released. A failure before release kills and reaps the outer bwrap."""
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
    info_read, info_write = os.pipe()
    block_read, block_write = os.pipe()
    child: object = None
    try:
        process = subprocess.Popen(
            build_argv(spec, argv, info_fd=info_write, block_fd=block_read),
            pass_fds=(info_write, block_read),
            stdin=subprocess.DEVNULL,
        )
    except BaseException:
        for fd in (info_read, block_write):
            os.close(fd)
        raise
    finally:
        os.close(info_write)
        os.close(block_read)
    try:
        try:
            info = _read_info(info_read, process)
        finally:
            os.close(info_read)
        child = None if info is None else info.get("child-pid")
        if type(child) is not int:
            raise _abort(process, "bwrap reported no child in time")
        try:
            pidfd = os.pidfd_open(child)
        except ProcessLookupError:
            raise _abort(process, f"the held child {child} vanished before its handle was taken") from None
        except OSError as caught:
            raise _abort(process, f"no handle on the held child {child}: {caught.strerror}", child) from caught
        os.write(block_write, b"\x01")  # release the command
    except SandboxUnproven:
        raise
    except BaseException:
        # anything unanticipated: never let closing block_write release an actor
        # nobody holds a handle on
        _abort(process, "launch interrupted", child if type(child) is int else None)
        raise
    finally:
        os.close(block_write)
    return Sandboxed(process, child, pidfd)
