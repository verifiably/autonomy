"""Hold the development gate, supervise the actor, and recover unfinished runs."""

from __future__ import annotations

import os
import re
import resource
import select
import signal
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from autonomy.baseline import append_event, fsync_dir, utc_now
from autonomy.development._records import (
    MODE,
    DevelopmentAborted,
    RunPaths,
    file_digest,
    publication_lock,
    publish_json,
    publish_terminal,
    read_journal,
    read_json,
    supervisor_lock,
    terminal_exit,
)
from autonomy.development._workspace import Limits, PreparedWorkspace
from autonomy.membership import Finding
from autonomy.run import RunRefused
from autonomy.sandbox.bwrap import Sandboxed, launch, prove_development_host
from autonomy.sandbox.static import SandboxUnproven

__all__ = ["ActorOutcome", "prove_development_host", "recover_run", "request_stop", "stop_requested", "supervise_actor"]

_TERM_GRACE = 10.0
_KILL_WAIT = 5.0
Cause = Literal["exit", "deadline", "stop"]


@dataclass(frozen=True)
class ActorOutcome:
    actor_exit: int | None
    cause: Cause | None
    containment_proven: bool
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class _Identity:
    child_pid: int
    start_time: int
    boot_id: str


def _boot_id() -> str:
    value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if str(uuid.UUID(value)) != value:
        raise ValueError("boot ID is not canonical")
    return value


def _start_time(pid: int) -> int:
    stat = Path(f"/proc/{pid}/stat").read_bytes()
    ticks = int(stat.rsplit(b")", 1)[1].split()[19])
    if ticks < 0:
        raise ValueError("invalid kernel start time")
    return ticks


def _exited(pidfd: int, timeout_ms: int = 0) -> bool:
    poll = select.poll()
    poll.register(pidfd, select.POLLIN)
    return any(flags & select.POLLIN for _, flags in poll.poll(timeout_ms))


def _send(pidfd: int, sig: int) -> None:
    try:
        signal.pidfd_send_signal(pidfd, sig)
    except ProcessLookupError:
        pass


def _terminate(pidfd: int) -> bool:
    if _exited(pidfd):
        return True
    _send(pidfd, signal.SIGTERM)
    if _exited(pidfd, int(_TERM_GRACE * 1000)):
        return True
    _send(pidfd, signal.SIGKILL)
    return _exited(pidfd, int(_KILL_WAIT * 1000))


def stop_requested(run: RunPaths) -> bool:
    try:
        request = read_json(run.run_dir / "stop.json")
    except FileNotFoundError:
        return False
    if (type(request.get("version")) is not int or request["version"] != 1 or request.get("run") != run.run_id
            or not isinstance(request.get("requested_at"), str)):
        raise ValueError("invalid protected stop request")
    return True


def request_stop(run: RunPaths) -> int:
    with publication_lock(run):
        status = terminal_exit(run)
        if status is not None:
            return status
        if stop_requested(run):
            fsync_dir(run.run_dir)
        else:
            publish_json(run.run_dir / "stop.json", {"version": 1, "run": run.run_id, "requested_at": utc_now()})
        return 0


def _finding(code: str, detail: str) -> Finding:
    return Finding(code, "development", detail)


def _await_actor(actor: Sandboxed, run: RunPaths, until: float) -> tuple[int | None, Cause, bool]:
    while True:
        remaining = until - time.monotonic()
        if remaining <= 0:
            cause: Cause = "deadline"
            break
        if stop_requested(run):
            cause = "stop"
            break
        try:
            exit_status = actor.wait(timeout=min(remaining, 1.0))
        except subprocess.TimeoutExpired:
            continue
        if time.monotonic() >= until:
            cause = "deadline"
            break
        return exit_status, "exit", _exited(actor.pidfd)
    try:
        ended = _terminate(actor.pidfd)
        return actor.wait(timeout=_KILL_WAIT), cause, ended
    except (OSError, subprocess.TimeoutExpired):
        return actor.process.poll(), cause, False


def supervise_actor(
    run: RunPaths, workspace: PreparedWorkspace, argv: tuple[str, ...], *, actor_fds: tuple[int, int, int],
    limits: Limits, deadline_seconds: float, grant_sha256: str, actor_launched: Callable[[], None] | None = None,
) -> ActorOutcome:
    until = 0.0
    armed = False

    @contextmanager
    def guard(child_pid: int, pidfd: int) -> Iterator[None]:
        nonlocal armed, until
        try:
            required = (limits.actor_fsize_bytes, limits.actor_fsize_bytes)
            if resource.prlimit(child_pid, resource.RLIMIT_FSIZE) != required or _exited(pidfd):
                raise ValueError("the held child lacks the required file size limit")
            start_time = _start_time(child_pid)
            boot_id = _boot_id()
        except (OSError, ValueError, IndexError) as caught:
            raise DevelopmentAborted(_finding("development-sandbox-unproven", f"{caught}; correct the launch guard and rerun")) from caught
        try:
            with publication_lock(run):
                if stop_requested(run):
                    raise DevelopmentAborted(_finding("development-stop-before-release", "stop preceded release; start a new run if needed"))
                if _exited(pidfd):
                    raise OSError("the held namespace exited")
                append_event(run.run_dir, "releasing", child_pid=child_pid, start_time=start_time,
                             boot_id=boot_id, grant_sha256=grant_sha256)
                armed = True
                until = time.monotonic() + deadline_seconds
                yield
        except (OSError, RunRefused, ValueError) as caught:
            code = "development-close-unproven" if armed else "development-gate-unproven"
            raise DevelopmentAborted(_finding(code, f"{caught}; inspect the retained release evidence")) from caught

    stdin, stdout, stderr = actor_fds
    try:
        actor = launch(replace(workspace.spec, disable_nested_userns=True), argv,
                       stdin=stdin, stdout=stdout, stderr=stderr, release_guard=guard,
                       actor_fsize_bytes=limits.actor_fsize_bytes)
    except (SandboxUnproven, OSError) as caught:
        raise DevelopmentAborted(_finding("development-sandbox-unproven", f"{caught}; correct the launch guard and rerun")) from caught

    try:
        if actor_launched is not None:
            actor_launched()
        append_event(run.run_dir, "launched", child_pid=actor.child_pid)
        exit_status, cause, ended = _await_actor(actor, run, until)
        findings = []
        if not ended:
            findings.append(_finding("development-close-unproven", "namespace shutdown could not be confirmed; inspect retained scratch"))
        if cause == "deadline":
            findings.append(_finding("development-deadline", "actor deadline expired; inspect retained work"))
        elif cause == "stop":
            findings.append(_finding("development-stopped", "operator stopped the run; inspect retained work"))
        elif exit_status != 0:
            findings.append(_finding("development-actor-failed", f"actor exited {exit_status}; inspect actor diagnostics"))
        if exit_status is not None:
            append_event(run.run_dir, "actor-ended", actor_exit=exit_status, cause=cause, containment_proven=ended)
        return ActorOutcome(exit_status, cause, ended, tuple(findings))
    finally:
        try:
            if not _exited(actor.pidfd):
                _send(actor.pidfd, signal.SIGKILL)
            if actor.process.poll() is None:
                actor.wait(timeout=_KILL_WAIT)
        except (OSError, subprocess.TimeoutExpired):
            # Keep the journal and scratch for recovery. The supervisor never
            # turns this into eligibility for a candidate.
            pass
        finally:
            os.close(actor.pidfd)


def _grant_digest(run: RunPaths) -> str | None:
    path = run.run_dir / "grant.json"
    try:
        grant = read_json(path)
    except FileNotFoundError:
        return None
    if grant.get("run") != run.run_id or grant.get("mode") != MODE or grant.get("run_sha256") != run.run_sha256:
        raise ValueError("grant identity does not match the run")
    return file_digest(path)


def _release_identity(run: RunPaths, digest: str | None) -> _Identity | None:
    allocated, *later = read_journal(run)
    for record in (allocated, *later):
        if not isinstance(record.get("at"), str):
            raise ValueError("event timestamp is missing")
    if allocated.get("event") != "allocated" or allocated.get("run") != run.run_id or allocated.get("mode") != MODE:
        raise ValueError("journal does not start with this run's allocation")
    if later and later[0].get("event") == "report-unwritten" and later[0].get("line") == "run":
        later.pop(0)
    if not later:
        return None
    row, *tail = later
    if row.get("event") != "releasing" or tuple(item.get("event") for item in tail) not in (
        (), ("launched",), ("launched", "actor-ended"),
    ):
        raise ValueError("unexpected release journal sequence")
    pid, ticks, boot_id = row.get("child_pid"), row.get("start_time"), row.get("boot_id")
    if (type(pid) is not int or pid <= 0 or type(ticks) is not int or ticks < 0
            or not isinstance(boot_id, str) or str(uuid.UUID(boot_id)) != boot_id
            or digest is None or row.get("grant_sha256") != digest):
        raise ValueError("release identity or grant digest is invalid")
    if tail and tail[0].get("child_pid") != pid:
        raise ValueError("launched identity differs from release")
    if len(tail) == 2 and (type(tail[1].get("actor_exit")) is not int
                           or tail[1].get("cause") not in ("exit", "deadline", "stop")
                           or type(tail[1].get("containment_proven")) is not bool):
        raise ValueError("invalid actor exit evidence")
    return _Identity(pid, ticks, boot_id)


def _recover_namespace(identity: _Identity) -> bool:
    try:
        if _boot_id() != identity.boot_id:
            return False
        try:
            fd = os.pidfd_open(identity.child_pid)
        except ProcessLookupError:
            return True
        try:
            if _exited(fd):
                return True
            if _start_time(identity.child_pid) != identity.start_time:
                return True  # That PID belongs to a replacement.
            return _terminate(fd)
        finally:
            os.close(fd)
    except (OSError, ValueError, IndexError, OverflowError):
        return False


def recover_run(run: RunPaths) -> int:
    status = terminal_exit(run)
    if status is not None:
        return status
    with supervisor_lock(run):
        status = terminal_exit(run)
        if status is not None:
            return status
        digest = None
        try:
            digest = _grant_digest(run)
            identity = _release_identity(run, digest)
        except (OSError, ValueError) as caught:
            finding = _finding("development-close-unproven", f"release evidence is uncertain ({caught}); inspect retained scratch")
        else:
            if identity is None:
                finding = _finding("orchestrator-lost", "the journal proves no release; inspect events and rerun if appropriate")
            elif _recover_namespace(identity):
                finding = _finding("development-close-unproven", "supervisor lost after possible release; containment confirmed, inspect retained work")
            else:
                finding = _finding("development-close-unproven", "supervisor lost and containment unconfirmed; inspect retained scratch")
        with publication_lock(run):
            return publish_terminal(run, (finding,), grant_sha256=digest, candidate_sha256=None)
