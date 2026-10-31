"""The analyst's toolchain (envelope design decision 14, step 1): the pinned pi install,
the node prefix, and the epoch record that ties a launch to the versions row E24 was
checked with. A change in any of them is a new epoch for the check."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

PI_VERSION = "1.1.0"
"""The pi this build was checked with; the install's lock must name it."""
PI_PACKAGE = "node_modules/@earendil-works/pi-coding-agent"
ANALYST_TOOLS: tuple[str, ...] = ("read", "bash", "grep", "find", "ls", "write")
"""The exact tool set row E24 tests: a constant, never a flag."""
TOOLS_SHADOWED: tuple[str, ...] = ("rg", "fd")
"""pi resolves these from its agent directory's bin/, then PATH; node's bin/ comes first on
the sandbox PATH, so it must hold neither."""
_VERSION_TIMEOUT = 10


class AnalystRefused(Exception):
    """A configuration refusal at step 1: exit 2, nothing kept."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PiInstall:
    dir: Path
    version: str
    lock_sha256: str
    executable: Path


def _absolute(value: str | None) -> Path | None:
    return Path(value) if value and Path(value).is_absolute() else None


def default_pi_dir(env: Mapping[str, str], home: Path) -> Path:
    return _absolute(env.get("PI_DIR")) or home / ".local/share/pi" / PI_VERSION


def default_node_dir(env: Mapping[str, str], which: Callable[[str], str | None] = shutil.which) -> Path | None:
    given = _absolute(env.get("NODE_DIR"))
    if given is not None:
        return given
    node = which("node")
    return None if node is None else Path(node).resolve().parent.parent


def check_pi(pi_dir: Path) -> PiInstall:
    def refused(why: str) -> AnalystRefused:
        return AnalystRefused("pi-mismatch", f"{pi_dir}: {why}")

    try:
        real = pi_dir.resolve(strict=True)
    except OSError as caught:
        raise refused(f"not a directory that resolves: {caught}") from None
    executable = real / "node_modules/.bin/pi"
    if not os.access(executable, os.X_OK) or not executable.is_file():
        raise refused(f"{executable} is not an executable file; run just pi-install in hq")
    try:
        data = (real / "package-lock.json").read_bytes()
    except OSError as caught:
        raise refused(f"package-lock.json cannot be read: {caught}") from None
    try:
        version = json.loads(data)["packages"][PI_PACKAGE]["version"]
    except (ValueError, KeyError, TypeError) as caught:
        raise refused(f"package-lock.json does not name {PI_PACKAGE}: {caught!r}") from None
    if version != PI_VERSION:
        raise refused(f"the install is pi {version}; this build was checked with {PI_VERSION}")
    return PiInstall(real, version, hashlib.sha256(data).hexdigest(), executable)


def check_node(node_dir: Path) -> Path:
    try:
        real = node_dir.resolve(strict=True)
    except OSError as caught:
        raise AnalystRefused("node-missing", f"{node_dir}: {caught}") from None
    node = real / "bin/node"
    if not os.access(node, os.X_OK) or not node.is_file():
        raise AnalystRefused("node-missing", f"{node} is not an executable file")
    with os.scandir(real / "bin") as entries:
        for entry in entries:
            if entry.name in TOOLS_SHADOWED:
                raise AnalystRefused(
                    "toolchain-shadowed",
                    f"{real / 'bin'} holds {entry.name}, which pi would run instead of /usr/bin/{entry.name}",
                )
    return real


def _version(run: Callable[..., subprocess.CompletedProcess], argv: list[str]) -> str | None:
    try:
        result = run(argv, capture_output=True, text=True, timeout=_VERSION_TIMEOUT, stdin=subprocess.DEVNULL,
                     env={"PATH": "/usr/bin"})
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    first = result.stdout.strip().splitlines()
    return first[0].strip() if first else None


def epoch_record(pi: PiInstall, node_dir: Path, *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> dict:
    """The versions a launch ran with. Evidence, not a gate: a tool that is missing or
    fails records null."""
    return {
        "pi": {"version": pi.version, "lock_sha256": pi.lock_sha256},
        "node": _version(run, [str(node_dir / "bin/node"), "--version"]),
        "bwrap": _version(run, ["bwrap", "--version"]),
        "rg": _version(run, ["/usr/bin/rg", "--version"]),
        "fd": _version(run, ["/usr/bin/fd", "--version"]),
    }
