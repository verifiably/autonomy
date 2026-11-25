"""Settlement, status reporting, revocation, and admission for delegated development runs."""

from __future__ import annotations

import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from autonomy.allowance import AllowanceRefused, storage
from autonomy.baseline import fsync_dir, utc_now
from autonomy.delegation import (
    TERMINATION_SECONDS,
    ActorCgroup,
    Caller,
    Ceiling,
    Delegation,
    Grant,
    Host,
    Start,
    check_unit,
    identify,
    identifier,
    peak_memory,
    within,
)
from autonomy.development._records import (
    DevelopmentPlaces,
    RunPaths,
    Terminal,
    lookup_run,
    publication_lock,
    publish_json,
    read_terminal,
)
from autonomy.development._refs import branch_tip
from autonomy.development._supervisor import ActorBounds, stop_requested
from autonomy.development._workspace import Limits, SourceBase
from autonomy.run import Diag, RunRefused


@dataclass(frozen=True)
class Admission:
    grant: Delegation
    config: Grant
    caller: Caller
    repository: str
    actor: str
    ref: str
    limits: Limits
    bounds: ActorBounds
    attempt: str = ""


@dataclass(frozen=True)
class Revocation:
    cause: str
    first: Literal["stop", "verdict"] | None
    actor: Literal["empty", "occupied"]
    acknowledged: bool


def ceiling(limits: Limits = Limits()) -> Ceiling:
    return Ceiling(
        prepared_bytes=limits.base_bytes + limits.candidate_bytes,
        storage_bytes=limits.actor_storage_bytes,
        storage_inodes=limits.actor_storage_inodes,
        receiver_bytes=limits.receiver_memory_bytes + limits.receiver_storage_bytes,
        prepare_seconds=limits.prepare_seconds,
    )


def open_grant(host: Host, delegation_id: str) -> Delegation:
    name = identifier(delegation_id)
    try:
        root = storage(host.config)
    except AllowanceRefused as caught:
        raise RunRefused("delegation-unavailable", str(caught)) from caught
    return Delegation(root, name)


def _read_verdict(start: Start, host: Host) -> Terminal | None:
    places = DevelopmentPlaces(start.state, start.cache, host.config)
    try:
        run = lookup_run(places, start.run)
        return read_terminal(run)
    except OSError:
        return None
    except RunRefused as caught:
        if caught.code == "development-run-invalid":
            return None
        raise


def settle(grant: Delegation, host: Host) -> None:
    for start in grant.starts():
        if start.outcome is not None:
            continue
        try:
            cgroup_cleared = host.actor_cgroup(start.cgroup, start.run).remove(wait=5.0)
        except OSError:
            cgroup_cleared = False
        terminal = _read_verdict(start, host)
        if terminal is not None:
            if not cgroup_cleared or not terminal.containment_proven:
                grant.contain()
            grant.settle(start.run, terminal.disposition, terminal.sha256)
        else:
            if not cgroup_cleared:
                grant.contain()
            if not start.allocated:
                grant.settle(start.run, "not-allocated", None)


def _leftover_directories(start: Start) -> list[str]:
    found: list[str] = []
    for candidate in (start.state / "runs" / start.run, start.cache / "scratch" / start.run):
        try:
            if candidate.exists() or candidate.is_symlink():
                found.append(str(candidate))
        except OSError:
            continue
    return found


def _serialize_start(start: Start, *, lock_held: bool) -> dict[str, object]:
    if start.outcome is not None:
        outcome = start.outcome
    else:
        outcome = "running" if lock_held else "unfinished"
    leftover = _leftover_directories(start) if outcome == "not-allocated" else []
    return {
        "ordinal": start.ordinal,
        "attempt": start.attempt,
        "run": start.run,
        "at": start.at,
        "roots": {"state": str(start.state), "cache": str(start.cache)},
        "repository": start.repository,
        "actor": start.actor,
        "base": start.base,
        "deadline_seconds": start.deadline,
        "caller": {
            "unit": start.unit,
            "cgroup": start.cgroup,
            "invocation_id": start.invocation,
        },
        "allocated": start.allocated,
        "outcome": outcome,
        "disposition_sha256": start.disposition_sha256,
        "leftover": leftover,
    }


def report(grant: Delegation, host: Host, attempt: str | None = None) -> dict[str, object]:
    selected = None if attempt is None else identifier(attempt)
    try:
        with grant.lock(wait=1.0):
            settle(grant, host)
            info = grant.grant()
            all_starts = grant.starts()
            lock_held = False
    except RunRefused as caught:
        if caught.code != "delegation-busy":
            raise
        lock_held = True
        info = grant.grant()
        all_starts = grant.starts()

    visible = all_starts if selected is None else tuple(s for s in all_starts if s.attempt == selected)
    starts_left = max(0, int(info.config["limits"]["starts"]) - len(all_starts))
    return {
        "grant": info.config,
        "grant_digest": info.digest,
        "storage": info.storage,
        "closed": info.closed,
        "starts_left": starts_left,
        "starts": [_serialize_start(item, lock_held=lock_held) for item in visible],
    }


def _wait_empty(cgroup: ActorCgroup, seconds: float) -> bool:
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        try:
            if cgroup.empty():
                return True
        except OSError:
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.02, remaining))
    try:
        return cgroup.empty()
    except OSError:
        return False


def _kill_and_wait(cgroup: ActorCgroup, seconds: float) -> bool:
    try:
        cgroup.kill()
    except OSError:
        pass
    return _wait_empty(cgroup, seconds)


def revoke(
    grant: Delegation,
    host: Host,
    *,
    lock_wait: float = 5.0,
    stop_wait: float = 16.0,
    kill_wait: float = 5.0,
) -> Revocation:
    cause = grant.revoke()
    try:
        with grant.lock(wait=1.0):
            settle(grant, host)
    except RunRefused as caught:
        if caught.code != "delegation-busy":
            raise

    unfinished = [item for item in grant.starts() if item.allocated and item.outcome is None]
    if not unfinished:
        return Revocation(cause=cause, first=None, actor="empty", acknowledged=True)

    start = unfinished[0]
    cgroup = host.actor_cgroup(start.cgroup, start.run)
    places = DevelopmentPlaces(start.state, start.cache, host.config)
    first: Literal["stop", "verdict"] | None = None
    recorded = False
    run: RunPaths | None = None

    try:
        run = lookup_run(places, start.run)
        with publication_lock(run, wait=lock_wait):
            if read_terminal(run) is not None:
                first = "verdict"
                recorded = True
            else:
                if stop_requested(run):
                    fsync_dir(run.run_dir)
                else:
                    publish_json(
                        run.run_dir / "stop.json",
                        {"version": 1, "run": run.run_id, "requested_at": utc_now()},
                    )
                first = "stop"
                recorded = True
    except (OSError, TimeoutError, ValueError, RunRefused):
        pass

    if not recorded:
        empty = _kill_and_wait(cgroup, kill_wait)
    elif _wait_empty(cgroup, stop_wait):
        empty = True
    else:
        empty = _kill_and_wait(cgroup, kill_wait)

    return Revocation(
        cause=cause,
        first=first,
        actor="empty" if empty else "occupied",
        acknowledged=recorded and empty,
    )


def admit(
    host: Host,
    *,
    delegation: str,
    attempt: str,
    repository: Path,
    argv: tuple[str, ...],
    deadline: float,
    run_id: str | None = None,
) -> Admission:
    delegation_id = identifier(delegation)
    attempt_id = identifier(attempt)
    grant = open_grant(host, delegation_id)
    info = grant.grant()
    if info.closed == "expired":
        raise RunRefused("delegation-expired", "delegation has expired")
    if info.closed is not None:
        raise RunRefused("delegation-closed", f"delegation is closed ({info.closed})")

    caller = identify(host, info.config["orchestrator"]["unit"])
    try:
        canonical_repo = str(repository.resolve(strict=True))
    except OSError as exc:
        raise RunRefused("delegation-repository", f"repository path is unavailable: {exc}") from exc
    matched_repo = next(
        ((name, entry["ref"]) for name, entry in info.config["repositories"].items() if entry["path"] == canonical_repo),
        None,
    )
    if matched_repo is None:
        raise RunRefused("delegation-repository", "repository path is not granted")
    repo_name, ref = matched_repo

    argv_list = list(argv)
    actor_name = next(
        (name for name, cmd in info.config["actors"].items() if cmd == argv_list),
        None,
    )
    if actor_name is None:
        raise RunRefused("delegation-actor", "actor argv is not granted")

    grant_limits = info.config["limits"]
    if deadline > grant_limits["deadline_seconds"]:
        raise RunRefused("delegation-deadline", "deadline exceeds the granted limit")

    chosen_run_id = secrets.token_hex(16) if run_id is None else run_id
    run_limits = replace(Limits(), actor_storage_bytes=int(grant_limits["writable_bytes"]))
    bounds = ActorBounds(
        cgroup=host.actor_cgroup(caller.cgroup, chosen_run_id),
        memory_bytes=int(grant_limits["memory_bytes"]),
        tasks=int(grant_limits["tasks"]),
        expires=int(info.config["expires"]),
    )
    return Admission(
        grant=grant,
        config=info,
        caller=caller,
        repository=repo_name,
        actor=actor_name,
        ref=ref,
        limits=run_limits,
        bounds=bounds,
        attempt=attempt_id,
    )


def check_base(admission: Admission, source: SourceBase) -> None:
    tip = branch_tip(source.repository, admission.ref)
    if tip != source.oid:
        raise RunRefused("delegation-base", f"base {source.oid} differs from {admission.ref} tip {tip}")


def check_bounds(admission: Admission, host: Host) -> None:
    ceil = ceiling(Limits())
    grant_limits = admission.config.config["limits"]
    within(grant_limits, ceil)
    check_unit(
        host,
        admission.caller,
        peak=peak_memory(grant_limits, ceil),
        tasks=int(grant_limits["tasks"]),
    )


@contextmanager
def begin(
    admission: Admission,
    host: Host,
    places: DevelopmentPlaces,
    source: SourceBase,
    run_id: str,
    *,
    deadline: float,
    diag: Diag | None = None,
) -> Iterator[int]:
    with admission.grant.lock(wait=1.0):
        settle(admission.grant, host)
        margin = admission.limits.prepare_seconds + deadline + TERMINATION_SECONDS
        start = Start(
            ordinal=0,
            attempt=admission.attempt,
            run=run_id,
            at=int(time.time()),
            state=places.state,
            cache=places.cache,
            repository=admission.repository,
            actor=admission.actor,
            base=source.oid,
            deadline=deadline,
            unit=admission.caller.unit,
            cgroup=admission.caller.cgroup,
            invocation=admission.caller.invocation,
            allocated=False,
            outcome=None,
            disposition_sha256=None,
        )
        ordinal = admission.grant.begin(start, margin=margin)
        try:
            try:
                yield ordinal
            finally:
                try:
                    settle(admission.grant, host)
                except (OSError, RunRefused) as caught:
                    if diag is not None:
                        diag(f"delegation settlement warning: {caught}")
        finally:
            try:
                cleared = admission.bounds.cgroup.remove(wait=5.0)
            except OSError as caught:
                cleared = False
                if diag is not None:
                    diag(f"actor cgroup cleanup failed: {caught}")
            if not cleared and diag is not None:
                diag(f"actor cgroup {admission.bounds.cgroup.path} is still occupied")
