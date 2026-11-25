"""Prepare an independent Git workspace from one pinned local source."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from autonomy.analyst.walk import mount_points, walk
from autonomy.baseline import publish_bytes
from autonomy.development._git import GitFailed, PinnedObjectDirectory, SourceViewInvalid, run_worker
from autonomy.development._records import BASE_REF, REF, DevelopmentAborted, RunPaths, publish_json
from autonomy.egress.route import all_egress_denied
from autonomy.membership import Finding
from autonomy.run import RunRefused
from autonomy.sandbox.bwrap import probe
from autonomy.sandbox.spec import IN_SANDBOX_OUTPUTS, SYSTEM_RO, SandboxSpec, Storage
from autonomy.sandbox.static import SandboxUnproven, check_binds

_MIB = 1 << 20
_OPEN_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


@dataclass(frozen=True)
class Limits:
    base_bytes: int = 64 * _MIB
    candidate_bytes: int = 32 * _MIB
    actor_fsize_bytes: int = 64 * _MIB
    actor_storage_bytes: int = 1024 * _MIB
    actor_storage_inodes: int = 128 * 1024
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
    object_identity: tuple[int, int]


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


@dataclass(frozen=True)
class _ObjectView:
    identity: tuple[int, int]
    mounts: tuple[PinnedObjectDirectory, ...]


def _directory_identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _check_inspection_deadline(until: float) -> None:
    if time.monotonic() >= until:
        raise SourceViewInvalid("source inspection exceeded its preparation deadline")


@contextmanager
def _open_objects(path: Path, until: float) -> Iterator[int]:
    # Start from the canonical absolute path and follow no symlink component.
    directory = os.open(path.anchor, _OPEN_DIR)
    try:
        for part in path.parts[1:]:
            _check_inspection_deadline(until)
            next_directory = os.open(part, _OPEN_DIR, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        yield directory
    finally:
        os.close(directory)


@contextmanager
def _object_view(objects: Path, *, until: float, expected: tuple[int, int] | None = None) -> Iterator[_ObjectView]:
    # The object bins remain pinned until the confined worker has checked
    # the mounted inodes. Git never runs against an unverified mount.
    mounts = []
    with _open_objects(objects, until) as root, ExitStack() as held, os.scandir(root) as entries:
        identity = _directory_identity(os.fstat(root))
        if expected is not None and identity != expected:
            raise SourceViewInvalid("source object root changed since admission")
        for entry in entries:
            _check_inspection_deadline(until)
            if entry.name != "pack" and not re.fullmatch(r"[0-9a-f]{2}", entry.name):
                continue
            before = _directory_identity(entry.stat(follow_symlinks=False))
            fd = os.open(entry.name, _OPEN_DIR, dir_fd=root)
            held.callback(os.close, fd)
            opened = _directory_identity(os.fstat(fd))
            if opened != before:
                raise SourceViewInvalid("source object directory changed during inspection")
            destination = f"/source-objects/{entry.name}"
            mounts.append(PinnedObjectDirectory(fd, destination, *opened))
        _check_inspection_deadline(until)
        yield _ObjectView(identity, tuple(mounts))


def admit_source(repository: Path, oid: str, *, limits: Limits) -> SourceBase:
    deadline = time.monotonic() + limits.prepare_seconds
    if not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", oid):
        raise RunRefused("development-base-invalid", "resolve and supply the full approved commit ID")
    object_format = "sha1" if len(oid) == 40 else "sha256"
    try:
        repository = repository.resolve(strict=True)
        objects = _objects(repository)
        with _object_view(objects, until=deadline) as view:
            if not view.mounts:
                raise RunRefused("development-base-invalid", "the base is absent from the local object store")
            run_worker("admit", (object_format, oid), until=deadline, memory_bytes=limits.receiver_memory_bytes,
                       storage_bytes=limits.receiver_storage_bytes, source_mounts=view.mounts)
    except (OSError, ValueError, SourceViewInvalid) as caught:
        raise RunRefused(
            "development-repository-invalid", f"cannot use the source repository: {caught}. Select an approved local repository.",
        ) from caught
    except GitFailed as caught:
        if caught.input_invalid:
            raise RunRefused("development-base-invalid", f"{caught}. Supply the full approved commit ID.") from caught
        raise SandboxUnproven("development-launch-unavailable", str(repository), str(caught)) from caught
    return SourceBase(repository, objects, oid, object_format, deadline, view.identity)


def prepare_workspace(run: RunPaths, source: SourceBase, *, config: Path, limits: Limits) -> PreparedWorkspace:
    try:
        with _object_view(source.objects, until=source.prepare_until, expected=source.object_identity) as view:
            run_worker(
                "prepare", (source.object_format, source.oid, str(limits.base_bytes), BASE_REF, REF),
                until=source.prepare_until, memory_bytes=limits.receiver_memory_bytes,
                storage_bytes=limits.receiver_storage_bytes, source_mounts=view.mounts,
                export=run.scratch,
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
    cgroups = Path("/sys/fs/cgroup")
    inode_denied = tuple(dict.fromkeys((source.repository, run.run_dir.parent.parent, *all_egress_denied(config))))
    denied = (*inode_denied, runtime, cgroups)
    spec = SandboxSpec(
        scratch=run.scratch, chdir=run.scratch / "repo", outputs_link=True, disable_nested_userns=True,
        storage=Storage(limits.actor_storage_bytes, limits.actor_storage_inodes),
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
            inode_denied = (*inode_denied, runtime)
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


def seed_scratch(prepared: Path, scratch_fd: int) -> None:
    """Move the prepared tree into the actor's bounded scratch while its gate is held."""
    for entry in sorted(prepared.iterdir()):
        shutil.copytree(entry, f"/proc/self/fd/{scratch_fd}/{entry.name}", symlinks=True, dirs_exist_ok=True)
        shutil.rmtree(entry)
