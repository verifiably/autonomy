"""The output release (docs/envelope.md). Scratch is where the
analyst wrote freely; a symlink it planted dangles inside the namespace and resolves on
the host. Outputs therefore cross to the host through this one walk by descriptor,
which follows no link at any component: every entry is classified by `lstat` relative
to its parent's descriptor, only regular files with one link and directories are
opened (`O_NOFOLLOW | O_NONBLOCK`, so a swapped-in symlink is refused by the kernel and
a FIFO cannot stall), and bytes are copied with one read/write loop that feeds the
hash. `openat2` would say the same thing and is not in the standard library.

The release directory check treats `<cache>` as the stand-in for scratch, which does not
exist yet at step 1; that is stricter than the spec's "outside scratch" (the
implementer's call)."""

from __future__ import annotations

import errno
import hashlib
import os
import secrets
import stat
from collections import Counter
from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from autonomy.analyst.toolchain import AnalystRefused
from autonomy.baseline import fsync_dir, write_all

__all__ = [
    "RETAINED_DEPTH", "ReleaseFileMissing", "ReleaseFileRefused", "ReleaseReport", "ReleasedFile", "RetainedTally",
    "check_release_dir", "release", "release_file", "retain",
]

RETAINED_DEPTH = 128
"""Directories below the retained root. The walk holds a path and two descriptors per
level, and the actor chooses the depth."""

_CHUNK = 1 << 20
_OPEN = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_CREATE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


def check_release_dir(path: Path, *, forbidden: Iterable[Path]) -> Path:
    """The caller's release directory: existing, a directory, not a symlink, empty, and
    neither inside nor around any forbidden path (the inputs, the cache, the denied set,
    which need not exist: a release there would create a denied path)."""

    def refused(why: str) -> AnalystRefused:
        return AnalystRefused("release-unusable", f"{path}: {why}")

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise refused("does not exist") from None
    except OSError as caught:
        raise refused(str(caught)) from None
    if stat.S_ISLNK(info.st_mode):
        raise refused("a symlink")
    if not stat.S_ISDIR(info.st_mode):
        raise refused("not a directory")
    real = path.resolve(strict=True)
    with os.scandir(real) as entries:
        if any(True for _ in entries):
            raise refused("not empty")
    for other in forbidden:
        target = Path(other).resolve(strict=False)
        if real == target or real.is_relative_to(target) or target.is_relative_to(real):
            raise refused(f"is, contains or lies inside {target}")
    return real


class _Record(Protocol):
    """What the walk tells about each entry, and the bytes and depth it may still copy."""

    remaining: int | None
    max_depth: int | None

    def release(self, path: str, size: int, sha256: str) -> None: ...

    def refuse(self, path: str, reason: str, detail: str | None = None) -> None: ...


@dataclass
class ReleaseReport:
    released: list[dict] = field(default_factory=list)
    refused: list[dict] = field(default_factory=list)
    remaining: None = None
    max_depth: None = None

    def release(self, path: str, size: int, sha256: str) -> None:
        self.released.append({"path": path, "size": size, "sha256": sha256})

    def refuse(self, path: str, reason: str, detail: str | None = None) -> None:
        entry = {"path": path, "reason": reason}
        if detail:
            entry["detail"] = detail
        self.refused.append(entry)

    def to_json(self) -> dict:
        return {"released": list(self.released), "refused": list(self.refused)}


@dataclass
class RetainedTally:
    """Counts only. The tree is the actor's, and deep paths times many entries would make
    a per-entry report far larger than the tree. A refusal counts under its reason, with
    the system's error where there is one."""

    remaining: int
    max_depth: int = RETAINED_DEPTH
    files: int = 0
    bytes: int = 0
    refused: Counter[str] = field(default_factory=Counter)

    def release(self, path: str, size: int, sha256: str) -> None:
        self.files += 1
        self.bytes += size
        self.remaining -= size

    def refuse(self, path: str, reason: str, detail: str | None = None) -> None:
        self.refused[f"{reason}: {detail}" if detail else reason] += 1

    def to_json(self) -> dict:
        return {"files": self.files, "bytes": self.bytes, "refused": dict(sorted(self.refused.items()))}


def _classify(info: os.stat_result) -> str | None:
    """The refusal reason for an entry, or None for one the release may take."""
    mode = info.st_mode
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
        return "device"
    if stat.S_ISREG(mode):
        return "hardlinked" if info.st_nlink > 1 else None
    if stat.S_ISDIR(mode):
        return None
    return "unopenable"


def _copy(src_fd: int, dest_fd: int, *, max_bytes: int | None = None) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while chunk := os.read(src_fd, _CHUNK if max_bytes is None else min(_CHUNK, max_bytes - size + 1)):
        size += len(chunk)
        if max_bytes is not None and size > max_bytes:
            raise ReleaseFileRefused("output stream exceeds the byte limit")
        write_all(dest_fd, chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def _names(src_fd: int, where: str, report: _Record) -> list[str]:
    """A directory's entries, sorted descending so `pop()` yields them in order; a
    directory that cannot be listed (descriptor exhaustion included) is one refusal."""
    try:
        with os.scandir(src_fd) as entries:
            return sorted((entry.name for entry in entries), reverse=True)
    except OSError as caught:
        report.refuse(where.rstrip("/"), "unopenable", caught.strerror)
        return []


def _release_dir(src_fd: int, dest_fd: int, prefix: str, report: _Record) -> None:
    """Walk `src_fd` into `dest_fd` depth-first with one frame per open directory pair and
    that directory's pending names, so open descriptors grow with the tree's depth and
    never with its width (an analyst can make either). A frame's two descriptors are
    closed when its names run out; the caller's pair is not owned. Past the descriptor
    budget, opens fail with EMFILE and become refusals, never an exception."""
    frames: list[list] = [[src_fd, dest_fd, prefix, _names(src_fd, prefix, report), False]]
    try:
        while frames:
            src, dest, where, names, owned = frames[-1]
            if not names:
                frames.pop()
                if owned:
                    os.close(src)
                    os.close(dest)
                continue
            child = _release_entry(src, dest, where, names.pop(), report, len(frames))
            if child is not None:
                child_src, child_dest, child_where = child
                frames.append([child_src, child_dest, child_where, _names(child_src, child_where, report), True])
    finally:
        for src, dest, _, _, owned in frames:
            if owned:
                os.close(src)
                os.close(dest)


def _release_entry(
    src_fd: int, dest_fd: int, prefix: str, name: str, report: _Record, depth: int,
) -> tuple[int, int, str] | None:
    """One entry: refused, copied, or (for a directory) created at the destination and
    returned as an open pair to descend into."""
    relative = f"{prefix}{name}"

    def refuse(reason: str, detail: str | None = None) -> None:
        report.refuse(relative, reason, detail)

    try:
        info = os.stat(name, dir_fd=src_fd, follow_symlinks=False)
    except OSError as caught:
        refuse("unopenable", caught.strerror)
        return None
    reason = _classify(info)
    if reason is not None:
        refuse(reason)
        return None
    directory = stat.S_ISDIR(info.st_mode)
    if not directory and report.remaining is not None and info.st_size > report.remaining:
        refuse("over-bound")
        return None
    if directory and report.max_depth is not None and depth > report.max_depth:
        refuse("too-deep")
        return None
    try:
        fd = os.open(name, _OPEN | (os.O_DIRECTORY if directory else 0), dir_fd=src_fd)
    except OSError as caught:
        refuse("symlink" if caught.errno in (errno.ELOOP, errno.ENOTDIR) else "unopenable", caught.strerror)
        return None
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino) or _classify(opened) is not None:
            refuse("symlink", "swapped between stat and open")
            return None
        if directory:
            try:
                os.mkdir(name, 0o700, dir_fd=dest_fd)
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dest_fd)
            except FileExistsError:
                refuse("collision")
                return None
            except OSError as caught:
                refuse("unopenable", caught.strerror)
                return None
            pair = (fd, child, relative + "/")
            fd = -1  # owned by the frame now
            return pair
        try:
            out = os.open(name, _CREATE, 0o600, dir_fd=dest_fd)
        except FileExistsError:
            refuse("collision")
            return None
        except OSError as caught:
            refuse("unopenable", caught.strerror)
            return None
        try:
            size, sha256 = _copy(fd, out, max_bytes=report.remaining)
        except (OSError, ReleaseFileRefused) as caught:
            refuse("unopenable", caught.strerror if isinstance(caught, OSError) else str(caught))
            try:
                os.unlink(name, dir_fd=dest_fd)  # a partial copy is not a release
            except OSError:
                pass
            return None
        finally:
            os.close(out)
        report.release(relative, size, sha256)
        return None
    finally:
        if fd >= 0:
            os.close(fd)


def release(outputs: Path, destination: Path) -> ReleaseReport:
    """Copy `outputs` (the scratch output directory the launcher made) into
    `destination` (checked by `check_release_dir`), by descriptor, following no link."""
    report = ReleaseReport()
    try:
        src = os.open(outputs, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as caught:  # the analyst replaced, removed or locked outputs/ itself
        report.refuse("", "outputs-unusable", f"{outputs}: {caught.strerror}")
        return report
    try:
        dest = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            _release_dir(src, dest, "", report)
        finally:
            os.close(dest)
    finally:
        os.close(src)
    return report


def retain(source_fd: int, destination: Path, *, max_bytes: int) -> RetainedTally:
    """Copy an ended actor's tree into `destination` for inspection: the release walk, with
    at most `max_bytes` of content, so a sparse file cannot grow on its way to disk, and
    at most `RETAINED_DEPTH` directories down."""
    tally = RetainedTally(max_bytes)
    dest = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        _release_dir(source_fd, dest, "", tally)
    finally:
        os.close(dest)
    return tally


class ReleaseFileMissing(Exception):
    """The declared output was absent."""


class ReleaseFileRefused(Exception):
    """The declared output could not be transferred intact within the byte limit."""


@dataclass(frozen=True)
class ReleasedFile:
    path: Path
    size: int
    sha256: str


def _file_identity(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def release_file(scratch_fd: int, outputs: str, name: str, destination: Path, *, max_bytes: int) -> ReleasedFile:
    """Transfer one bounded regular file from the scratch directory's `outputs` to a new
    protected staging name."""
    if Path(name).name != name or name in ("", ".", "..") or max_bytes <= 0:
        raise ValueError("release requires a single entry name and a positive byte limit")
    try:
        with ExitStack() as close:
            try:
                outputs_fd = os.open(outputs, _OPEN | os.O_DIRECTORY, dir_fd=scratch_fd)
                close.callback(os.close, outputs_fd)
                before = os.stat(name, dir_fd=outputs_fd, follow_symlinks=False)
            except FileNotFoundError as caught:
                raise ReleaseFileMissing(f"{outputs}/{name} is absent") from caught
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ReleaseFileRefused("the output must be a single-link regular file")
            if before.st_size > max_bytes:
                raise ReleaseFileRefused(f"output exceeds the {max_bytes} byte limit")
            source_fd = os.open(name, _OPEN, dir_fd=outputs_fd)
            close.callback(os.close, source_fd)
            identity = _file_identity(before)
            if _file_identity(os.fstat(source_fd)) != identity:
                raise ReleaseFileRefused("output changed before opening")
            temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(8)}.tmp")
            dest_fd = os.open(temporary, _CREATE, 0o600)
            try:
                try:
                    size, digest = _copy(source_fd, dest_fd, max_bytes=max_bytes)
                    named = os.stat(name, dir_fd=outputs_fd, follow_symlinks=False)
                    current_dir = os.stat(outputs, dir_fd=scratch_fd, follow_symlinks=False)
                    opened_dir = os.fstat(outputs_fd)
                    if (size != before.st_size or _file_identity(named) != identity
                            or _file_identity(os.fstat(source_fd)) != identity
                            or (current_dir.st_dev, current_dir.st_ino) != (opened_dir.st_dev, opened_dir.st_ino)):
                        raise ReleaseFileRefused("output size or identity changed during transfer")
                    os.fsync(dest_fd)
                finally:
                    os.close(dest_fd)
                os.link(temporary, destination, follow_symlinks=False)
            finally:
                temporary.unlink()
            fsync_dir(destination.parent)
            return ReleasedFile(destination, size, digest)
    except OSError as caught:
        raise ReleaseFileRefused(f"cannot transfer {outputs}/{name}: {caught}") from caught
