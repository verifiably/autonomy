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

import hashlib
import json
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


@dataclass(frozen=True)
class InputDigest:
    path: str
    kind: str
    sha256: str
    files: int
    bytes: int

    def to_json(self) -> dict[str, object]:
        return {
            "path": self.path,
            "kind": self.kind,
            "sha256": self.sha256,
            "files": self.files,
            "bytes": self.bytes,
        }


@dataclass
class TreeReport:
    root: str
    rules: list[str]
    entries: int = 0
    skipped: list[str] = field(default_factory=list)
    seconds: float = 0.0
    digest: InputDigest | None = None


@dataclass
class WalkReport:
    trees: list[TreeReport]
    denied_inodes: int
    seconds: float
    inputs: list[InputDigest] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "trees": [
                {"root": t.root, "rules": list(t.rules), "entries": t.entries, "skipped": list(t.skipped), "seconds": t.seconds}
                for t in self.trees
            ],
            "denied_inodes": self.denied_inodes,
            "seconds": self.seconds,
            **({"inputs": [i.to_json() for i in self.inputs]} if self.inputs else {}),
        }


def _check_entry(path: str, info: os.stat_result, root_dev: int, denied: frozenset[Inode], hardlinks: bool) -> None:
    if info.st_dev != root_dev:
        raise SandboxUnproven("walk-submount", path, "lies on another filesystem than the tree's root")
    if hardlinks and stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise SandboxUnproven("walk-hardlink", path, f"a regular file with {info.st_nlink} links")
    if _identity(info) in denied:
        raise SandboxUnproven("walk-alias", path, "is the same inode as a path under a denied root")


def _hash_regular_file(path: str, expected: os.stat_result) -> tuple[str, int]:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as caught:
        raise SandboxUnproven("walk-special", path, f"cannot open regular file without following links: {caught}") from caught
    try:
        f_info = os.fstat(fd)
        if not stat.S_ISREG(f_info.st_mode) or _identity(f_info) != _identity(expected):
            raise SandboxUnproven("walk-special", path, "declared input entry changed inode or file mode before hashing")
        hasher = hashlib.sha256()
        total = 0
        while chunk := os.read(fd, 65536):
            hasher.update(chunk)
            total += len(chunk)
        return hasher.hexdigest(), total
    finally:
        os.close(fd)


def walk_tree(
    root: Path, denied_inodes: frozenset[Inode], *, hardlinks: bool, mounts: tuple[Path, ...], digest: bool = False
) -> TreeReport:
    """`root` is already a real path. Mount points strictly below a directory root fail
    before any entry is read; a regular-file root that is itself a mount point fails."""
    started = time.monotonic()
    report = TreeReport(str(root), ["submount", "hardlink", "alias"] if hardlinks else ["submount", "alias"])
    root_info = os.lstat(root)
    root_dev = root_info.st_dev

    if stat.S_ISREG(root_info.st_mode):
        for mount in mounts:
            if mount == root:
                raise SandboxUnproven("walk-submount", str(root), f"a mount point on the regular-file input {root}")
        _check_entry(str(root), root_info, root_dev, denied_inodes, hardlinks)
        report.entries = 1
        if digest:
            sha256_hex, size = _hash_regular_file(str(root), root_info)
            report.digest = InputDigest(str(root), "file", sha256_hex, 1, size)
        report.seconds = round(time.monotonic() - started, 3)
        return report

    if digest and not stat.S_ISDIR(root_info.st_mode):
        raise SandboxUnproven("walk-special", str(root), "declared input is neither a regular file nor a directory")

    for mount in mounts:
        if mount != root and mount.is_relative_to(root):
            raise SandboxUnproven("walk-submount", str(mount), f"a mount point below the admitted tree {root}")
    _check_entry(str(root), root_info, root_dev, denied_inodes, hardlinks)
    manifest: list[dict[str, object]] = []
    file_count = 0
    total_bytes = 0
    stack = [str(root)]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                if digest and directory != str(root):
                    manifest.append({"kind": "dir", "path": Path(directory).relative_to(root).as_posix()})
                for entry in entries:
                    info = entry.stat(follow_symlinks=False)
                    report.entries += 1
                    _check_entry(entry.path, info, root_dev, denied_inodes, hardlinks)
                    if stat.S_ISDIR(info.st_mode):
                        stack.append(entry.path)
                    elif digest:
                        rel = Path(entry.path).relative_to(root).as_posix()
                        if stat.S_ISREG(info.st_mode):
                            file_sha, size = _hash_regular_file(entry.path, info)
                            manifest.append({"bytes": size, "kind": "file", "path": rel, "sha256": file_sha})
                            file_count += 1
                            total_bytes += size
                        elif stat.S_ISLNK(info.st_mode):
                            manifest.append({"kind": "symlink", "path": rel, "target": os.readlink(entry.path)})
                        else:
                            raise SandboxUnproven(
                                "walk-special",
                                entry.path,
                                "declared input holds a non-regular, non-directory, non-symlink entry",
                            )
        except PermissionError as caught:
            if os.access(directory, os.X_OK):
                raise SandboxUnproven(
                    "walk-unlistable", directory, f"a directory that can be searched but not listed: {caught}"
                ) from caught
            report.skipped.append(directory)
            if digest and directory != str(root):
                manifest.append(
                    {"kind": "dir", "path": Path(directory).relative_to(root).as_posix(), "skipped": True}
                )
    if digest:
        manifest.sort(key=lambda item: str(item["path"]))
        tree_sha = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        report.digest = InputDigest(str(root), "directory", tree_sha, file_count, total_bytes)
    report.seconds = round(time.monotonic() - started, 3)
    return report


def walk(
    user_trees: Iterable[Path],
    system_trees: Iterable[Path],
    denied: Iterable[Path],
    *,
    digest_inputs: Iterable[Path] = (),
) -> WalkReport:
    """The whole pre-launch walk: the hard-link rule for the user-writable trees (the
    inputs, node, pi), the mount and inode rules for every tree."""
    started = time.monotonic()
    denied_inodes = collect_denied_inodes(denied)
    mounts = mount_points()
    digest_set = {Path(p) for p in digest_inputs}
    trees = [
        walk_tree(Path(t), denied_inodes, hardlinks=True, mounts=mounts, digest=(Path(t) in digest_set))
        for t in user_trees
    ]
    trees += [walk_tree(Path(t), denied_inodes, hardlinks=False, mounts=mounts) for t in system_trees]
    inputs = [t.digest for t in trees if t.digest is not None]
    return WalkReport(trees, len(denied_inodes), round(time.monotonic() - started, 3), inputs=inputs)
