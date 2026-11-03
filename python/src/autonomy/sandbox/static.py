"""The static bind check (envelope design §7, decision 8): no bind source may be,
contain, or lie inside a denied path, by real path or by (st_dev, st_ino) ancestry,
so a symlinked or bind-mounted alias of a corpus is caught before anything runs."""

from __future__ import annotations

import os
import posixpath
from collections.abc import Iterable
from pathlib import Path

from autonomy.sandbox.spec import SYSTEM_LINKS, SandboxSpec


class SandboxUnproven(Exception):
    """The sandbox could not be proven: the run is `unwired` and the actor never starts."""

    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(f"{code}: {path}: {message}")
        self.code = code
        self.path = path


def system_symlinks(root: Path = Path("/")) -> tuple[tuple[str, str], ...]:
    """The host's merged-/usr links as `(target, link)` pairs, to recreate inside the
    sandbox. They mirror the host because the targets differ by distribution (Arch:
    `/lib64 -> usr/lib`; Debian and Ubuntu: `usr/lib64`), and a wrong one leaves every
    binary without its ELF interpreter. Only `/usr` is bound, so each link must resolve
    under it; a link the host lacks is left out."""
    links: list[tuple[str, str]] = []
    for link in SYSTEM_LINKS:
        host = root / link.lstrip("/")
        if not os.path.lexists(host):
            continue
        if not host.is_symlink():
            raise SandboxUnproven("layout-unsupported", link, "not a merged-/usr symlink on this host")
        target = os.readlink(host)
        if not posixpath.normpath(posixpath.join("/", target)).startswith("/usr/"):
            raise SandboxUnproven("layout-unsupported", link, f"points at {target}, outside the bound /usr")
        links.append((target, link))
    return tuple(links)


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


def check_sources(sources: Iterable[Path], denied: Iterable[Path], *, exempt: Iterable[Path] = ()) -> None:
    """Each source against each denied path. A source whose real path is exactly an
    exempt path is skipped: the proxy's credential and `ca_file` are bound as single
    files under a denied ancestor such as `<config>` (decision 13). The exemption is
    exact, so their directories are still refused."""
    targets = [_target(path) for path in denied]
    skip = {path.resolve(strict=False) for path in exempt if not path.is_symlink()}
    for source in sources:
        try:
            real = source.resolve(strict=True)
            identity, ancestry = _identity(real), _ancestry(real)
        except FileNotFoundError as caught:
            raise SandboxUnproven("bind-missing", str(source), f"a bind source must exist: {caught}") from caught
        except (OSError, RuntimeError) as caught:
            raise SandboxUnproven("bind-unreadable", str(source), f"a bind source must resolve: {caught}") from caught
        if real in skip and not source.is_symlink():
            continue
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


def check_recreated_links(links: Iterable[Path], denied: Iterable[Path]) -> None:
    """Each recreated host symlink `L` against each denied path (decision 14): `L` may
    not equal, contain, or lie inside a denied path, and `L.parent` may not lie inside a
    denied ancestor. `L.parent` is not itself bound into the sandbox (`bwrap` creates an
    empty directory on the tmpfs to hold `L`), so unrelated denied siblings under
    `L.parent` are not exposed and are not refused."""
    denied_list = tuple(denied)
    targets = [(_target(path), Path(os.path.abspath(path))) for path in denied_list]
    for link in links:
        try:
            parent_real = link.parent.resolve(strict=True)
            parent_ancestry = _ancestry(parent_real)
        except FileNotFoundError as caught:
            raise SandboxUnproven("bind-missing", str(link), f"recreated link parent must exist: {caught}") from caught
        except (OSError, RuntimeError) as caught:
            raise SandboxUnproven("bind-unreadable", str(link), f"recreated link parent must resolve: {caught}") from caught
        lexical = parent_real / link.name
        for (target, target_identity, _target_ancestry), raw_target in targets:
            overlaps = (
                lexical == target
                or lexical.is_relative_to(target)
                or target.is_relative_to(lexical)
                or lexical == raw_target
                or lexical.is_relative_to(raw_target)
                or raw_target.is_relative_to(lexical)
                or (target_identity is not None and target_identity in parent_ancestry)
            )
            if overlaps:
                raise SandboxUnproven(
                    "bind-overlaps-denied", str(link), f"is, contains, or lies inside the denied path {target}"
                )


def check_binds(spec: SandboxSpec, denied: Iterable[Path]) -> None:
    denied_tuple = tuple(denied)
    check_sources(spec.bind_sources(), denied_tuple)
    check_recreated_links((link for _, link in spec.symlinks), denied_tuple)
