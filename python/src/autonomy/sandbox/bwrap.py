"""The bwrap driver (envelope design §7, §8): argv, preflight, the denial probe,
and (Task 7) launch and kill."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

from autonomy.sandbox.spec import IN_SANDBOX_SOCKET, IN_SANDBOX_TOKEN, SYSTEM_RO, SYSTEM_SYMLINKS, SandboxSpec
from autonomy.sandbox.static import SandboxUnproven, check_binds

_PROBE = """\
import errno, os, sys
for path in sys.argv[1:]:
    try:
        os.stat(path)
        print("REACHABLE", path)
    except OSError as caught:
        print(errno.errorcode.get(caught.errno, str(caught.errno)), path)
"""


def preflight(which: Callable[[str], str | None] = shutil.which) -> None:
    if which("bwrap") is None:
        raise SandboxUnproven("bwrap-missing", "bwrap", "bubblewrap is not on PATH")
    trial = [
        "bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr",
        *[arg for target, link in SYSTEM_SYMLINKS for arg in ("--symlink", target, link)],
        "--", "/usr/bin/true",
    ]
    result = subprocess.run(trial, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise SandboxUnproven("userns-unavailable", "bwrap", result.stderr.strip() or f"exit {result.returncode}")


def build_argv(
    spec: SandboxSpec, argv: Iterable[str], *, info_fd: int | None, block_fd: int | None = None
) -> list[str]:
    args = ["bwrap", "--unshare-all"]
    if spec.network == "host":
        args.append("--share-net")
    args += ["--die-with-parent", "--new-session", "--clearenv", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for path in SYSTEM_RO:
        args += ["--ro-bind", str(path), str(path)]
    for target, link in SYSTEM_SYMLINKS:
        args += ["--symlink", target, link]
    for path in spec.ro_binds:
        args += ["--ro-bind", str(path), str(path)]
    args += ["--bind", str(spec.scratch), str(spec.scratch)]
    if spec.socket is not None or spec.token is not None:
        args += ["--dir", "/run/va"]
    if spec.socket is not None:
        args += ["--bind", str(spec.socket), str(IN_SANDBOX_SOCKET)]
    if spec.token is not None:
        args += ["--ro-bind", str(spec.token), str(IN_SANDBOX_TOKEN)]
    env = {"PATH": "/usr/bin", **spec.env}
    for key, value in sorted(env.items()):
        args += ["--setenv", key, value]
    args += ["--chdir", str(spec.scratch)]
    if info_fd is not None:
        args += ["--info-fd", str(info_fd)]
    if block_fd is not None:
        # bwrap reports the child on --info-fd, then holds the command until this fd
        # has data: the window in which launch() takes its pidfd (Task 7)
        args += ["--block-fd", str(block_fd)]
    return [*args, "--", *argv]


def probe(spec: SandboxSpec, denied: Iterable[Path]) -> None:
    paths = [str(p.resolve()) for p in denied]
    argv = build_argv(spec, ["/usr/bin/python3", "-I", "-c", _PROBE, *paths], info_fd=None)
    result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise SandboxUnproven("probe-failed", "bwrap", result.stderr.strip() or f"exit {result.returncode}")
    lines = result.stdout.splitlines()
    if len(lines) != len(paths):
        raise SandboxUnproven("probe-failed", "bwrap", f"expected {len(paths)} lines, got {len(lines)}")
    for path, line in zip(paths, lines, strict=True):
        status, _, reported = line.partition(" ")
        if reported != path or status != "ENOENT":
            raise SandboxUnproven("probe-reachable", path, f"stat inside the sandbox gave {status}, not ENOENT")


def prove(spec: SandboxSpec, denied: Iterable[Path], *, which: Callable[[str], str | None] = shutil.which) -> None:
    denied = tuple(denied)
    preflight(which)
    check_binds(spec, denied)
    probe(spec, denied)
