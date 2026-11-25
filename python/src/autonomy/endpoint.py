"""Launch and control one qualified science writer over its private socket."""

from __future__ import annotations

from array import array
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import secrets
import select
import signal
import socket
import struct
import subprocess
import threading
import time

from autonomy.allowance._contract import digest
from autonomy.baseline import append_event, decode_object, publish_json
from autonomy.ledger import LedgerUnusable, load_ledger
from autonomy.process import ProcessSurvived, exited, send_signal, spawn_recorded
from autonomy.run import RunDirs
from autonomy.science_reads import ChainHead, has_handle
from autonomy.tiers import Permit

__all__ = ["Control", "Endpoint", "EndpointError", "Launch", "SessionOpen", "check_seal"]

_VERSION = "control.v1"
_LIMIT = 16384
_SOCKET_MAX = 107
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SID = re.compile(r"[0-9a-f]{32}")
_TERMINAL = {"sealed", "seal-timeout", "seal-failed"}
_ACK_TIMEOUT = 5.0
_EXIT_GRACE = 5.0


class EndpointError(Exception):
    def __init__(self, message: str, *, code: str = "endpoint-unavailable") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResearchLaunch:
    allowance_fd: int
    research_action: dict
    resume_handoff: dict


@dataclass(frozen=True)
class Launch:
    dirs: RunDirs
    executable: Path
    config: Path
    operations: Path
    permit: Permit
    written: tuple[ChainHead, ...]
    lease: float
    seal_timeout: float
    research: ResearchLaunch | None = None


@dataclass(frozen=True)
class SessionOpen:
    session_id: str
    ledger_path: Path
    basis_open: str


def _digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def check_seal(row: dict[str, object], written: tuple[ChainHead, ...]) -> dict[str, object]:
    if set(row) != {"cause", "sealed_tips", "basis_seal"}:
        raise EndpointError("wrong seal fields", code="seal-failed")
    if row["cause"] not in ("stop", "lease", "eof", "term") or (
            row["basis_seal"] is not None and not _digest(row["basis_seal"])):
        raise EndpointError("invalid seal cause or basis", code="seal-failed")
    tips = row["sealed_tips"]
    if not isinstance(tips, list) or len(tips) != len(written):
        raise EndpointError("seal does not cover every written chain", code="seal-failed")
    expected = {(chain.role, chain.chain_id, chain.genesis) for chain in written}
    for tip in tips:
        if (not isinstance(tip, dict) or set(tip) != {"role", "id", "genesis", "tip"}
                or not all(isinstance(tip[key], str) for key in ("role", "id", "genesis"))
                or not _digest(tip["tip"])):
            raise EndpointError("invalid sealed tip", code="seal-failed")
        key = (tip["role"], tip["id"], tip["genesis"])
        if key not in expected:
            raise EndpointError("seal substituted or repeated a chain", code="seal-failed")
        expected.remove(key)
    return row


def _wait(fd: int, events: int, deadline: float, now: Callable[[], float]) -> None:
    remaining = deadline - now()
    if remaining <= 0:
        raise TimeoutError("endpoint control deadline expired")
    poll = select.poll()
    poll.register(fd, events)
    if not poll.poll(math.ceil(remaining * 1000)):
        raise TimeoutError("endpoint control deadline expired")


class Control:
    """Bounded frames with one ordinary exchange in flight. Seal can send independently."""

    def __init__(self, stream: socket.socket, *, lease: float, now: Callable[[], float] = time.monotonic) -> None:
        self.stream = stream
        self.stream.setblocking(False)
        self._lease = lease
        self._now = now
        self.expires = now() + lease
        self._buffer = bytearray()
        self._sender = threading.Lock()
        self._exchange = threading.Lock()
        self._sealing = threading.Event()
        self._terminal: dict[str, object] | None = None
        self._pending: str | None = None

    def _read(self, deadline: float) -> dict[str, object]:
        while True:
            if self._now() >= deadline:
                raise TimeoutError("endpoint control deadline expired")
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                raw = bytes(self._buffer[:newline])
                del self._buffer[:newline + 1]
                try:
                    row = decode_object(raw)
                except (ValueError, RecursionError) as error:
                    raise EndpointError("invalid endpoint control JSON") from error
                if row.get("version") != _VERSION or not isinstance(row.get("type"), str):
                    raise EndpointError("invalid endpoint control version or type")
                return row
            if len(self._buffer) >= _LIMIT:
                raise EndpointError("oversized endpoint control frame")
            try:
                data = self.stream.recv(_LIMIT - len(self._buffer))
            except BlockingIOError:
                _wait(self.stream.fileno(), select.POLLIN, deadline, self._now)
                continue
            if not data:
                raise EOFError("endpoint control closed")
            self._buffer.extend(data)

    def _send(self, kind: str, deadline: float, fd: int | None = None) -> None:
        message = json.dumps({"version": _VERSION, "type": kind}, separators=(",", ":")).encode() + b"\n"
        ancillary = [] if fd is None else [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array("i", [fd]))]
        with self._sender:
            if kind != "seal" and self._sealing.is_set():
                raise EndpointError("endpoint is sealing")
            while message:
                if self._now() >= deadline:
                    raise TimeoutError("endpoint control send timed out")
                try:
                    count = self.stream.sendmsg([message], ancillary)
                except BlockingIOError:
                    _wait(self.stream.fileno(), select.POLLOUT, deadline, self._now)
                    continue
                if not count:
                    raise EOFError("endpoint control closed")
                message = message[count:]
                ancillary = []

    def _request(self, kind: str, expected: str, fd: int | None = None) -> None:
        with self._exchange:
            now = self._now()
            if now >= self.expires:
                raise EndpointError("endpoint lease expired")
            if self._pending is not None:
                raise EndpointError("endpoint has an unacknowledged request")
            deadline = min(self.expires, now + _ACK_TIMEOUT)
            try:
                self._send(kind, deadline, fd)
                self._pending = expected
                row = self._read(deadline)
            except (OSError, EOFError) as error:
                raise EndpointError(str(error)) from error
            self._pending = None
            response = row["type"]
            if response in _TERMINAL:
                self._terminal = row
                self._sealing.set()
                raise EndpointError("endpoint sealed during control exchange")
            if response == "refused" and set(row) == {"type", "version", "code"} and row["code"] == "run-sealed":
                self._sealing.set()
                raise EndpointError("endpoint refused control: run-sealed")
            if response != expected or set(row) != {"version", "type"}:
                raise EndpointError(f"expected {expected} from endpoint, got {response}")
            if kind == "renew":
                self.expires = now + self._lease

    def renew(self) -> None:
        self._request("renew", "renewed")

    def bind(self, namespace_fd: int) -> None:
        self._request("bind-actor", "bound", namespace_fd)

    def seal(self, deadline: float) -> dict[str, object]:
        self._sealing.set()
        if self._terminal is None:
            try:
                self._send("seal", min(deadline, self._now() + _ACK_TIMEOUT))
            except (EOFError, BrokenPipeError, ConnectionResetError):
                # The endpoint may have sent its result and closed its read side.
                pass
        if not self._exchange.acquire(timeout=max(0, deadline - self._now())):
            raise TimeoutError("endpoint exchange did not release before close")
        try:
            while self._terminal is None:
                row = self._read(deadline)
                kind = row["type"]
                if kind in _TERMINAL:
                    self._terminal = row
                elif self._pending is not None and (
                        (kind == self._pending and set(row) == {"type", "version"})
                        or (kind == "refused" and set(row) == {"type", "version", "code"} and row["code"] == "run-sealed")
                ):
                    self._pending = None
                else:
                    raise EndpointError("unexpected endpoint reply during seal", code="seal-failed")
            return self._terminal
        finally:
            self._exchange.release()


def _listener(path: Path) -> socket.socket:
    stream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
    try:
        stream.bind(path.as_posix())
        stream.listen(1)
        stream.setblocking(False)
    except BaseException:
        stream.close()
        raise
    return stream


def _receive_peer(listener: socket.socket, pidfd: int, pid: int, deadline: float) -> socket.socket:
    poll = select.poll()
    poll.register(listener, select.POLLIN)
    poll.register(pidfd, select.POLLIN)
    while (remaining := deadline - time.monotonic()) > 0:
        ready = dict(poll.poll(math.ceil(remaining * 1000)))
        if pidfd in ready:
            raise EndpointError("science endpoint exited during startup")
        if listener.fileno() in ready:
            stream, _ = listener.accept()
            try:
                credentials = stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                peer, uid, _ = struct.unpack("3i", credentials)
                if peer != pid or uid != os.geteuid() or exited(pidfd):
                    raise EndpointError("control socket peer is not the launched endpoint")
                return stream
            except BaseException:
                stream.close()
                raise
    raise EndpointError("science endpoint did not connect in time")


def _spawn(launch: Launch, env: Mapping[str, str], source: Path) -> tuple[subprocess.Popen, int]:
    fd = os.open(launch.dirs.run_dir / "endpoint.log",
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as log:
        return spawn_recorded(
            [str(launch.executable), "serve", "--run", str(source)],
            env={key: value for key, value in env.items() if key != "SCIENCE_CONFIG"},
            record=lambda identity: append_event(launch.dirs.run_dir, "endpoint-starting", **identity.fields()),
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            pass_fds=(launch.research.allowance_fd,) if launch.research else (),
        )


def _opening(control: Control, launch: Launch, deadline: float) -> SessionOpen:
    row = control._read(deadline)
    sid, basis = row.get("session_id"), row.get("basis_open")
    fields = {"type", "version", "session_id", "ledger_path", "basis_open"}
    if launch.research is not None:
        fields.add("research_action_digest")
        if row.get("research_action_digest") != digest(launch.research.research_action):
            raise EndpointError("endpoint did not acknowledge the bound research action", code="allowance-scope")
    if (row["type"] != "open" or set(row) != fields
            or not isinstance(sid, str) or not _SID.fullmatch(sid) or not _digest(basis)):
        raise EndpointError("invalid endpoint open report")
    ledger_path = launch.operations / "sessions" / sid / "ledger.v1"
    if row["ledger_path"] != str(ledger_path) or ledger_path.resolve() != ledger_path:
        raise EndpointError("ledger path does not match the original operations root")
    append_event(launch.dirs.run_dir, "session-open", session_id=sid, ledger_path=str(ledger_path), basis_open=basis)
    ledger = load_ledger(ledger_path, sid)
    if isinstance(ledger, LedgerUnusable) or ledger.torn_tail or ledger.closed:
        raise EndpointError("session-open ledger is unavailable or already closed")
    if ledger.actor != f"session:{sid}":
        raise EndpointError("session actor differs from the endpoint ID", code="actor-mismatch")
    if ledger.permit != launch.permit:
        raise EndpointError("session permit differs from the tier", code="permit-mismatch")
    assert isinstance(basis, str)
    return SessionOpen(sid, ledger_path, basis)


def _reap(process: subprocess.Popen, pidfd: int, grace: float) -> None:
    try:
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            send_signal(pidfd, signal.SIGKILL)
            process.wait(timeout=_EXIT_GRACE)
    except subprocess.TimeoutExpired as error:
        raise ProcessSurvived("science endpoint has not confirmed exit") from error
    finally:
        os.close(pidfd)


@dataclass
class Endpoint:
    process: subprocess.Popen
    pidfd: int
    actor_socket: Path
    token: Path
    control: Control
    opened: SessionOpen
    seal_timeout: float

    @classmethod
    def start(cls, launch: Launch, env: Mapping[str, str], *, timeout: float) -> Endpoint:
        if has_handle(env):
            raise EndpointError("endpoint startup requires an operator invocation")
        deadline = time.monotonic() + timeout
        runtime = launch.dirs.socket_dir.resolve()
        socket_path, token = runtime / "endpoint.sock", runtime / "token"
        control_path = runtime.with_suffix(".ctl")
        if any(len(os.fsencode(path)) > _SOCKET_MAX for path in (socket_path, control_path)):
            raise EndpointError("endpoint Unix socket path exceeds the host limit")
        listener: socket.socket | None = None
        try:
            listener = _listener(control_path)
            fd = os.open(token, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
            with os.fdopen(fd, "wb") as file:
                file.write(secrets.token_hex(32).encode("ascii"))
            source = launch.dirs.run_dir / "launch.json"
            publish_json(source, {
                "version": "launch.v1", "config": str(launch.config), "run_dir": str(launch.dirs.run_dir.resolve()),
                "scratch_dir": str(launch.dirs.scratch), "socket": str(socket_path), "control_socket": str(control_path),
                "token_file": str(token), "permit": launch.permit.to_json(),
                "written_chains": [{"id": c.chain_id, "role": c.role, "root": str(c.root)} for c in launch.written],
                "lease_seconds": launch.lease, "seal_timeout_seconds": launch.seal_timeout,
                **({"allowance_fd": launch.research.allowance_fd, "research_action": launch.research.research_action,
                    "resume_handoff": launch.research.resume_handoff} if launch.research else {}),
            })
            process, pidfd = _spawn(launch, env, source)
            peer: socket.socket | None = None
            try:
                peer = _receive_peer(listener, pidfd, process.pid, deadline)
                control = Control(peer, lease=launch.lease)
                opened = _opening(control, launch, deadline)
                return cls(process, pidfd, socket_path, token, control, opened, launch.seal_timeout)
            except BaseException:
                if peer is not None:
                    peer.close()
                else:
                    send_signal(pidfd, signal.SIGTERM)
                _reap(process, pidfd, launch.seal_timeout + _EXIT_GRACE)
                raise
        except (OSError, EOFError, ValueError) as error:
            raise EndpointError(f"science endpoint could not open: {error}") from error
        finally:
            if listener is not None:
                listener.close()
                control_path.unlink(missing_ok=True)

    def bind(self, child_pid: int, pidfd: int) -> None:
        if exited(pidfd):
            raise EndpointError("actor namespace init exited before binding")
        fd = os.open(f"/proc/{child_pid}/ns/pid", os.O_RDONLY | os.O_CLOEXEC)
        try:
            if exited(pidfd) or os.path.samestat(os.fstat(fd), os.stat("/proc/self/ns/pid")):
                raise EndpointError("actor needs a live, distinct PID namespace")
            self.control.bind(fd)
            if exited(pidfd):
                raise EndpointError("actor namespace init exited during binding")
        finally:
            os.close(fd)

    def close(self, *, grace: float | None = None) -> None:
        if self.pidfd < 0:
            return
        self.control.stream.close()
        try:
            _reap(self.process, self.pidfd, self.seal_timeout + _EXIT_GRACE if grace is None else grace)
        finally:
            self.pidfd = -1
