"""The sandbox spec is data (envelope design §7): what is bound, where, and how."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Literal

SYSTEM_RO: tuple[Path, ...] = (Path("/usr"), Path("/etc"))
# The merged-/usr symlinks, created inside the sandbox rather than bound.
SYSTEM_SYMLINKS: tuple[tuple[str, str], ...] = (
    ("usr/bin", "/bin"),
    ("usr/lib", "/lib"),
    ("usr/lib", "/lib64"),
    ("usr/bin", "/sbin"),
)
IN_SANDBOX_SOCKET = PurePosixPath("/run/va/endpoint.sock")
IN_SANDBOX_TOKEN = PurePosixPath("/run/va/token")


@dataclass(frozen=True)
class SandboxSpec:
    scratch: Path
    ro_binds: tuple[Path, ...] = ()
    socket: Path | None = None
    token: Path | None = None
    network: Literal["none", "host"] = "none"
    env: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def bind_sources(self) -> tuple[Path, ...]:
        """Every host path the sandbox binds, in argv order: each one is checked."""
        sources: list[Path] = [*SYSTEM_RO, *self.ro_binds, self.scratch]
        if self.socket is not None:
            sources.append(self.socket)
        if self.token is not None:
            sources.append(self.token)
        return tuple(sources)
