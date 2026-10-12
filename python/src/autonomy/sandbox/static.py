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


def check_binds(spec: SandboxSpec, denied: Iterable[Path]) -> None:
    targets: list[tuple[Path, tuple[int, int], set[tuple[int, int]]]] = []
    for path in denied:
        real = path.resolve()
        if real.exists():
            targets.append((real, _identity(real), _ancestry(real)))
    for source in spec.bind_sources():
        try:
            real = source.resolve(strict=True)
        except (FileNotFoundError, RuntimeError) as caught:
            raise SandboxUnproven("bind-missing", str(source), f"a bind source must exist: {caught}") from caught
        identity, ancestry = _identity(real), _ancestry(real)
        for target, target_identity, target_ancestry in targets:
            overlaps = (
                real == target
                or real.is_relative_to(target)
                or target.is_relative_to(real)
                or target_identity in ancestry
                or identity in target_ancestry
            )
            if overlaps:
                raise SandboxUnproven(
                    "bind-overlaps-denied", str(source), f"is, contains, or lies inside the denied path {target}"
                )
