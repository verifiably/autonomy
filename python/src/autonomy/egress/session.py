"""The orchestrator's side of the model proxy (envelope design decision 13): the
proxy's own sandbox, its start, the listener's hand-off before the gate's release,
renewal, and the close. B2 calls `check_proxy` at §3 step 7, `start` at step 9 (which
checks again) and passes `attach` to `launch` there, sends `close` with the seal at
close step 0, and calls `kill_orphan` from `run close`."""

from __future__ import annotations

import base64
import json
import os
import select
import signal
import socket
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import autonomy
from autonomy.baseline import EVENTS, append_event
from autonomy.egress.errors import EgressUnproven
from autonomy.egress.helper import make_listener
from autonomy.egress.proxy import BOOT, IN_SANDBOX_CA, IN_SANDBOX_CREDENTIAL, receive_message, send_message
from autonomy.egress.route import LoadedRoute, Route
from autonomy.membership import Finding
from autonomy.sandbox.bwrap import read_info
from autonomy.sandbox.spec import SYSTEM_SYMLINKS
from autonomy.sandbox.static import SandboxUnproven, check_sources

PROXY_START_TIMEOUT = 10.0
LISTENING_TIMEOUT = 5.0
CLOSE_TIMEOUT = 5.0
EGRESS_RECORDS = "egress.jsonl"
PROXY_LOG = "proxy.log"


@dataclass(frozen=True)
class ProxyBinds:
    ro: tuple[tuple[Path, str], ...]
    exempt: tuple[Path, ...]


def _package() -> Path:
    return Path(autonomy.__file__).resolve().parent


def proxy_binds(route: Route, *, resolv: Path = Path("/etc/resolv.conf")) -> ProxyBinds:
    """`/usr`, `/etc`, the package, the credential and the `ca_file`, and the resolver
    configuration's real path when it lies outside `/etc` (systemd-resolved's stub)."""
    package = _package()
    ro: list[tuple[Path, str]] = [(Path("/usr"), "/usr"), (Path("/etc"), "/etc"), (package, str(package))]
    real = resolv.resolve()
    if real.exists() and not real.is_relative_to("/etc"):
        ro.append((real, str(real)))
    ro.append((route.credential_file, str(IN_SANDBOX_CREDENTIAL)))
    exempt = [route.credential_file]
    if route.ca_file is not None:
        ro.append((route.ca_file, str(IN_SANDBOX_CA)))
        exempt.append(route.ca_file)
    return ProxyBinds(tuple(ro), tuple(exempt))


def check_proxy(binds: ProxyBinds, denied: Iterable[Path]) -> None:
    """§3 step 7, the proxy's half: the denied set, with only its own files exempt."""
    try:
        check_sources([source for source, _ in binds.ro], denied, exempt=binds.exempt)
    except SandboxUnproven as caught:
        raise EgressUnproven("proxy-bind-refused", str(caught)) from None


def proxy_argv(binds: ProxyBinds, *, control_fd: int, records_fd: int, info_fd: int) -> list[str]:
    """No `--die-with-parent`, deliberately: a proxy that died with the orchestrator
    would write no closing line. It sees EOF on its control socket and closes."""
    args = ["bwrap", "--unshare-all", "--share-net", "--new-session", "--clearenv",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/run/va"]
    for source, destination in binds.ro:
        args += ["--ro-bind", str(source), destination]
    for target, link in SYSTEM_SYMLINKS:
        args += ["--symlink", target, link]
    args += ["--setenv", "PATH", "/usr/bin", "--info-fd", str(info_fd), "--",
             "/usr/bin/python3", "-I", "-c", BOOT, str(_package().parent), str(control_fd), str(records_fd)]
    return args


def _start_time(pid: int) -> int:
    stat = Path(f"/proc/{pid}/stat").read_bytes()
    return int(stat.rsplit(b")", 1)[1].split()[19])


def closing_line(path: Path) -> dict | None:
    """The proxy's closing line, when `egress.jsonl` ends with one."""
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return None
    if not lines:
        return None
    try:
        last = json.loads(lines[-1])
    except ValueError:
        return None
    return last if "closed" in last else None


@dataclass(frozen=True)
class EgressClosed:
    cause: str | None
    last_seq: int | None
    timed_out: bool

    def findings(self) -> tuple[Finding, ...]:
        if self.timed_out:
            return (Finding("egress-close-timeout", "proxy", "the proxy did not exit within 5 s and was killed"),)
        if self.cause is None:
            return (Finding("egress-lost", "proxy", "the proxy exited without its closing line"),)
        return ()


def unproven(error: EgressUnproven) -> Finding:
    return Finding("egress-unproven", error.code, error.message)


def _settle(run_dir: Path, timed_out: bool) -> EgressClosed:
    line = closing_line(run_dir / EGRESS_RECORDS)
    result = EgressClosed(None if line is None else line["closed"], None if line is None else line["last_seq"], timed_out)
    if timed_out:
        append_event(run_dir, "egress-close-timeout")
    elif line is None:
        append_event(run_dir, "egress-lost")
    else:
        append_event(run_dir, "egress-closed", cause=result.cause, last_seq=result.last_seq)
    return result


class EgressSession:
    def __init__(self, process: subprocess.Popen, init_pid: int, pidfd: int, control: socket.socket, run_dir: Path) -> None:
        self.process = process
        self.init_pid = init_pid
        self.pidfd = pidfd
        self.run_dir = run_dir
        self._control = control

    @classmethod
    def start(cls, loaded: LoadedRoute, run_dir: Path, *, lease: float, denied: Iterable[Path]) -> EgressSession:
        binds = proxy_binds(loaded.route)
        check_proxy(binds, denied)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC
        records = os.open(run_dir / EGRESS_RECORDS, flags, 0o600)
        log = os.open(run_dir / PROXY_LOG, flags, 0o600)
        ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        info_read, info_write = os.pipe()
        try:
            process = subprocess.Popen(
                proxy_argv(binds, control_fd=theirs.fileno(), records_fd=records, info_fd=info_write),
                pass_fds=(theirs.fileno(), records, info_write), stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, start_new_session=True,
            )
        except OSError as caught:
            ours.close()
            os.close(info_read)
            raise EgressUnproven("proxy-unstarted", f"cannot run bwrap: {caught}") from None
        finally:
            theirs.close()
            os.close(records)
            os.close(log)
            os.close(info_write)
        try:
            info = read_info(info_read, process)
        finally:
            os.close(info_read)
        child = None if info is None else info.get("child-pid")
        pidfd = -1
        if type(child) is int:
            try:
                pidfd = os.pidfd_open(child)
            except OSError:
                pidfd = -1
        if pidfd < 0:
            process.kill()
            process.wait()
            ours.close()
            raise EgressUnproven("proxy-unstarted", f"bwrap reported no proxy namespace (exit {process.returncode})")
        session = cls(process, child, pidfd, ours, run_dir)
        try:  # until the start succeeds, any failure kills and reaps the proxy and closes its descriptors
            append_event(run_dir, "egress-proxy", pid=child, start_time=_start_time(child))
            send_message(ours, {"op": "route", "route": base64.b64encode(loaded.data).decode("ascii"), "lease": lease,
                                "run": run_dir.name})
            reply = session._receive(PROXY_START_TIMEOUT)
            if reply is None or reply.get("op") != "ready":
                raise EgressUnproven("proxy-unready", _why(reply, PROXY_START_TIMEOUT))
            append_event(run_dir, "egress-ready")
        except BaseException:
            session.kill()
            raise
        return session

    def _receive(self, timeout: float) -> dict | None:
        if not select.select([self._control], [], [], timeout)[0]:
            return None
        message, fds = receive_message(self._control)
        for fd in fds:
            os.close(fd)
        return message

    def attach(self, child_pid: int, pidfd: int, *, make: Callable[[int, int], socket.socket] = make_listener) -> None:
        """`launch`'s `before_release` hook (§3 step 9). The orchestrator keeps no copy
        of the listener, so it lives only as long as the proxy does."""
        listener = make(child_pid, pidfd)
        try:
            send_message(self._control, {"op": "listener"}, [listener.fileno()])
        finally:
            listener.close()
        reply = self._receive(LISTENING_TIMEOUT)
        if reply is None or reply.get("op") != "listening":
            raise EgressUnproven("proxy-unlistening", _why(reply, LISTENING_TIMEOUT))
        append_event(self.run_dir, "egress-listening")

    def renew(self) -> None:
        send_message(self._control, {"op": "renew"})

    def exited(self) -> bool:
        return bool(select.select([self.pidfd], [], [], 0)[0])

    def close(self, timeout: float = CLOSE_TIMEOUT) -> EgressClosed:
        """Close step 0. B2 sends it together with the seal and waits on both."""
        if self.pidfd < 0:
            raise RuntimeError("this proxy session is already released")
        send_message(self._control, {"op": "close"})
        exited = bool(select.select([self.pidfd], [], [], timeout)[0])
        if not exited:
            self._kill_namespace()
        self._release()
        return _settle(self.run_dir, timed_out=not exited)

    def kill(self) -> None:
        """For a start or hand-off that failed: no closing line is expected."""
        self._kill_namespace()
        self._release()

    def _kill_namespace(self) -> None:
        _kill_and_confirm(self.pidfd, self.init_pid)

    def _release(self) -> None:
        try:
            self.process.wait(timeout=10)  # the outer bwrap exits with its namespace
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self._control.close()
        if self.pidfd >= 0:
            os.close(self.pidfd)
            self.pidfd = -1


class ProxySurvived(Exception):
    """A proxy namespace SIGKILLed has not exited within `CLOSE_TIMEOUT`. Cleanup
    failed: the run must not be settled as if the proxy were gone."""

    def __init__(self, pid: int) -> None:
        super().__init__(f"the proxy namespace {pid} did not exit within {CLOSE_TIMEOUT:g} s of SIGKILL")
        self.pid = pid


def _kill_and_confirm(pidfd: int, pid: int) -> bool:
    """SIGKILL a namespace's init and confirm its exit through the pidfd. True when
    this signal killed it, False when it had already exited. Raises `ProxySurvived`
    when it has not exited within `CLOSE_TIMEOUT`."""
    try:
        signal.pidfd_send_signal(pidfd, signal.SIGKILL)
        killed = True
    except ProcessLookupError:
        killed = False
    if not select.select([pidfd], [], [], CLOSE_TIMEOUT)[0]:
        raise ProxySurvived(pid)
    return killed


def _why(reply: dict | None, timeout: float) -> str:
    if reply is None:
        return f"no answer within {timeout:g} s"
    if reply.get("op") == "error":
        return f"{reply.get('code')}: {reply.get('message')}"
    return f"an unexpected answer: {reply}"


def kill_orphan(run_dir: Path, timeout: float = CLOSE_TIMEOUT) -> EgressClosed | None:
    """*Orphans* (spec §3): the proxy of a run whose orchestrator died has seen EOF and
    closed, or it is wedged. Wait up to `timeout` for its exit, then kill it. Returns
    None when the run started no proxy."""
    events_path = run_dir / EVENTS
    events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
    started = next((event for event in reversed(events) if event["event"] == "egress-proxy"), None)
    if started is None:
        return None
    timed_out = False
    try:
        pidfd = os.pidfd_open(started["pid"])
    except ProcessLookupError:
        pidfd = -1
    if pidfd >= 0:
        try:
            try:
                same = _start_time(started["pid"]) == started["start_time"]
            except FileNotFoundError:
                same = False
            if same and not select.select([pidfd], [], [], timeout)[0]:
                timed_out = _kill_and_confirm(pidfd, started["pid"])  # settles only once it has exited
        finally:
            os.close(pidfd)
    return _settle(run_dir, timed_out)
