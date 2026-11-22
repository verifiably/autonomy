"""Record and verify the Linux process identity used to recover a run."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import select
import signal
import uuid

__all__ = ["ProcessIdentity", "exited", "send_signal"]


def _boot_id() -> str:
    value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if str(uuid.UUID(value)) != value:
        raise ValueError("invalid kernel boot ID")
    return value


def _start_time(pid: int) -> int:
    raw = Path(f"/proc/{pid}/stat").read_bytes()
    return int(raw.rsplit(b")", 1)[1].split()[19])


def exited(pidfd: int, timeout: float = 0) -> bool:
    poll = select.poll()
    poll.register(pidfd, select.POLLIN)
    return any(flags & select.POLLIN for _, flags in poll.poll(max(0, int(timeout * 1000))))


def send_signal(pidfd: int, signum: int) -> None:
    try:
        signal.pidfd_send_signal(pidfd, signum)
    except ProcessLookupError:
        pass


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    start_time: int
    boot_id: str

    def __post_init__(self) -> None:
        if type(self.pid) is not int or self.pid <= 0 or type(self.start_time) is not int or self.start_time < 0:
            raise ValueError("invalid process identity")
        if not isinstance(self.boot_id, str) or str(uuid.UUID(self.boot_id)) != self.boot_id:
            raise ValueError("invalid process boot ID")

    @classmethod
    def capture(cls, pid: int) -> ProcessIdentity:
        return cls(pid, _start_time(pid), _boot_id())

    def fields(self) -> dict[str, object]:
        return {"pid": self.pid, "start_time": self.start_time, "boot_id": self.boot_id}

    def pin(self) -> int | None:
        """Open a pidfd on the recorded process. None proves absence or replacement."""
        if _boot_id() != self.boot_id:
            return None
        try:
            pidfd = os.pidfd_open(self.pid)
        except ProcessLookupError:
            return None
        try:
            if not exited(pidfd):
                try:
                    same = _start_time(self.pid) == self.start_time
                except FileNotFoundError:
                    if not exited(pidfd):
                        raise
                else:
                    if same and not exited(pidfd):
                        return pidfd
        except BaseException:
            os.close(pidfd)
            raise
        os.close(pidfd)
        return None
