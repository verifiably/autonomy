"""The sandbox spec is data (docs/envelope.md): what is bound, where, and how."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType

__all__ = [
    "IN_SANDBOX_OUTPUTS", "IN_SANDBOX_SOCKET", "IN_SANDBOX_TOKEN", "SYSTEM_LINKS", "SYSTEM_RO", "SandboxSpec", "Storage",
]

SYSTEM_RO: tuple[Path, ...] = (Path("/usr"), Path("/etc"))
# The merged-/usr symlinks, recreated inside the sandbox rather than bound. Their
# targets are the host's (static.system_symlinks): they differ by distribution.
SYSTEM_LINKS: tuple[str, ...] = ("/bin", "/lib", "/lib64", "/sbin")
IN_SANDBOX_SOCKET = PurePosixPath("/run/va/endpoint.sock")
IN_SANDBOX_TOKEN = PurePosixPath("/run/va/token")
IN_SANDBOX_OUTPUTS = PurePosixPath("/run/va/outputs")


@dataclass(frozen=True)
class Storage:
    """The total for everything an actor can write: file bytes, a multiple of the page
    size, and inodes. Both are RAM. Each inode costs kernel memory on top of the bytes,
    measured at up to 1.3 KiB with a 238-byte name."""

    bytes: int
    inodes: int


@dataclass(frozen=True)
class SandboxSpec:
    """No spec shares the host's network namespace: the actor's network is its own
    loopback, and its only way out is the model route's listener."""

    scratch: Path
    ro_binds: tuple[Path, ...] = ()
    socket: Path | None = None
    token: Path | None = None
    env: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    symlinks: tuple[tuple[Path, Path], ...] = ()
    chdir: Path | None = None
    outputs_link: bool = False
    disable_nested_userns: bool = False
    storage: Storage | None = None

    def bind_sources(self) -> tuple[Path, ...]:
        """Every host path the sandbox binds, in argv order: each one is checked."""
        sources: list[Path] = [*SYSTEM_RO, *self.ro_binds, self.scratch]
        if self.socket is not None:
            sources.append(self.socket)
        if self.token is not None:
            sources.append(self.token)
        return tuple(sources)
