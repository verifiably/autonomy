"""The bwrap driver (docs/envelope.md): argv, preflight, the denial probe,
and launch and kill."""

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
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from autonomy.sandbox.spec import IN_SANDBOX_OUTPUTS, IN_SANDBOX_SOCKET, IN_SANDBOX_TOKEN, SYSTEM_RO, SandboxSpec, Storage
from autonomy.sandbox.static import SandboxUnproven, check_binds, system_symlinks
from autonomy.sandbox.storage import pool_binds, pool_command

__all__ = [
    "BWRAP_ENV",
    "LAUNCH_TIMEOUT",
    "NET_TARGETS",
    "RELEASE",
    "Sandboxed",
    "build_argv",
    "launch",
    "preflight",
    "probe",
    "prove",
    "prove_development_host",
    "read_info",
]

BWRAP_ENV = MappingProxyType({"PATH": "/usr/bin", "LC_ALL": "C"})
"""The fixed environment passed to bwrap and any pre-exec stage: never the caller's."""

_PROBE = """\
import errno, os, socket, sys
for path in sys.argv[1:]:
    try:
        os.stat(path)
        print("REACHABLE", path)
    except OSError as caught:
        print(errno.errorcode.get(caught.errno, str(caught.errno)), path)
for family, host in ((socket.AF_INET, "192.0.2.1"), (socket.AF_INET6, "2001:db8::1")):
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.settimeout(5)
            probe.connect((host, 443))
        print("CONNECTED", "net:" + host)
    except OSError as caught:
        name = errno.errorcode.get(caught.errno) if caught.errno else type(caught).__name__
        print(name, "net:" + host)
"""

NET_TARGETS = ("net:192.0.2.1", "net:2001:db8::1")
"""Documentation addresses (RFC 5737, RFC 3849): nothing answers them anywhere."""
_UNREACHABLE = {"net:192.0.2.1": {"ENETUNREACH"}, "net:2001:db8::1": {"ENETUNREACH", "EAFNOSUPPORT"}}


def preflight(which: Callable[[str], str | None] = shutil.which) -> None:
    if which("bwrap") is None:
        raise SandboxUnproven("bwrap-missing", "bwrap", "bubblewrap is not on PATH")
    trial = [
        "bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr",
        *[arg for target, link in system_symlinks() for arg in ("--symlink", target, link)],
        "--", "/usr/bin/true",
    ]
    try:
        result = subprocess.run(
            trial, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL, env=BWRAP_ENV,
        )
    except FileNotFoundError as caught:
        raise SandboxUnproven("bwrap-missing", "bwrap", str(caught)) from caught
    except OSError as caught:
        raise SandboxUnproven("userns-unavailable", "bwrap", str(caught)) from caught
    except subprocess.TimeoutExpired:
        raise SandboxUnproven("userns-unavailable", "bwrap", "the trial sandbox did not exit in 30 s") from None
    if result.returncode != 0:
        raise SandboxUnproven("userns-unavailable", "bwrap", result.stderr.strip() or f"exit {result.returncode}")


_LOCK_USERNS = ("--unshare-user", "--disable-userns")
_USERNS_PROOF = """
import errno, os
try:
    os.unshare(os.CLONE_NEWUSER)
except OSError as error:
    if error.errno not in (errno.EPERM, errno.ENOSPC):
        raise
else:
    raise SystemExit("nested user namespaces are available")
"""


def prove_development_host() -> None:
    """Require rootless user namespaces and a bounded mount, and prove the sandbox cannot
    nest namespaces."""
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise SandboxUnproven("pidfd-unavailable", "python", "development supervision requires pidfds")
    argv = [*pool_command(Path("/tmp"), Storage(1 << 20, 16)), "bwrap", "--unshare-all", *_LOCK_USERNS,
            "--die-with-parent", "--clearenv", "--ro-bind", "/usr", "/usr"]
    for target, link in system_symlinks():
        argv.extend(("--symlink", target, link))
    argv.extend(("--", "/usr/bin/python3", "-I", "-c", _USERNS_PROOF))
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL, env=BWRAP_ENV,
        )
    except (OSError, subprocess.TimeoutExpired) as caught:
        raise SandboxUnproven("userns-unavailable", "bwrap", str(caught)) from caught
    if result.returncode != 0:
        raise SandboxUnproven("userns-unavailable", "bwrap", result.stderr.strip() or f"exit {result.returncode}")


def build_argv(
    spec: SandboxSpec, argv: Iterable[str], *, info_fd: int | None, gate_fd: int | None = None
) -> list[str]:
    for source in spec.bind_sources():
        try:
            real = source.resolve(strict=True)
        except FileNotFoundError as caught:
            raise SandboxUnproven("bind-missing", str(source), f"a bind source must exist: {caught}") from caught
        except (OSError, RuntimeError) as caught:
            raise SandboxUnproven("bind-unreadable", str(source), f"a bind source must resolve: {caught}") from caught
        if source != real:
            raise SandboxUnproven("bind-unreadable", str(source), f"a bind source must be its absolute real path: {real}")
    chdir = spec.chdir if spec.chdir is not None else spec.scratch
    args = []
    if spec.storage is not None:
        args += pool_command(spec.scratch, spec.storage, (chdir,) if chdir.is_relative_to(spec.scratch) else ())
    args += ["bwrap", "--unshare-all"]
    if spec.disable_nested_userns:
        args.extend(_LOCK_USERNS)
    args += ["--die-with-parent", "--new-session", "--clearenv", "--proc", "/proc", "--dev", "/dev"]
    # /tmp comes before anything that may lie beneath it, and scratch after the read-only binds.
    if spec.storage is None:
        args += ["--tmpfs", "/tmp"]
        writable = [(str(spec.scratch), str(spec.scratch))]
    else:
        tmp, *writable = pool_binds(spec.scratch)
        args += ["--bind", *tmp]
    for path in SYSTEM_RO:
        args += ["--ro-bind", str(path), str(path)]
    for target, link in system_symlinks():
        args += ["--symlink", target, link]
    for path in spec.ro_binds:
        args += ["--ro-bind", str(path), str(path)]
    for target, link in spec.symlinks:
        args += ["--symlink", str(target), str(link)]
    for source, destination in writable:
        args += ["--bind", source, destination]
    if spec.socket is not None or spec.token is not None or spec.outputs_link:
        args += ["--dir", "/run/va"]
    if spec.socket is not None:
        args += ["--bind", str(spec.socket), str(IN_SANDBOX_SOCKET)]
    if spec.token is not None:
        args += ["--ro-bind", str(spec.token), str(IN_SANDBOX_TOKEN)]
    if spec.outputs_link:
        args += ["--symlink", str(spec.scratch / "outputs"), str(IN_SANDBOX_OUTPUTS)]
    env = {"PATH": "/usr/bin", **spec.env}
    if gate_fd is None:
        for key, value in sorted(env.items()):
            args += ["--setenv", key, value]
    else:
        # Bubblewrap sets PWD and Python can coerce the locale. Give the gate
        # the actor's environment as separate arguments for an exact exec.
        environment_args = [part for pair in sorted(env.items()) for part in pair]
        argv = ["/usr/bin/python3", "-I", "-c", _GATE, str(gate_fd), str(len(env)), *environment_args, *argv]
    if spec.storage is not None:
        args += ["--remount-ro", "/dev", "--remount-ro", "/"]
    args += ["--chdir", str(chdir)]
    if info_fd is not None:
        args += ["--info-fd", str(info_fd)]
    return [*args, "--", *argv]


def probe(spec: SandboxSpec, denied: Iterable[Path], *, timeout: float = 60) -> None:
    """`ENOENT` on every denied path, and `ENETUNREACH` from a connect to a
    non-loopback IPv4 and IPv6 address. A kernel without IPv6 answers
    `EAFNOSUPPORT`, which is as unreachable."""
    paths = []
    for path in denied:
        try:
            paths.append(str(path.resolve()))
        except (OSError, RuntimeError) as caught:
            raise SandboxUnproven("denied-unreadable", str(path), f"cannot resolve denied path: {caught}") from caught
    if not paths:
        raise SandboxUnproven("probe-failed", "denied", "the probe needs at least one denied path")
    argv = build_argv(spec, ["/usr/bin/python3", "-I", "-c", _PROBE, *paths], info_fd=None)
    try:
        result = subprocess.run(
            argv, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, env=BWRAP_ENV,
        )
    except subprocess.TimeoutExpired:
        raise SandboxUnproven("probe-failed", "bwrap", f"the probe did not exit in {timeout:g} s") from None
    stdout = result.stdout.decode("utf-8", errors="replace")
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise SandboxUnproven("probe-failed", "bwrap", stderr or f"exit {result.returncode}")
    lines = stdout.splitlines()
    expected = [*paths, *NET_TARGETS]
    if len(lines) != len(expected):
        raise SandboxUnproven("probe-failed", "bwrap", f"expected {len(expected)} lines, got {len(lines)}")
    for path, line in zip(expected, lines, strict=True):
        status, _, reported = line.partition(" ")
        if reported != path:
            raise SandboxUnproven("probe-failed", path, f"the probe reported {reported!r} out of order")
        if path in _UNREACHABLE:
            if status not in _UNREACHABLE[path]:
                raise SandboxUnproven("probe-network", path, f"a connect inside the sandbox gave {status}, not ENETUNREACH")
        elif status != "ENOENT":
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
    worker_fd: int = -1

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
        kills every process in it."""
        self._signal(signal.SIGTERM)
        try:
            return self.process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self._signal(signal.SIGKILL)
            return self.process.wait()

    def wait(self, timeout: float | None = None) -> int:
        return self.process.wait(timeout=timeout)

    def close_handles(self) -> None:
        for fd in (self.worker_fd, self.pidfd):
            if fd >= 0:
                os.close(fd)
        self.worker_fd = self.pidfd = -1

    def close(self) -> None:
        """Kill if still running, reap, and release the pidfd; safe to call twice."""
        if self.pidfd < 0:
            return
        if self.process.poll() is None:
            self._signal(signal.SIGKILL)
            self.process.wait()
        self.close_handles()


LAUNCH_TIMEOUT = 30.0
"""Seconds bwrap may take to report its child before the launch is abandoned."""

_ABORT_TIMEOUT = 5.0


def read_info(fd: int, process: subprocess.Popen) -> dict[str, object] | None:
    """Read bwrap's --info-fd JSON object; None when bwrap exits without one or does
    not report within LAUNCH_TIMEOUT (a stuck bind source must not hang the caller)."""
    decoder = json.JSONDecoder()
    buffer = ""
    deadline = time.monotonic() + LAUNCH_TIMEOUT
    poll = select.poll()
    poll.register(fd, select.POLLIN)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not poll.poll(max(1, int(1000 * remaining))):
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
env_end = 3 + 2 * int(sys.argv[2])
env = dict(zip(sys.argv[3:env_end:2], sys.argv[4:env_end:2], strict=True))
argv = sys.argv[env_end:]
try:
    os.execvpe(argv[0], argv, env)
except OSError as caught:
    os.write(2, f"va-gate: {argv[0]}: {caught.strerror}\n".encode("utf-8", "replace"))
    os._exit(127)
"""
"""The program bwrap runs in front of the actor, under `/usr/bin/python3 -I`.
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
        for fd in set(ends).union(moved):
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
    pidfd when one is held, then kill and reap bwrap within the cleanup timeout."""
    try:
        if pidfd >= 0:
            try:
                signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finally:
                os.close(pidfd)
    except OSError as caught:
        raise SandboxUnproven("launch-failed", "bwrap", f"namespace cleanup failed: {caught}") from caught
    finally:
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=_ABORT_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as caught:
            raise SandboxUnproven("launch-failed", "bwrap", f"process cleanup failed: {caught}") from caught


def _check_network_namespace(child_pid: int, pidfd: int) -> None:
    child_path = f"/proc/{child_pid}/ns/net"
    try:
        host = os.stat("/proc/self/ns/net")
        child = os.stat(child_path)
    except OSError as caught:
        raise SandboxUnproven("probe-network", child_path, f"cannot read network namespace identity: {caught}") from caught

    # A pidfd becomes readable on exit, even before the task is reaped.
    poll = select.poll()
    poll.register(pidfd, select.POLLIN)
    if poll.poll(0):
        raise SandboxUnproven("probe-network", child_path, "sandbox init exited during the network namespace check")
    if (host.st_dev, host.st_ino) == (child.st_dev, child.st_ino):
        raise SandboxUnproven("probe-network", child_path, "sandbox shares the orchestrator's network namespace")


_PRE_EXEC = r"""
import os, resource, sys
fsize, cgroup = sys.argv[1], sys.argv[2]
if cgroup:
    fd = os.open(os.path.join(cgroup, "cgroup.procs"), os.O_WRONLY | os.O_CLOEXEC)
    try:
        os.write(fd, b"0\n")
    finally:
        os.close(fd)
if fsize:
    limit = int(fsize)
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
os.execvp(sys.argv[3], sys.argv[3:])
"""


def _pin_worker(init: int, init_fd: int) -> int:
    """Find namespace PID 2 while the exec gate still owns the process."""
    directory = Path("/proc") / str(init)
    poll = select.poll()
    poll.register(init_fd, select.POLLIN)
    until = time.monotonic() + LAUNCH_TIMEOUT
    while time.monotonic() < until and not poll.poll(0):
        children = (directory / "task" / str(init) / "children").read_text().split()
        if children:
            if len(children) != 1:
                break
            pid = int(children[0])
            fd = os.pidfd_open(pid)
            try:
                target = Path("/proc") / str(pid)
                status = dict(line.split(":", 1) for line in (target / "status").read_text().splitlines())
                if (int(status["PPid"]) == init and status["NSpid"].split()[-1] == "2"
                        and (target / "ns/pid").samefile(directory / "ns/pid") and not poll.poll(0)):
                    return fd
            except BaseException:
                os.close(fd)
                raise
            os.close(fd)
            break
        time.sleep(0.005)
    raise SandboxUnproven("launch-failed", "bwrap", "cannot bind the gated worker in the actor namespace")


def launch(
    spec: SandboxSpec,
    argv: Iterable[str],
    *,
    stdin: int,
    stdout: int,
    stderr: int,
    before_release: Callable[[int, int], None] | None = None,
    release_guard: Callable[[int, int], AbstractContextManager[None]] | None = None,
    actor_fsize_bytes: int | None = None,
    actor_cgroup: Path | None = None,
    track_worker: bool = False,
) -> Sandboxed:
    """Start the actor so that its handle exists before it can run.

    bwrap runs the gate (`_GATE`) holding the read end of a dedicated pipe. bwrap
    reports the namespace's init on --info-fd, the pidfd is opened while the gate still
    waits, and its network namespace is checked before the actor can start. Every
    failure before release aborts through the pidfd or by killing bwrap, and the gate,
    seeing EOF, never runs the actor.

    The actor's fds 0, 1 and 2 are `stdin`, `stdout` and `stderr`, and it holds no
    other descriptor. A closed one is refused, so a library caller never
    passes a stray descriptor. `before_release(child_pid, pidfd)` runs after
    the namespace check and before the release. Whatever it raises aborts the launch and
    propagates unchanged: the model proxy's listener must exist before
    the actor can run. bwrap starts in a process group of its own, so a signal
    to the caller's group cannot kill the actor before the seal. An optional
    guard encloses the gate write. The optional file limit is inherited via an
    in-place exec of bwrap, which preserves its parent-death semantics."""
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
    if actor_cgroup is not None and not actor_cgroup.is_absolute():
        raise ValueError("actor_cgroup must be an absolute path")
    actor_argv = tuple(argv)
    if not actor_argv or not actor_argv[0]:
        raise SandboxUnproven("launch-failed", "actor", "the actor must have a nonempty executable argument")
    info_read, info_write = _pipe_above_stdio()
    try:
        gate_read, gate_write = _pipe_above_stdio()
    except BaseException:
        os.close(info_read)
        os.close(info_write)
        raise
    try:
        command = build_argv(spec, actor_argv, info_fd=info_write, gate_fd=gate_read)
        if actor_fsize_bytes is not None or actor_cgroup is not None:
            command = [
                "/usr/bin/python3",
                "-I",
                "-c",
                _PRE_EXEC,
                "" if actor_fsize_bytes is None else str(actor_fsize_bytes),
                "" if actor_cgroup is None else str(actor_cgroup),
                *command,
            ]
        process = subprocess.Popen(
            command,
            pass_fds=(info_write, gate_read),
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            process_group=0,
            env=BWRAP_ENV,
        )
    except BaseException:
        os.close(info_read)
        os.close(gate_write)
        raise
    finally:
        os.close(info_write)
        os.close(gate_read)
    pidfd = -1
    worker_fd = -1
    hook_error: BaseException | None = None
    try:
        try:
            info = read_info(info_read, process)
        finally:
            os.close(info_read)
        child = None if info is None else info.get("child-pid")
        if type(child) is not int:
            raise SandboxUnproven("launch-failed", "bwrap", "bwrap reported no child in time")
        try:
            pidfd = os.pidfd_open(child)
        except OSError as caught:
            raise SandboxUnproven("launch-failed", "bwrap", f"no handle on child {child}: {caught.strerror}") from caught
        if process.poll() is not None:
            os.close(pidfd)
            pidfd = -1
            raise SandboxUnproven("launch-failed", "bwrap", "bwrap exited while acquiring the child handle")
        _check_network_namespace(child, pidfd)
        if track_worker:
            worker_fd = _pin_worker(child, pidfd)
        if before_release is not None:
            try:
                before_release(child, pidfd)
            except BaseException as caught:
                hook_error = caught
                raise
        try:
            with release_guard(child, pidfd) if release_guard is not None else nullcontext():
                try:
                    os.write(gate_write, RELEASE)
                except BrokenPipeError as caught:
                    raise SandboxUnproven("launch-failed", "bwrap", "the actor gate closed before release") from caught
        except BaseException as caught:
            if release_guard is not None:
                hook_error = caught
            raise
    except BaseException as caught:
        if worker_fd >= 0:
            os.close(worker_fd)
        os.close(gate_write)
        try:
            _abort(process, pidfd)
        except SandboxUnproven as cleanup:
            if caught is hook_error or not isinstance(caught, Exception):
                raise caught from cleanup
            raise
        if caught is hook_error or isinstance(caught, SandboxUnproven) or not isinstance(caught, Exception):
            raise
        raise SandboxUnproven("launch-failed", "bwrap", f"{type(caught).__name__}: {caught}") from caught
    else:
        os.close(gate_write)
    return Sandboxed(process, child, pidfd, worker_fd)
