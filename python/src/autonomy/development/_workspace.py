"""Prepare an independent Git workspace from one pinned local source."""

from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from autonomy.analyst.walk import mount_points, walk
from autonomy.baseline import publish_bytes
from autonomy.development._git import GitFailed, run_worker
from autonomy.development._records import BASE_REF, REF, DevelopmentAborted, RunPaths, publish_json
from autonomy.egress.route import all_egress_denied
from autonomy.membership import Finding
from autonomy.run import RunRefused
from autonomy.sandbox.bwrap import probe
from autonomy.sandbox.spec import IN_SANDBOX_OUTPUTS, SYSTEM_RO, SandboxSpec
from autonomy.sandbox.static import SandboxUnproven, check_binds

_MIB = 1 << 20


@dataclass(frozen=True)
class Limits:
    base_bytes: int = 64 * _MIB
    candidate_bytes: int = 32 * _MIB
    actor_fsize_bytes: int = 64 * _MIB
    prepare_seconds: int = 60
    receiver_seconds: int = 30
    receiver_memory_bytes: int = 512 * _MIB
    receiver_storage_bytes: int = 256 * _MIB


@dataclass(frozen=True)
class SourceBase:
    repository: Path
    objects: Path
    oid: str
    object_format: str
    prepare_until: float


@dataclass(frozen=True)
class PreparedWorkspace:
    spec: SandboxSpec
    base_sha256: str
    denied: tuple[Path, ...]
    walk_sha256: str


def _objects(repository: Path) -> Path:
    dotgit = repository / ".git"
    if dotgit.exists() or dotgit.is_symlink():
        if dotgit.is_symlink() or not dotgit.is_dir():
            raise ValueError("the source needs an ordinary local Git directory")
        admin = dotgit
    else:
        admin = repository
    objects = admin / "objects"
    if not (admin / "HEAD").is_file() or objects.is_symlink() or not objects.is_dir():
        raise ValueError("local Git object storage is unavailable")
    return objects


def _object_binds(objects: Path) -> tuple[tuple[Path, str], ...]:
    # Construct the object view from the pack and loose-object directories.
    # Git's source objects/info (including alternates) never enters it.
    binds = []
    for path in sorted(objects.iterdir()):
        if path.name != "pack" and not re.fullmatch(r"[0-9a-f]{2}", path.name):
            continue
        if path.is_symlink() or not path.is_dir():
            raise ValueError("Git object storage contains an unsupported directory")
        with os.scandir(path) as entries:
            if any(not entry.is_file(follow_symlinks=False) or entry.name.endswith(".promisor") for entry in entries):
                raise ValueError("Git object storage contains an unsupported entry")
        binds.append((path, f"/source-objects/{path.name}"))
    return tuple(binds)


def admit_source(repository: Path, oid: str, *, limits: Limits) -> SourceBase:
    deadline = time.monotonic() + limits.prepare_seconds
    try:
        repository = repository.resolve(strict=True)
        objects = _objects(repository)
        binds = _object_binds(objects)
    except (OSError, ValueError) as caught:
        raise RunRefused(
            "development-repository-invalid", f"cannot use the source repository: {caught}; select an approved local repository",
        ) from caught
    if not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", oid):
        raise RunRefused("development-base-invalid", "resolve and supply the full approved commit ID")
    object_format = "sha1" if len(oid) == 40 else "sha256"
    if not binds:
        raise RunRefused("development-base-invalid", "base is absent from the local object store; supply the approved commit")
    try:
        run_worker("admit", (object_format, oid), until=deadline, memory_bytes=limits.receiver_memory_bytes,
                   storage_bytes=limits.receiver_storage_bytes, read_only=binds)
    except GitFailed as caught:
        if caught.input_invalid:
            raise RunRefused("development-base-invalid", f"{caught}; supply the full approved commit ID") from caught
        raise SandboxUnproven("development-launch-unavailable", str(repository), str(caught)) from caught
    return SourceBase(repository, objects, oid, object_format, deadline)


def prepare_workspace(run: RunPaths, source: SourceBase, *, config: Path, limits: Limits) -> PreparedWorkspace:
    try:
        run_worker(
            "prepare", (source.object_format, source.oid, str(limits.base_bytes), BASE_REF, REF),
            until=source.prepare_until, memory_bytes=limits.receiver_memory_bytes,
            storage_bytes=limits.receiver_storage_bytes, read_only=_object_binds(source.objects), export=run.scratch,
        )
        staged = run.scratch / "base.bundle"
        with staged.open("rb") as stream:
            data = stream.read(limits.base_bytes + 1)
        if len(data) > limits.base_bytes:
            raise ValueError("base bundle exceeds the recorded byte limit")
        publish_bytes(run.run_dir / "base.bundle", data)
        staged.unlink()
        for name in ("home", "agent", "sessions", "outputs"):
            (run.scratch / name).mkdir(mode=0o700)
    except (GitFailed, SandboxUnproven, OSError, ValueError) as caught:
        raise DevelopmentAborted(Finding(
            "development-workspace-unproven", str(source.repository), f"{caught}; correct the source or host and rerun",
        )) from caught

    runtime = Path("/run/user") / str(os.getuid())
    inode_denied = tuple(dict.fromkeys((source.repository, run.run_dir.parent.parent, *all_egress_denied(config))))
    denied = (*inode_denied, runtime)
    spec = SandboxSpec(
        scratch=run.scratch, chdir=run.scratch / "repo", outputs_link=True, disable_nested_userns=True,
        env={
            "HOME": str(run.scratch / "home"),
            "LC_ALL": "C",
            "VERIFIABLY_DEVELOPMENT_BASE": source.oid,
            "VERIFIABLY_DEVELOPMENT_REF": REF,
            "VERIFIABLY_DEVELOPMENT_BUNDLE": str(IN_SANDBOX_OUTPUTS / "candidate.bundle"),
        },
    )
    try:
        check_binds(spec, denied)
        # The runtime root can contain unlistable systemd sentinel directories.
        # An inode on another filesystem cannot alias an admitted file.
        try:
            runtime_devices = {runtime.stat().st_dev}
        except FileNotFoundError:
            runtime_devices = set()
        runtime_devices.update(p.stat().st_dev for p in mount_points() if p != runtime and p.is_relative_to(runtime))
        admitted_devices = {path.stat().st_dev for path in (run.scratch, *SYSTEM_RO)}
        if runtime_devices & admitted_devices:
            inode_denied = denied
        report = walk((run.scratch,), SYSTEM_RO, inode_denied, until=source.prepare_until)
        remaining = source.prepare_until - time.monotonic()
        if remaining <= 0:
            raise GitFailed("workspace preparation passed its deadline")
        probe(spec, denied, timeout=remaining)
        walk_digest = publish_json(run.run_dir / "walk.json", report.to_json())
    except (SandboxUnproven, GitFailed, OSError) as caught:
        raise DevelopmentAborted(Finding(
            "development-sandbox-unproven", str(run.scratch), f"{caught}; correct the named guard and rerun",
        )) from caught
    return PreparedWorkspace(spec, hashlib.sha256(data).hexdigest(), denied, walk_digest)
