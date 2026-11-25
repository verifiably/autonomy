"""Shared pytest fixture and wrappers for transient systemd user services and private passwd."""
from __future__ import annotations

import os
import secrets
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest


def unit_env(home: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/bin",
        "HOME": str(home),
        "LC_ALL": "C",
        "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
    }


def stop_unit(unit: str, home: Path) -> None:
    subprocess.run(
        ["/usr/bin/systemctl", "--no-pager", "--user", "stop", "--", unit],
        env=unit_env(home),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=10,
        check=False,
    )


def in_delegated_unit(
    argv: Sequence[str], *properties: str, unit: str | None = None
) -> list[str]:
    unit_name = unit or f"autonomy-test-{secrets.token_hex(8)}.service"
    cmd = [
        "/usr/bin/systemd-run",
        "--user",
        "--wait",
        "--pipe",
        "--collect",
        f"--unit={unit_name}",
    ]
    if not any(prop.startswith("Delegate=") for prop in properties):
        cmd.extend(("-p", "Delegate=memory pids"))
    if not any(prop.startswith("DelegateSubgroup=") for prop in properties):
        cmd.extend(("-p", "DelegateSubgroup=main"))
    for prop in properties:
        cmd.extend(("-p", prop))
    cmd.extend(("--", *argv))
    return cmd


def with_passwd_home(home: Path, argv: Sequence[str]) -> list[str]:
    home.mkdir(parents=True, exist_ok=True)
    uid = str(os.getuid())
    lines = []
    matched = False
    for raw in Path("/etc/passwd").read_text(encoding="utf-8").splitlines():
        parts = raw.split(":")
        if len(parts) == 7 and parts[2] == uid:
            parts[5] = str(home)
            matched = True
            lines.append(":".join(parts))
        else:
            lines.append(raw)
    if not matched:
        raise RuntimeError(f"uid {uid} not found in /etc/passwd")
    passwd_file = home.parent / f".passwd-{home.name}-{secrets.token_hex(4)}"
    passwd_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [
        "/usr/bin/unshare",
        "--map-current-user",
        "--mount",
        "--keep-caps",
        "/usr/bin/sh",
        "-c",
        'mount --bind "$1" /etc/passwd && shift && exec "$@"',
        "sh",
        str(passwd_file),
        *argv,
    ]


@pytest.fixture(scope="session")
def user_manager(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("systemd-run") is None or shutil.which("systemctl") is None:
        pytest.skip("systemd-run or systemctl is absent")
    probe_home = tmp_path_factory.mktemp("user-manager")
    env = unit_env(probe_home)
    status = subprocess.run(
        ["/usr/bin/systemctl", "--no-pager", "--user", "is-system-running"],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if status.returncode != 0 and status.stdout.strip() not in ("running", "degraded", "starting"):
        pytest.skip(f"systemctl --user reached no manager: {status.stderr.strip() or status.stdout.strip()}")

    unit = f"autonomy-probe-{secrets.token_hex(8)}.service"
    probe_cmd = in_delegated_unit(
        [
            "/usr/bin/sh",
            "-c",
            'cg=$(sed -n "s/^0:://p" /proc/self/cgroup); cat "/sys/fs/cgroup${cg%/main}/cgroup.controllers"',
        ],
        unit=unit,
    )
    try:
        result = subprocess.run(
            probe_cmd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
        )
    finally:
        stop_unit(unit, probe_home)
    if result.returncode != 0:
        if "Failed to connect" in result.stderr or "No medium found" in result.stderr:
            pytest.skip(f"systemctl --user reached no manager: {result.stderr.strip()}")
        pytest.fail(f"transient delegated unit failed: {result.stderr.strip()}")
    controllers = set(result.stdout.split())
    if not {"memory", "pids"} <= controllers:
        pytest.skip(f"delegated unit did not receive memory and pids controllers: {sorted(controllers)}")
    return probe_home
