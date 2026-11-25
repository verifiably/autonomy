"""Account configuration, caller cgroup identity, and systemd user-unit bounds."""
from __future__ import annotations

import os
import pwd
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from autonomy.run import RunRefused

from ._cgroup import ActorCgroup, actor_cgroup
from ._contract import valid_unit

_PROPERTIES = (
    "ActiveState",
    "Type",
    "ControlGroup",
    "InvocationID",
    "Delegate",
    "DelegateControllers",
    "DelegateSubgroup",
    "OOMPolicy",
)
_USER_MANAGER_RE = re.compile(r"^/user\.slice/user-(\d+)\.slice/user@\1\.service/(.+)$")


@dataclass(frozen=True)
class Host:
    config: Path
    cgroup: str
    cgroups: Path
    show: Callable[[str], Mapping[str, str]]
    actor_cgroup: Callable[[str, str], ActorCgroup]


@dataclass(frozen=True)
class Caller:
    unit: str
    cgroup: str
    invocation: str
    properties: Mapping[str, str]


def _account_config() -> Path:
    uid = os.getuid()
    try:
        pw_dir = pwd.getpwuid(uid).pw_dir
    except KeyError:
        raise RunRefused("delegation-unavailable", f"uid {uid} has no password database entry") from None
    home = Path(pw_dir)
    if not pw_dir or "\x00" in pw_dir or not home.is_absolute():
        raise RunRefused("delegation-unavailable", f"uid {uid} password database home is not absolute")
    return home / ".config" / "verifiably-autonomy"


def _self_cgroup() -> str:
    try:
        lines = Path("/proc/self/cgroup").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RunRefused("delegation-caller", f"cannot read caller cgroup: {exc}") from exc
    v2 = [line[3:] for line in lines if line.startswith("0::")]
    if len(v2) != 1 or not v2[0].startswith("/"):
        raise RunRefused("delegation-caller", "caller has no unified cgroup v2 path")
    return v2[0]


def _show_unit(unit: str) -> Mapping[str, str]:
    uid = os.getuid()
    cmd = [
        "/usr/bin/systemctl",
        "--no-pager",
        "--user",
        "show",
        *[arg for prop in _PROPERTIES for arg in ("-p", prop)],
        "--",
        unit,
    ]
    result = subprocess.run(
        cmd,
        env={"PATH": "/usr/bin", "XDG_RUNTIME_DIR": f"/run/user/{uid}"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    parsed: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            parsed[key] = value
    return MappingProxyType(parsed)


def current_host() -> Host:
    cgroups = Path("/sys/fs/cgroup")
    return Host(
        config=_account_config(),
        cgroup=_self_cgroup(),
        cgroups=cgroups,
        show=_show_unit,
        actor_cgroup=lambda unit_cgroup, run_id: actor_cgroup(cgroups, unit_cgroup, run_id),
    )


def in_user_service(cgroup: str) -> bool:
    match = _USER_MANAGER_RE.match(cgroup)
    if match is None:
        return False
    parts = [part for part in match.group(2).split("/") if part]
    return any(part.endswith(".service") for part in parts)


def identify(host: Host, unit: str) -> Caller:
    valid_unit(unit)
    uid = os.getuid()
    prefix = f"/user.slice/user-{uid}.slice/user@{uid}.service/"
    if not host.cgroup.startswith(prefix):
        raise RunRefused("delegation-caller", f"caller is outside user@{uid}.service")
    parts = host.cgroup[len(prefix):].split("/")
    if len(parts) < 2 or any(part in ("", ".", "..") for part in parts):
        raise RunRefused("delegation-caller", "caller cgroup lacks a delegated service subgroup")
    *slices, unit_part, subgroup = parts
    if any(not item.endswith(".slice") for item in slices) or unit_part != unit or subgroup.startswith("actor-"):
        raise RunRefused("delegation-caller", f"caller cgroup does not match {unit}")
    unit_cgroup = prefix + "/".join([*slices, unit_part])
    try:
        props = host.show(unit)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RunRefused("delegation-caller", f"user manager did not report {unit}: {exc}") from exc

    active = props.get("ActiveState", "")
    service_type = props.get("Type", "")
    invocation = props.get("InvocationID", "")
    if not (active == "active" or (active == "activating" and service_type == "oneshot")):
        raise RunRefused("delegation-caller", f"unit {unit} is not active ({active})")
    if props.get("ControlGroup") != unit_cgroup or props.get("DelegateSubgroup") != subgroup:
        raise RunRefused("delegation-caller", f"unit {unit} control group or subgroup disagrees with manager")
    if not invocation or any(ch.isspace() for ch in invocation):
        raise RunRefused("delegation-caller", f"unit {unit} has no invocation ID")
    return Caller(
        unit=unit,
        cgroup=unit_cgroup,
        invocation=invocation,
        properties=MappingProxyType(dict(props)),
    )


def _read_cgroup_limit(path: Path, *, allow_missing: bool) -> int | None:
    try:
        raw = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        if allow_missing:
            return None
        raise RunRefused("delegation-bounds", f"missing cgroup limit file {path.name}") from None
    except OSError as exc:
        raise RunRefused("delegation-bounds", f"cannot read {path.name}: {exc}") from exc
    if raw == "max":
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise RunRefused("delegation-bounds", f"invalid cgroup limit in {path.name}") from exc


def check_unit(host: Host, caller: Caller, *, peak: int, tasks: int) -> None:
    props = caller.properties
    controllers = set(props.get("DelegateControllers", "").split())
    if props.get("Delegate") != "yes" or not {"memory", "pids"} <= controllers:
        raise RunRefused("delegation-bounds", f"unit {caller.unit} must delegate memory and pids controllers")
    if props.get("OOMPolicy") != "continue":
        raise RunRefused("delegation-bounds", f"unit {caller.unit} must set OOMPolicy=continue")

    root = host.cgroups
    unit_dir = root.joinpath(*[part for part in caller.cgroup.split("/") if part])
    if not unit_dir.is_dir():
        raise RunRefused("delegation-bounds", f"unit cgroup directory {unit_dir} is absent")

    current = unit_dir
    while True:
        is_root = current == root
        mem = _read_cgroup_limit(current / "memory.max", allow_missing=is_root)
        if mem is not None and mem < peak:
            raise RunRefused("delegation-bounds", f"{current}/memory.max ({mem}) is below required peak ({peak})")
        pids = _read_cgroup_limit(current / "pids.max", allow_missing=is_root)
        if pids is not None and pids <= tasks:
            raise RunRefused("delegation-bounds", f"{current}/pids.max ({pids}) must exceed tasks ({tasks})")
        if is_root:
            break
        parent = current.parent
        if parent == current:
            raise RunRefused("delegation-bounds", "unit cgroup does not lie beneath cgroup root")
        current = parent
