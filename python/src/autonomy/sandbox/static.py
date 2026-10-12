"""The static bind check (envelope design §7, decision 8): no bind source may be,
contain, or lie inside a denied path, by real path or by (st_dev, st_ino) ancestry,
so a symlinked or bind-mounted alias of a corpus is caught before anything runs."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from autonomy.sandbox.spec import SandboxSpec


class SandboxUnproven(Exception):
    """The sandbox could not be proven: the run is `unwired` and the actor never starts."""

    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(f"{code}: {path}: {message}")
        self.code = code
        self.path = path


def _identity(path: Path) -> tuple[int, int]:
    info = os.stat(path)
    return (info.st_dev, info.st_ino)


def _ancestry(path: Path) -> set[tuple[int, int]]:
    """The (st_dev, st_ino) of a resolved path and of each of its ancestors."""
    return {_identity(p) for p in (path, *path.parents)}


def _target(path: Path) -> tuple[Path, tuple[int, int] | None, set[tuple[int, int]]]:
    """A denied path for comparison. One that does not exist yet (an unconfigured
    store root) still takes part by path; only the inode comparisons need it to
    exist. One that exists but cannot be stat'ed is refused, never downgraded to a
    path-only comparison that a bind-mount alias would pass."""
    real = path.resolve(strict=False)
    try:
        return real, _identity(real), _ancestry(real)
    except (FileNotFoundError, NotADirectoryError):
        return real, None, set()
    except OSError as caught:
        raise SandboxUnproven("denied-unreadable", str(path), f"a denied path must be stat-able: {caught}") from caught


def check_binds(spec: SandboxSpec, denied: Iterable[Path]) -> None:
    targets = [_target(path) for path in denied]
    for source in spec.bind_sources():
        try:
            real = source.resolve(strict=True)
            identity, ancestry = _identity(real), _ancestry(real)
        except FileNotFoundError as caught:
            raise SandboxUnproven("bind-missing", str(source), f"a bind source must exist: {caught}") from caught
        except (OSError, RuntimeError) as caught:
            raise SandboxUnproven("bind-unreadable", str(source), f"a bind source must resolve: {caught}") from caught
        for target, target_identity, target_ancestry in targets:
            overlaps = (
                real == target
                or real.is_relative_to(target)
                or target.is_relative_to(real)
                or (target_identity is not None and target_identity in ancestry)
                or identity in target_ancestry
            )
            if overlaps:
                raise SandboxUnproven(
                    "bind-overlaps-denied", str(source), f"is, contains, or lies inside the denied path {target}"
                )
