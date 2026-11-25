"""Per-run actor cgroup v2 directory beside the orchestrator's delegated subgroup."""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from autonomy.baseline import write_all

_RUN_ID = re.compile(r"[0-9a-f]{32}")


class ActorCgroup(Protocol):
    path: Path

    def create(self, *, memory_bytes: int, tasks: int) -> None: ...
    def check(self, pid: int, *, memory_bytes: int, tasks: int) -> None: ...
    def empty(self) -> bool: ...
    def kill(self) -> None: ...
    def remove(self, *, wait: float) -> bool: ...


def _write_control(path: Path, value: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CLOEXEC)
    try:
        write_all(fd, value.encode("ascii"))
    finally:
        os.close(fd)


@dataclass(frozen=True)
class CgroupDirectory:
    path: Path

    def create(self, *, memory_bytes: int, tasks: int) -> None:
        _write_control(self.path.parent / "cgroup.subtree_control", "+memory +pids\n")
        self.path.mkdir(mode=0o755)
        try:
            _write_control(self.path / "memory.max", f"{memory_bytes}\n")
            _write_control(self.path / "memory.swap.max", "0\n")
            _write_control(self.path / "memory.oom.group", "1\n")
            _write_control(self.path / "pids.max", f"{tasks}\n")
        except BaseException:
            try:
                self.path.rmdir()
            except OSError:
                pass
            raise

    def check(self, pid: int, *, memory_bytes: int, tasks: int) -> None:
        try:
            procs = (self.path / "cgroup.procs").read_text(encoding="ascii").split()
            mem = (self.path / "memory.max").read_text(encoding="ascii").strip()
            swap = (self.path / "memory.swap.max").read_text(encoding="ascii").strip()
            oom = (self.path / "memory.oom.group").read_text(encoding="ascii").strip()
            pids = (self.path / "pids.max").read_text(encoding="ascii").strip()
            proc_lines = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ValueError(f"cannot verify actor cgroup {self.path}: {exc}") from exc
        v2 = [line[3:] for line in proc_lines if line.startswith("0::")]
        if (
            str(pid) not in procs
            or len(v2) != 1
            or not v2[0].endswith(f"/{self.path.name}")
            or mem != str(memory_bytes)
            or swap != "0"
            or oom != "1"
            or pids != str(tasks)
        ):
            raise ValueError("held child is not confined by the expected actor cgroup limits")

    def empty(self) -> bool:
        try:
            events = (self.path / "cgroup.events").read_text(encoding="ascii").splitlines()
            procs = (self.path / "cgroup.procs").read_text(encoding="ascii").split()
        except FileNotFoundError:
            return True
        return "populated 0" in events and not procs

    def kill(self) -> None:
        try:
            _write_control(self.path / "cgroup.kill", "1\n")
        except FileNotFoundError:
            return

    def remove(self, *, wait: float) -> bool:
        if not self.path.exists():
            return True
        self.kill()
        deadline = time.monotonic() + max(0.0, wait)
        while True:
            if not self.path.exists():
                return True
            if self.empty():
                try:
                    self.path.rmdir()
                    return True
                except FileNotFoundError:
                    return True
                except OSError:
                    pass
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.02, remaining))
        if not self.path.exists():
            return True
        if self.empty():
            try:
                self.path.rmdir()
                return True
            except FileNotFoundError:
                return True
            except OSError:
                return False
        return False


def actor_cgroup(cgroups: Path, unit_cgroup: str, run_id: str) -> CgroupDirectory:
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("invalid run ID for actor cgroup")
    parts = [part for part in unit_cgroup.split("/") if part]
    if not unit_cgroup.startswith("/") or not parts or any(part in (".", "..") for part in parts):
        raise ValueError("invalid unit cgroup path")
    return CgroupDirectory(cgroups.joinpath(*parts, f"actor-{run_id}"))
