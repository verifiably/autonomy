"""The output release (envelope design decision 14, *The release*). Scratch is where the
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
import stat
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from autonomy.analyst.toolchain import AnalystRefused

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


@dataclass
class ReleaseReport:
    released: list[dict] = field(default_factory=list)
    refused: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"released": list(self.released), "refused": list(self.refused)}


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


def _copy(src_fd: int, dest_fd: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while chunk := os.read(src_fd, _CHUNK):
        view = memoryview(chunk)
        while view:
            view = view[os.write(dest_fd, view):]
        digest.update(chunk)
        size += len(chunk)
    return size, digest.hexdigest()


def _release_dir(src_fd: int, dest_fd: int, prefix: str, report: ReleaseReport) -> None:
    with os.scandir(src_fd) as entries:
        names = [entry.name for entry in entries]
    for name in sorted(names):
        relative = f"{prefix}{name}"
        try:
            info = os.stat(name, dir_fd=src_fd, follow_symlinks=False)
        except OSError as caught:
            report.refused.append({"path": relative, "reason": "unopenable", "detail": caught.strerror})
            continue
        reason = _classify(info)
        if reason is not None:
            report.refused.append({"path": relative, "reason": reason})
            continue
        directory = stat.S_ISDIR(info.st_mode)
        try:
            fd = os.open(name, _OPEN | (os.O_DIRECTORY if directory else 0), dir_fd=src_fd)
        except OSError as caught:
            report.refused.append(
                {"path": relative, "reason": "symlink" if caught.errno in (errno.ELOOP, errno.ENOTDIR) else "unopenable",
                 "detail": caught.strerror}
            )
            continue
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino) or _classify(opened) is not None:
                report.refused.append({"path": relative, "reason": "symlink", "detail": "swapped between stat and open"})
                continue
            if directory:
                try:
                    os.mkdir(name, 0o700, dir_fd=dest_fd)
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dest_fd)
                except FileExistsError:
                    report.refused.append({"path": relative, "reason": "collision"})
                    continue
                try:
                    _release_dir(fd, child, relative + "/", report)
                finally:
                    os.close(child)
                continue
            try:
                out = os.open(name, _CREATE, 0o600, dir_fd=dest_fd)
            except FileExistsError:
                report.refused.append({"path": relative, "reason": "collision"})
                continue
            try:
                size, sha256 = _copy(fd, out)
            finally:
                os.close(out)
            report.released.append({"path": relative, "size": size, "sha256": sha256})
        finally:
            os.close(fd)


def release(outputs: Path, destination: Path) -> ReleaseReport:
    """Copy `outputs` (the scratch output directory the launcher made) into
    `destination` (checked by `check_release_dir`), by descriptor, following no link."""
    report = ReleaseReport()
    src = os.open(outputs, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        dest = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            _release_dir(src, dest, "", report)
        finally:
            os.close(dest)
    finally:
        os.close(src)
    return report
