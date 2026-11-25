"""Transfer and verify a candidate, or the actor's declaration that it found nothing to do,
without trusting the actor's Git repository."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from autonomy.analyst.release import ReleasedFile, ReleaseFileMissing, ReleaseFileRefused, release_file
from autonomy.baseline import fsync_dir, utc_now
from autonomy.development._git import GitFailed, run_worker
from autonomy.development._records import (
    BASE_REF,
    MODE,
    NO_CANDIDATE,
    NO_CANDIDATE_BYTES,
    REF,
    DevelopmentAborted,
    RunPaths,
    check_declaration,
    file_digest,
    publish_json,
)
from autonomy.development._workspace import Limits, PreparedWorkspace, SourceBase
from autonomy.membership import Finding

_BUNDLE = "candidate.bundle"


@dataclass(frozen=True)
class VerifiedCandidate:
    tip: str
    staged: ReleasedFile
    base_sha256: str


@dataclass(frozen=True)
class DeclaredNoCandidate:
    staged: ReleasedFile


def _aborted(code: str, detail: str, ref: str = _BUNDLE) -> DevelopmentAborted:
    return DevelopmentAborted(Finding(code, ref, detail))


def _release_declaration(run: RunPaths, scratch_fd: int) -> ReleasedFile | None:
    try:
        staged = release_file(scratch_fd, "outputs", NO_CANDIDATE, run.run_dir / ".no-candidate-staged.json",
                              max_bytes=NO_CANDIDATE_BYTES)
    except ReleaseFileMissing:
        return None
    except ReleaseFileRefused as caught:
        raise _aborted("development-no-candidate-invalid", f"{caught}; write one small declaration file",
                       NO_CANDIDATE) from caught
    try:
        check_declaration(staged.path.read_bytes())
    except (OSError, ValueError) as caught:
        raise _aborted("development-no-candidate-invalid",
                       f"{caught}; write {{\"version\": 1, \"reason\": \"...\"}}", NO_CANDIDATE) from caught
    return staged


def validate_candidate(
    run: RunPaths, source: SourceBase, workspace: PreparedWorkspace, scratch_fd: int, *, limits: Limits,
) -> VerifiedCandidate | DeclaredNoCandidate:
    """A declaration with no bundle is the actor saying it found nothing to do. Saying
    nothing stays a missing bundle, and saying both is a conflict."""
    declaration = _release_declaration(run, scratch_fd)
    conflict = "write either the bundle or the no-candidate declaration, not both"
    try:
        staged = release_file(scratch_fd, "outputs", _BUNDLE, run.run_dir / ".candidate-staged.bundle",
                              max_bytes=limits.candidate_bytes)
    except ReleaseFileMissing as caught:
        if declaration is not None:
            return DeclaredNoCandidate(declaration)
        raise _aborted("development-bundle-missing",
                       f"{caught}; write the declared output or declare no candidate, and rerun") from caught
    except ReleaseFileRefused as caught:
        if declaration is not None:
            raise _aborted("development-no-candidate-conflict", f"{caught}; {conflict}", NO_CANDIDATE) from caught
        raise _aborted("development-bundle-refused", f"{caught}; produce one eligible bounded file") from caught
    if declaration is not None:
        raise _aborted("development-no-candidate-conflict", conflict, NO_CANDIDATE)
    base_bundle = run.run_dir / "base.bundle"
    try:
        until = time.monotonic() + limits.receiver_seconds
        if file_digest(base_bundle) != workspace.base_sha256:
            raise GitFailed("protected base export differs from the grant")
        tip = run_worker(
            "validate", (source.object_format, source.oid, BASE_REF, REF), until=until,
            memory_bytes=limits.receiver_memory_bytes, storage_bytes=limits.receiver_storage_bytes,
            read_only=((base_bundle, "/base.bundle"), (staged.path, "/candidate.bundle")),
        )
        if len(tip) != len(source.oid) or re.fullmatch(r"[0-9a-f]+", tip) is None:
            raise GitFailed("the receiver did not return a valid candidate tip")
    except (GitFailed, OSError) as caught:
        if isinstance(caught, GitFailed) and caught.input_invalid:
            raise _aborted("development-bundle-header-invalid", f"{caught}; export the declared ref against the pinned base") from caught
        raise _aborted("development-bundle-validation-failed", f"{caught}; generate an eligible bundle and rerun") from caught
    return VerifiedCandidate(tip, staged, workspace.base_sha256)


def publish_candidate(run: RunPaths, result: VerifiedCandidate, *, grant_sha256: str, base: str) -> str:
    try:
        if file_digest(result.staged.path) != result.staged.sha256:
            raise OSError("protected staging bytes changed")
        os.link(result.staged.path, run.run_dir / _BUNDLE, follow_symlinks=False)
        result.staged.path.unlink()
        fsync_dir(run.run_dir)
        return publish_json(run.run_dir / "candidate.json", {
            "version": 2, "run": run.run_id, "mode": MODE, "base": base, "ref": REF, "tip": result.tip,
            "base_sha256": result.base_sha256, "bundle_sha256": result.staged.sha256,
            "grant_sha256": grant_sha256, "actor_exit": 0, "closed_at": utc_now(),
        })
    except (OSError, ValueError) as caught:
        raise _aborted("development-candidate-unrecorded", f"{caught}; restore storage and inspect retained evidence") from caught


def publish_no_candidate(run: RunPaths, result: DeclaredNoCandidate) -> str:
    try:
        if file_digest(result.staged.path) != result.staged.sha256:
            raise OSError("protected staging bytes changed")
        os.link(result.staged.path, run.run_dir / NO_CANDIDATE, follow_symlinks=False)
        result.staged.path.unlink()
        fsync_dir(run.run_dir)
        return result.staged.sha256
    except OSError as caught:
        raise _aborted("development-candidate-unrecorded", f"{caught}; restore storage and inspect retained evidence",
                       NO_CANDIDATE) from caught
