"""The sandbox spec is data (envelope design §7): what is bound, where, and how."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType

SYSTEM_RO: tuple[Path, ...] = (Path("/usr"), Path("/etc"))
# The merged-/usr symlinks, recreated inside the sandbox rather than bound. Their
# targets are the host's (static.system_symlinks): they differ by distribution.
SYSTEM_LINKS: tuple[str, ...] = ("/bin", "/lib", "/lib64", "/sbin")
IN_SANDBOX_SOCKET = PurePosixPath("/run/va/endpoint.sock")
IN_SANDBOX_TOKEN = PurePosixPath("/run/va/token")


@dataclass(frozen=True)
class SandboxSpec:
    """No spec shares the host's network namespace: the actor's network is its own
    loopback, and its only way out is the model route's listener (decision 13)."""

    scratch: Path
    ro_binds: tuple[Path, ...] = ()
    socket: Path | None = None
    token: Path | None = None
    env: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def bind_sources(self) -> tuple[Path, ...]:
        """Every host path the sandbox binds, in argv order: each one is checked."""
        sources: list[Path] = [*SYSTEM_RO, *self.ro_binds, self.scratch]
        if self.socket is not None:
            sources.append(self.socket)
        if self.token is not None:
            sources.append(self.token)
        return tuple(sources)
