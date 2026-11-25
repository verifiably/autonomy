"""Transfer and verify a candidate without trusting the actor's Git repository."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from autonomy.analyst.release import ReleasedFile, ReleaseFileMissing, ReleaseFileRefused, release_file
from autonomy.baseline import fsync_dir, utc_now
from autonomy.development._git import GitFailed, run_worker
from autonomy.development._records import BASE_REF, MODE, REF, DevelopmentAborted, RunPaths, file_digest, publish_json
from autonomy.development._workspace import Limits, PreparedWorkspace, SourceBase
from autonomy.membership import Finding

_BUNDLE = "candidate.bundle"


@dataclass(frozen=True)
class VerifiedCandidate:
    tip: str
    staged: ReleasedFile
    base_sha256: str


def _aborted(code: str, detail: str) -> DevelopmentAborted:
    return DevelopmentAborted(Finding(code, _BUNDLE, detail))


def validate_candidate(
    run: RunPaths, source: SourceBase, workspace: PreparedWorkspace, scratch_fd: int, *, limits: Limits,
) -> VerifiedCandidate:
    try:
        staged = release_file(scratch_fd, "outputs", _BUNDLE, run.run_dir / ".candidate-staged.bundle",
                              max_bytes=limits.candidate_bytes)
    except ReleaseFileMissing as caught:
        raise _aborted("development-bundle-missing", f"{caught}; write the declared output and rerun") from caught
    except ReleaseFileRefused as caught:
        raise _aborted("development-bundle-refused", f"{caught}; produce one eligible bounded file") from caught
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
