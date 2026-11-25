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
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from autonomy.baseline import append_event, fsync_dir, utc_now
from autonomy.delegation import TERMINATION_SECONDS, ActorCgroup
from autonomy.development._records import (
    MODE,
    DevelopmentAborted,
    RunPaths,
    boot_id,
    file_digest,
    publication_lock,
    publish_json,
    publish_terminal,
    read_journal,
    read_json,
    supervisor_lock,
    terminal_exit,
)
from autonomy.development._workspace import Limits, PreparedWorkspace, seed_scratch
from autonomy.membership import Finding
from autonomy.run import RunRefused
from autonomy.sandbox.bwrap import Sandboxed, launch, prove_development_host
from autonomy.sandbox.spec import Storage
from autonomy.sandbox.static import SandboxUnproven
from autonomy.sandbox.storage import hold_storage

__all__ = [
    "ActorBounds",
    "ActorOutcome",
    "prove_development_host",
    "recover_run",
    "request_stop",
    "stop_requested",
    "supervise_actor",
]

_TERM_GRACE = 10.0
_KILL_WAIT = 5.0
Cause = Literal["exit", "deadline", "stop"]


@dataclass(frozen=True)
class ActorBounds:
    cgroup: ActorCgroup
    memory_bytes: int
    tasks: int
    expires: int


@dataclass(frozen=True)
class ActorOutcome:
    actor_exit: int | None
    cause: Cause | None
    containment_proven: bool
    findings: tuple[Finding, ...]
    scratch_fd: int


@dataclass(frozen=True)
class _Identity:
    child_pid: int
    start_time: int
    boot_id: str


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
        # The outer wrapper can exit just before its namespace init.
        return exit_status, "exit", _exited(actor.pidfd, int(_KILL_WAIT * 1000))
    try:
        ended = _terminate(actor.pidfd)
        return actor.wait(timeout=_KILL_WAIT), cause, ended
    except (OSError, subprocess.TimeoutExpired):
        return actor.process.poll(), cause, False


def supervise_actor(
    run: RunPaths, workspace: PreparedWorkspace, argv: tuple[str, ...], *, actor_fds: tuple[int, int, int],
    limits: Limits, deadline_seconds: float, grant_sha256: str, actor_launched: Callable[[], None] | None = None,
    bounds: ActorBounds | None = None,
) -> ActorOutcome:
    """Run the actor to its end. The outcome's scratch descriptor is the caller's to close:
    the bounded pool holding the actor's work ends with it."""
    with ExitStack() as held:
        outcome = _supervise(
            run, workspace, argv, held, actor_fds=actor_fds, limits=limits, deadline_seconds=deadline_seconds,
            grant_sha256=grant_sha256, actor_launched=actor_launched, bounds=bounds,
        )
        held.pop_all()
        return outcome


def _supervise(
    run: RunPaths, workspace: PreparedWorkspace, argv: tuple[str, ...], held: ExitStack, *,
    actor_fds: tuple[int, int, int], limits: Limits, deadline_seconds: float, grant_sha256: str,
    actor_launched: Callable[[], None] | None, bounds: ActorBounds | None,
) -> ActorOutcome:
    until = 0.0
    armed = False
    scratch_fd = -1
    spec = replace(workspace.spec, disable_nested_userns=True,
                   storage=Storage(limits.actor_storage_bytes, limits.actor_storage_inodes))

    @contextmanager
    def guard(child_pid: int, pidfd: int) -> Iterator[None]:
        nonlocal armed, scratch_fd, until
        try:
            required = (limits.actor_fsize_bytes, limits.actor_fsize_bytes)
            if resource.prlimit(child_pid, resource.RLIMIT_FSIZE) != required or _exited(pidfd):
                raise ValueError("the held child lacks the required file size limit")
            if bounds is not None:
                bounds.cgroup.check(child_pid, memory_bytes=bounds.memory_bytes, tasks=bounds.tasks)
            scratch_fd = hold_storage(child_pid, spec)
            held.callback(os.close, scratch_fd)
            start_time = _start_time(child_pid)
            current_boot = boot_id()
        except (SandboxUnproven, OSError, ValueError, IndexError) as caught:
            raise DevelopmentAborted(_finding("development-sandbox-unproven", f"{caught}; correct the launch guard and rerun")) from caught
        try:
            seed_scratch(run.scratch, scratch_fd)
        except OSError as caught:
            detail = str(caught)[:3000]
            raise DevelopmentAborted(_finding("development-workspace-unproven", f"{detail}; select a base that fits the storage bound")) from caught
        try:
            with publication_lock(run):
                if stop_requested(run):
                    raise DevelopmentAborted(_finding("development-stop-before-release", "stop preceded release; start a new run if needed"))
                if bounds is not None and time.time() + deadline_seconds + TERMINATION_SECONDS > bounds.expires:
                    raise DevelopmentAborted(_finding(
                        "development-delegation-ended",
                        "too little delegation lifetime remains for the actor deadline and termination grace",
                    ))
                if _exited(pidfd):
                    raise OSError("the held namespace exited")
                append_event(run.run_dir, "releasing", child_pid=child_pid, start_time=start_time,
                             boot_id=current_boot, grant_sha256=grant_sha256)
                armed = True
                until = time.monotonic() + deadline_seconds
                yield
        except (SandboxUnproven, OSError, RunRefused, ValueError) as caught:
            code = "development-close-unproven" if armed else "development-gate-unproven"
            raise DevelopmentAborted(_finding(code, f"{caught}; inspect the retained release evidence")) from caught

    stdin, stdout, stderr = actor_fds
    try:
        if bounds is not None:
            bounds.cgroup.create(memory_bytes=bounds.memory_bytes, tasks=bounds.tasks)
        # The pinned worker shows that the sandbox has finished its mounts.
        actor = launch(
            spec, argv, stdin=stdin, stdout=stdout, stderr=stderr, release_guard=guard,
            actor_fsize_bytes=limits.actor_fsize_bytes,
            actor_cgroup=None if bounds is None else bounds.cgroup.path,
            track_worker=True,
        )
    except (SandboxUnproven, OSError, ValueError) as caught:
        raise DevelopmentAborted(_finding("development-sandbox-unproven", f"{caught}; correct the launch guard and rerun")) from caught

    try:
        if actor_launched is not None:
            actor_launched()
        append_event(run.run_dir, "launched", child_pid=actor.child_pid)
        exit_status, cause, ended = _await_actor(actor, run, until)
        usage = os.fstatvfs(scratch_fd)
        findings = []
        if not ended:
            findings.append(_finding("development-close-unproven", "namespace shutdown could not be confirmed; the actor's scratch is not retained"))
        if cause == "deadline":
            findings.append(_finding("development-deadline", "actor deadline expired; inspect retained work"))
        elif cause == "stop":
            findings.append(_finding("development-stopped", "operator stopped the run; inspect retained work"))
        elif exit_status != 0:
            findings.append(_finding("development-actor-failed", f"actor exited {exit_status}; inspect actor diagnostics"))
        if findings and (usage.f_bfree == 0 or usage.f_ffree == 0):
            findings.append(_finding("development-storage-exhausted", (
                f"the storage bound of {limits.actor_storage_bytes} bytes and {limits.actor_storage_inodes} inodes "
                "was full at the end; inspect retained work")))
        if exit_status is not None:
            append_event(run.run_dir, "actor-ended", actor_exit=exit_status, cause=cause, containment_proven=ended,
                         storage_bytes=(usage.f_blocks - usage.f_bfree) * usage.f_frsize,
                         storage_inodes=usage.f_files - usage.f_ffree)
        return ActorOutcome(exit_status, cause, ended, tuple(findings), scratch_fd)
    finally:
        try:
            if not _exited(actor.pidfd):
                _send(actor.pidfd, signal.SIGKILL)
            if actor.process.poll() is None:
                actor.wait(timeout=_KILL_WAIT)
        except (OSError, subprocess.TimeoutExpired):
            # Keep the journal for recovery. The supervisor never turns this
            # into eligibility for a candidate.
            pass
        finally:
            actor.close_handles()


def _grant_digest(run: RunPaths) -> str | None:
    path = run.run_dir / "grant.json"
    try:
        grant = read_json(path)
    except FileNotFoundError:
        return None
    if (
        grant.get("version") != 2 or grant.get("run") != run.run_id
        or grant.get("mode") != MODE or grant.get("run_sha256") != run.run_sha256
    ):
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
    pid, ticks, recorded_boot = row.get("child_pid"), row.get("start_time"), row.get("boot_id")
    if (type(pid) is not int or pid <= 0 or type(ticks) is not int or ticks < 0
            or not isinstance(recorded_boot, str) or str(uuid.UUID(recorded_boot)) != recorded_boot
            or digest is None or row.get("grant_sha256") != digest):
        raise ValueError("release identity or grant digest is invalid")
    if tail and tail[0].get("child_pid") != pid:
        raise ValueError("launched identity differs from release")
    if len(tail) == 2 and (type(tail[1].get("actor_exit")) is not int
                           or tail[1].get("cause") not in ("exit", "deadline", "stop")
                           or type(tail[1].get("containment_proven")) is not bool):
        raise ValueError("invalid actor exit evidence")
    return _Identity(pid, ticks, recorded_boot)


def _recover_namespace(identity: _Identity) -> bool:
    try:
        if boot_id() != identity.boot_id:
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
        try:
            rebooted = run.boot_id != boot_id()
        except (OSError, ValueError):
            rebooted = False
        digest = None
        try:
            digest = _grant_digest(run)
            identity = _release_identity(run, digest)
        except (OSError, ValueError) as caught:
            finding = _finding("development-close-unproven", f"release evidence is uncertain ({caught}); inspect the journal")
            containment_proven = rebooted
        else:
            if identity is None:
                finding = _finding("orchestrator-lost", "the journal proves no release; inspect events and rerun if appropriate")
                containment_proven = True
            elif rebooted:
                finding = _finding("development-close-unproven", "supervisor lost across a reboot; the prior boot ended, the actor's scratch is gone")
                containment_proven = True
            elif _recover_namespace(identity):
                finding = _finding("development-close-unproven", "supervisor lost after possible release; containment confirmed, the actor's scratch is gone")
                containment_proven = True
            else:
                finding = _finding("development-close-unproven", "supervisor lost and containment unconfirmed; inspect the recorded namespace")
                containment_proven = False
        with publication_lock(run):
            return publish_terminal(
                run, (finding,), grant_sha256=digest, candidate_sha256=None,
                containment_proven=containment_proven,
            )
