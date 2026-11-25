"""Caller cgroup and systemd user-service verification over a fake cgroup tree."""
import os
import pwd
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from autonomy.delegation import Caller, Host, check_unit, current_host, identify, in_user_service
from autonomy.run import RunRefused

UID = os.getuid()
UNIT = "band-dev.service"
UNIT_CG = f"/user.slice/user-{UID}.slice/user@{UID}.service/app.slice/{UNIT}"
CALLER_CG = f"{UNIT_CG}/main"


def make_cgroups(tmp_path: Path, unit_cgroup: str = UNIT_CG) -> Path:
    root = tmp_path / "cgroup"
    current = root
    root.mkdir(parents=True, exist_ok=True)
    for part in unit_cgroup.strip("/").split("/"):
        current = current / part
        current.mkdir(exist_ok=True)
        (current / "memory.max").write_text("max\n")
        (current / "pids.max").write_text("max\n")
    (current / "main").mkdir(exist_ok=True)
    return root


def base_properties(unit_cgroup: str = UNIT_CG) -> dict[str, str]:
    return {
        "ActiveState": "active",
        "Type": "simple",
        "ControlGroup": unit_cgroup,
        "InvocationID": "a" * 32,
        "Delegate": "yes",
        "DelegateControllers": "memory pids",
        "DelegateSubgroup": "main",
        "OOMPolicy": "continue",
    }


def make_host(tmp_path: Path, *, cgroup: str = CALLER_CG, props: dict[str, str] | None = None, show=None) -> Host:
    cgroups = make_cgroups(tmp_path)
    table = base_properties() if props is None else props

    def default_show(queried: str) -> dict[str, str]:
        assert queried == UNIT
        return dict(table)

    return Host(
        config=tmp_path / "config",
        cgroup=cgroup,
        cgroups=cgroups,
        show=default_show if show is None else show,
        actor_cgroup=lambda _u, _r: None,  # type: ignore[return-value]
    )


def test_identify(tmp_path):
    host = make_host(tmp_path)
    caller = identify(host, UNIT)
    assert caller.unit == UNIT
    assert caller.cgroup == UNIT_CG
    assert caller.invocation == "a" * 32

    oneshot = make_host(tmp_path / "oneshot", props={**base_properties(), "ActiveState": "activating", "Type": "oneshot"})
    assert identify(oneshot, UNIT).unit == UNIT

    direct_unit_cg = f"/user.slice/user-{UID}.slice/user@{UID}.service/{UNIT}"
    direct_host = Host(
        config=tmp_path / "direct-cfg",
        cgroup=f"{direct_unit_cg}/main",
        cgroups=make_cgroups(tmp_path / "direct", direct_unit_cg),
        show=lambda _u: base_properties(direct_unit_cg),
        actor_cgroup=lambda _u, _r: None,  # type: ignore[return-value]
    )
    assert identify(direct_host, UNIT).cgroup == direct_unit_cg

    def timeout_show(_u: str) -> dict[str, str]:
        raise subprocess.TimeoutExpired(["systemctl"], 10)

    def failing_show(_u: str) -> dict[str, str]:
        raise OSError("manager unavailable")

    bad_hosts = [
        ("activating-simple", make_host(tmp_path / "c1", props={**base_properties(), "ActiveState": "activating", "Type": "simple"})),
        ("inactive", make_host(tmp_path / "c2", props={**base_properties(), "ActiveState": "inactive"})),
        ("other-unit", make_host(tmp_path / "c3", cgroup=f"/user.slice/user-{UID}.slice/user@{UID}.service/app.slice/other.service/main")),
        ("scope", make_host(tmp_path / "c4", cgroup=f"/user.slice/user-{UID}.slice/user@{UID}.service/app.slice/kitty-1.scope")),
        ("no-subgroup", make_host(tmp_path / "c5", cgroup=UNIT_CG)),
        ("two-subgroups", make_host(tmp_path / "c6", cgroup=f"{UNIT_CG}/main/extra")),
        ("non-slice-before-unit", make_host(tmp_path / "c7", cgroup=f"/user.slice/user-{UID}.slice/user@{UID}.service/folder/{UNIT}/main")),
        ("wrong-subgroup", make_host(tmp_path / "c8", props={**base_properties(), "DelegateSubgroup": "other"})),
        ("wrong-control-group", make_host(tmp_path / "c9", props={**base_properties(), "ControlGroup": "/other"})),
        ("empty-invocation", make_host(tmp_path / "c10", props={**base_properties(), "InvocationID": ""})),
        ("manager-timeout", make_host(tmp_path / "c11", show=timeout_show)),
        ("manager-fails", make_host(tmp_path / "c12", show=failing_show)),
    ]
    for label, bad_host in bad_hosts:
        with pytest.raises(RunRefused) as caught:
            identify(bad_host, UNIT)
        assert caught.value.code == "delegation-caller", label


def test_check_unit(tmp_path):
    peak = 1280 * (1 << 20)
    tasks = 64
    host = make_host(tmp_path)
    caller = identify(host, UNIT)
    assert not (host.cgroups / "memory.max").exists()
    assert not (host.cgroups / "pids.max").exists()
    check_unit(host, caller, peak=peak, tasks=tasks)

    unit_dir = host.cgroups / UNIT_CG.lstrip("/")
    (unit_dir / "memory.max").write_text(f"{peak}\n")
    (unit_dir / "pids.max").write_text(f"{tasks + 1}\n")
    check_unit(host, caller, peak=peak, tasks=tasks)
    (unit_dir / "memory.max").write_text("max\n")
    (unit_dir / "pids.max").write_text("max\n")

    for bad_props in (
        {**base_properties(), "DelegateControllers": "memory"},
        {**base_properties(), "DelegateControllers": "pids"},
        {**base_properties(), "Delegate": "no"},
        {**base_properties(), "OOMPolicy": "stop"},
    ):
        bad_caller = replace(caller, properties=bad_props)
        with pytest.raises(RunRefused) as caught:
            check_unit(host, bad_caller, peak=peak, tasks=tasks)
        assert caught.value.code == "delegation-bounds"

    ancestors = [
        unit_dir,
        host.cgroups / f"user.slice/user-{UID}.slice/user@{UID}.service/app.slice",
        host.cgroups / f"user.slice/user-{UID}.slice/user@{UID}.service",
    ]
    for target in ancestors:
        (target / "memory.max").write_text(f"{peak - 1}\n")
        with pytest.raises(RunRefused) as mem_err:
            check_unit(host, caller, peak=peak, tasks=tasks)
        assert mem_err.value.code == "delegation-bounds"
        (target / "memory.max").write_text("max\n")

        (target / "pids.max").write_text(f"{tasks}\n")
        with pytest.raises(RunRefused) as pids_err:
            check_unit(host, caller, peak=peak, tasks=tasks)
        assert pids_err.value.code == "delegation-bounds"
        (target / "pids.max").write_text("max\n")


def test_in_user_service():
    assert not in_user_service("/user.slice/user-1000.slice/user@1000.service/app.slice/kitty-1.scope")
    assert not in_user_service("/system.slice/github-runner.service")
    assert not in_user_service("/user.slice/user-1000.slice/user@1000.service")
    assert in_user_service("/user.slice/user-1000.slice/user@1000.service/app.slice/band.service")
    assert in_user_service("/user.slice/user-1000.slice/user@1000.service/app.slice/band.service/main")


def test_home_and_xdg_select_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "forged-home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "forged-xdg"))
    expected = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".config" / "verifiably-autonomy"
    assert current_host().config == expected
