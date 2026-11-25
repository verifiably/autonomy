"""Compose the supervised offline development lifecycle."""

from __future__ import annotations

import math
import os
import secrets
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path

from autonomy.analyst.release import retain
from autonomy.baseline import append_event
from autonomy.channel import LineChannel
from autonomy.closing import disposition_of
from autonomy.delegation import Host, current_host, in_user_service
from autonomy.development._candidate import VerifiedCandidate, publish_candidate, validate_candidate
from autonomy.development._delegated import admit, begin, check_base, check_bounds
from autonomy.development._records import (
    MODE,
    REF,
    DevelopmentAborted,
    RunPaths,
    allocate_run,
    development_places,
    lookup_run,
    publication_lock,
    publish_grant,
    publish_terminal,
)
from autonomy.development._supervisor import prove_development_host, recover_run, request_stop, stop_requested, supervise_actor
from autonomy.development._workspace import Limits, admit_source, prepare_workspace
from autonomy.membership import Finding
from autonomy.run import DevelopmentProgress, Diag, RunRefused, _line, check_run_stdio
from autonomy.sandbox.spec import IN_SANDBOX_OUTPUTS, SYSTEM_RO
from autonomy.sandbox.static import SandboxUnproven
from autonomy.stdio import ACTOR_FDS


@dataclass(frozen=True)
class DevelopmentRequest:
    repository: Path
    base: str
    deadline_seconds: float
    actor_argv: tuple[str, ...]
    report_fd: int | None
    delegation: str | None = None
    attempt: str | None = None


def _report(run: RunPaths, channel: LineChannel | None, phase: str, fields: Mapping[str, object]) -> None:
    if channel is not None and not channel.write_line(_line({"run": run.run_id, "mode": MODE, **fields})):
        append_event(run.run_dir, "report-unwritten", line=phase)


def _finish(
    run: RunPaths, progress: DevelopmentProgress, findings: list[Finding], result: VerifiedCandidate | None,
    *, grant_sha256: str | None, base: str, possible_release: bool, containment_proven: bool,
) -> int:
    with publication_lock(run):
        if stop_requested(run):
            code = "development-stopped" if possible_release else "development-stop-before-release"
            if not any(finding.code == code for finding in findings):
                findings.append(Finding(code, "development", "stop preceded the verdict. Inspect retained work."))
        receipt = None
        if not findings:
            if result is None or grant_sha256 is None:
                raise ValueError("candidate validation evidence is incomplete")
            try:
                receipt = publish_candidate(run, result, grant_sha256=grant_sha256, base=base)
            except DevelopmentAborted as caught:
                findings.append(caught.finding)
        status = publish_terminal(
            run, findings, grant_sha256=grant_sha256, candidate_sha256=receipt,
            containment_proven=containment_proven,
        )
        progress.durable_exit = status
    return status


def _retain_scratch(run: RunPaths, scratch_fd: int, limits: Limits) -> None:
    """Keep an unpromoted actor's work for inspection. The verdict is already durable, so
    a full disk costs the copy and never the verdict. The caller's stderr is already
    released, so the journal is where a failure shows."""
    try:
        tally = retain(scratch_fd, run.scratch, max_bytes=limits.actor_storage_bytes)
    except OSError as caught:
        append_event(run.run_dir, "scratch-unretained", detail=str(caught))
    else:
        append_event(run.run_dir, "scratch-retained", **tally.to_json())


def execute(
    request: DevelopmentRequest, env: Mapping[str, str], *, diag: Diag, progress: DevelopmentProgress,
    actor_fds: tuple[int, int, int] = ACTOR_FDS, actor_launched: Callable[[], None] | None = None,
    host: Host | None = None,
) -> int:
    if not math.isfinite(request.deadline_seconds) or request.deadline_seconds <= 0:
        raise RunRefused("deadline-invalid", "supply a positive finite actor deadline")
    if not request.actor_argv or not request.actor_argv[0]:
        raise RunRefused("development-mode-conflict", "supply an actor executable after --")
    if (request.delegation is None) != (request.attempt is None):
        raise RunRefused("development-mode-conflict", "pass --delegation and --attempt together")
    stdio = check_run_stdio(request.report_fd, actor_fds)
    resolved_host = current_host() if host is None else host
    if request.delegation is None and in_user_service(resolved_host.cgroup):
        raise RunRefused("delegation-required", "pass --delegation and --attempt when starting from a user service")
    try:
        prove_development_host()
    except SandboxUnproven as caught:
        raise RunRefused("development-launch-unavailable", f"{caught}. Start from a host with working namespace support.") from caught

    if request.delegation is not None:
        assert request.attempt is not None
        chosen_run_id = secrets.token_hex(16)
        admission = admit(
            resolved_host,
            delegation=request.delegation,
            attempt=request.attempt,
            repository=request.repository,
            argv=request.actor_argv,
            deadline=request.deadline_seconds,
            run_id=chosen_run_id,
        )
        limits = admission.limits
    else:
        chosen_run_id = None
        admission = None
        limits = Limits()

    places = development_places(env)
    try:
        source = admit_source(request.repository, request.base, limits=limits)
    except SandboxUnproven as caught:
        raise RunRefused("development-launch-unavailable", f"{caught}. Start from a host with working namespace support.") from caught
    for destination in (places.state / "runs", places.cache / "scratch"):
        if destination.is_relative_to(source.repository) or source.repository.is_relative_to(destination):
            raise RunRefused("development-repository-invalid", "choose a source repository separate from run state and scratch")

    if admission is not None:
        check_base(admission, source)
        check_bounds(admission, resolved_host)

    report = None
    try:
        if request.report_fd is not None:
            report = LineChannel(request.report_fd)
        with ExitStack() as outer:
            if admission is not None:
                assert chosen_run_id is not None
                ordinal = outer.enter_context(
                    begin(
                        admission, resolved_host, places, source, chosen_run_id,
                        deadline=request.deadline_seconds, diag=diag,
                    )
                )
                header_delegation: Mapping[str, str] | None = {
                    "id": admission.grant.name,
                    "grant_digest": admission.config.digest,
                    "attempt": admission.attempt,
                }
            else:
                ordinal = None
                header_delegation = None

            run = outer.enter_context(
                allocate_run(
                    places,
                    repository=source.repository,
                    base=source.oid,
                    deadline_seconds=request.deadline_seconds,
                    run_id=chosen_run_id,
                    delegation=header_delegation,
                )
            )
            held = outer.enter_context(ExitStack())
            progress.run_dir = run.run_dir
            diag(f"development run {run.run_id} in {run.run_dir}")
            _report(run, report, "run", {
                "run_dir": str(run.run_dir), "scratch": str(run.scratch), "base": source.oid, "ref": REF,
                "bundle_path": str(IN_SANDBOX_OUTPUTS / "candidate.bundle"),
            })
            findings: list[Finding] = []
            result = None
            outcome = None
            grant_digest = None
            possible_release = False
            try:
                if admission is not None:
                    try:
                        admission.grant.mark(run.run_id)
                    except Exception as caught:
                        raise DevelopmentAborted(Finding(
                            "development-delegation-ended",
                            "delegation",
                            f"cannot mark delegated start allocated: {caught}",
                        )) from caught

                workspace = prepare_workspace(
                    run,
                    source,
                    config=resolved_host.config if admission is not None else places.config,
                    limits=limits,
                )
                grant_delegation: Mapping[str, object] | None = None if admission is None else {
                    "id": admission.grant.name,
                    "grant_digest": admission.config.digest,
                    "storage": admission.config.storage,
                    "attempt": admission.attempt,
                    "start": ordinal,
                    "repository": admission.repository,
                    "actor": admission.actor,
                    "ref": admission.ref,
                    "caller": {
                        "unit": admission.caller.unit,
                        "cgroup": admission.caller.cgroup,
                        "invocation_id": admission.caller.invocation,
                    },
                    "bounds": {
                        "memory_bytes": admission.bounds.memory_bytes,
                        "swap_bytes": 0,
                        "tasks": admission.bounds.tasks,
                    },
                }
                grant_digest = publish_grant(
                    run, base_sha256=workspace.base_sha256, walk_sha256=workspace.walk_sha256,
                    read_only=tuple(path.resolve() for path in (*SYSTEM_RO, *workspace.spec.ro_binds)),
                    denied=workspace.denied, stdio=stdio,
                    limits={**asdict(limits), "deadline_seconds": request.deadline_seconds},
                    delegation=grant_delegation,
                )
                outcome = supervise_actor(
                    run, workspace, request.actor_argv, actor_fds=actor_fds, limits=limits,
                    deadline_seconds=request.deadline_seconds, grant_sha256=grant_digest,
                    actor_launched=actor_launched,
                    bounds=None if admission is None else admission.bounds,
                )
                held.callback(os.close, outcome.scratch_fd)
                possible_release = True
                findings.extend(outcome.findings)
                if not findings and outcome.actor_exit == 0 and outcome.cause == "exit" and outcome.containment_proven:
                    result = validate_candidate(run, source, workspace, outcome.scratch_fd, limits=limits)
            except DevelopmentAborted as caught:
                findings.append(caught.finding)
                possible_release |= caught.finding.code == "development-close-unproven"
            status = _finish(
                run, progress, findings, result, grant_sha256=grant_digest, base=source.oid,
                possible_release=possible_release,
                containment_proven=outcome.containment_proven if outcome is not None else not possible_release,
            )
            disposition = disposition_of(findings)
            try:
                if status and outcome is not None and outcome.containment_proven:
                    _retain_scratch(run, outcome.scratch_fd, limits)
            finally:
                _report(run, report, "closing", {"disposition": disposition, "exit": status})
            diag(f"development run {run.run_id} closed {disposition}")
            return status
    finally:
        try:
            if report is not None:
                report.close()
        finally:
            if request.report_fd is not None:
                os.close(request.report_fd)


def stop(run_id: str, env: Mapping[str, str], *, diag: Diag) -> int:
    status = request_stop(lookup_run(development_places(env), run_id))
    diag(f"development run {run_id} stop returned {status}")
    return status


def close(run_id: str, env: Mapping[str, str], *, diag: Diag) -> int:
    status = recover_run(lookup_run(development_places(env), run_id))
    diag(f"development run {run_id} close returned {status}")
    return status
