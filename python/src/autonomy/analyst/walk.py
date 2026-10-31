"""The pre-launch walk (envelope design decision 14, §7 *The walk*). The static check
compares bind roots; this compares what the roots contain. Three rules over each
admitted tree, with the launcher's own credentials and following no symlink:

- `walk-submount`: no mount below the root. `/proc/self/mountinfo` lists every mount in
  the launcher's namespace, same-filesystem binds included, which an `st_dev` change
  alone would miss; `st_dev` is still compared, as a second signal.
- `walk-hardlink`: no regular file with `st_nlink > 1`, in user-writable trees only.
- `walk-alias`: no entry whose `(st_dev, st_ino)` is one under a denied root.

A directory the user can neither list nor search is skipped (the analyst runs as the
same uid and cannot reach it either); one that can be searched but not listed fails
`walk-unlistable`. Collecting the denied inodes fails `denied-unlistable` on a directory
under a denied root that cannot be listed: that is exactly where an alias would hide."""

from __future__ import annotations

import os
import re
import stat
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from autonomy.sandbox.static import SandboxUnproven

Inode = tuple[int, int]
MOUNTINFO = Path("/proc/self/mountinfo")
_ESCAPE = re.compile(r"\\([0-7]{3})")


def unescape_mountinfo(text: str) -> str:
    """mountinfo escapes space, tab, newline and backslash as `\\040`, `\\011`, `\\012`,
    `\\134`; any three-digit octal escape is decoded the same way."""
    return _ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), text)


def mount_points(mountinfo: Path = MOUNTINFO) -> tuple[Path, ...]:
    """Field 5 of every line: the mount point, unescaped."""
    points: list[Path] = []
    for line in mountinfo.read_text().splitlines():
        fields = line.split(" ")
        if len(fields) > 4:
            points.append(Path(unescape_mountinfo(fields[4])))
    return tuple(points)


def _identity(info: os.stat_result) -> Inode:
    return (info.st_dev, info.st_ino)


def collect_denied_inodes(denied: Iterable[Path]) -> frozenset[Inode]:
    """Every file and directory under each denied path that exists, by `lstat`,
    following no link. A missing path is skipped (it takes part by path in the static
    check). A directory that cannot be listed is refused."""
    inodes: set[Inode] = set()
    for root in denied:
        try:
            info = os.lstat(root)
        except FileNotFoundError:
            continue
        except OSError as caught:
            raise SandboxUnproven("denied-unreadable", str(root), f"a denied path must be stat-able: {caught}") from caught
        inodes.add(_identity(info))
        if not stat.S_ISDIR(info.st_mode):
            continue
        stack = [Path(root)]
        while stack:
            directory = stack.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        inodes.add(_identity(entry.stat(follow_symlinks=False)))
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
            except PermissionError as caught:
                raise SandboxUnproven(
                    "denied-unlistable", str(directory), f"a directory under a denied root must be listable: {caught}"
                ) from caught
    return frozenset(inodes)


@dataclass
class TreeReport:
    root: str
    rules: list[str]
    entries: int = 0
    skipped: list[str] = field(default_factory=list)
    seconds: float = 0.0


@dataclass
class WalkReport:
    trees: list[TreeReport]
    denied_inodes: int
    seconds: float

    def to_json(self) -> dict:
        return {
            "trees": [
                {"root": t.root, "rules": list(t.rules), "entries": t.entries, "skipped": list(t.skipped), "seconds": t.seconds}
                for t in self.trees
            ],
            "denied_inodes": self.denied_inodes,
            "seconds": self.seconds,
        }


def _check_entry(path: str, info: os.stat_result, root_dev: int, denied: frozenset[Inode], hardlinks: bool) -> None:
    if info.st_dev != root_dev:
        raise SandboxUnproven("walk-submount", path, "lies on another filesystem than the tree's root")
    if hardlinks and stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise SandboxUnproven("walk-hardlink", path, f"a regular file with {info.st_nlink} links")
    if _identity(info) in denied:
        raise SandboxUnproven("walk-alias", path, "is the same inode as a path under a denied root")


def walk_tree(root: Path, denied_inodes: frozenset[Inode], *, hardlinks: bool, mounts: tuple[Path, ...]) -> TreeReport:
    """`root` is already a real path. Mount points strictly below it fail before any
    entry is read; the root itself may be a mount point."""
    started = time.monotonic()
    report = TreeReport(str(root), ["submount", "hardlink", "alias"] if hardlinks else ["submount", "alias"])
    for mount in mounts:
        if mount != root and mount.is_relative_to(root):
            raise SandboxUnproven("walk-submount", str(mount), f"a mount point below the admitted tree {root}")
    root_info = os.lstat(root)
    root_dev = root_info.st_dev
    _check_entry(str(root), root_info, root_dev, denied_inodes, hardlinks)
    stack = [str(root)]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    info = entry.stat(follow_symlinks=False)
                    report.entries += 1
                    _check_entry(entry.path, info, root_dev, denied_inodes, hardlinks)
                    if stat.S_ISDIR(info.st_mode):
                        stack.append(entry.path)
        except PermissionError as caught:
            if os.access(directory, os.X_OK):
                raise SandboxUnproven(
                    "walk-unlistable", directory, f"a directory that can be searched but not listed: {caught}"
                ) from caught
            report.skipped.append(directory)
    report.seconds = round(time.monotonic() - started, 3)
    return report


def walk(user_trees: Iterable[Path], system_trees: Iterable[Path], denied: Iterable[Path]) -> WalkReport:
    """The whole pre-launch walk: the hard-link rule for the user-writable trees (the
    inputs, node, pi), the mount and inode rules for every tree."""
    started = time.monotonic()
    denied_inodes = collect_denied_inodes(denied)
    mounts = mount_points()
    trees = [walk_tree(Path(t), denied_inodes, hardlinks=True, mounts=mounts) for t in user_trees]
    trees += [walk_tree(Path(t), denied_inodes, hardlinks=False, mounts=mounts) for t in system_trees]
    return WalkReport(trees, len(denied_inodes), round(time.monotonic() - started, 3))
