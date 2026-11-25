"""Record and verify the Linux process identity used to recover a run."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import uuid

from autonomy.baseline import write_all

__all__ = ["ProcessIdentity", "ProcessSurvived", "exited", "send_signal", "spawn_recorded"]


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


class ProcessSurvived(RuntimeError):
    """A child may still be able to write after its supervisor failed."""


_EXEC_BARRIER = """
import os, sys
fd = int(sys.argv[1])
release = os.read(fd, 1)
os.close(fd)
if release != b'x':
    sys.exit(4)
os.execv(sys.argv[2], sys.argv[2:])
"""


def spawn_recorded(
    argv: Sequence[str], *, env: Mapping[str, str], record: Callable[[ProcessIdentity], None],
    stdin, stdout, stderr, encoding: str | None = None, pass_fds: tuple[int, ...] = (),
) -> tuple[subprocess.Popen, int]:
    """Release the exec barrier only after the child identity is durable."""
    read_end, write_end = os.pipe2(os.O_CLOEXEC)
    child = None
    pidfd = None
    try:
        child = subprocess.Popen(
            [sys.executable, "-I", "-c", _EXEC_BARRIER, str(read_end), *argv],
            pass_fds=(read_end, *pass_fds), env=env, stdin=stdin, stdout=stdout, stderr=stderr,
            encoding=encoding, start_new_session=True,
        )
        pidfd = os.pidfd_open(child.pid)
        record(ProcessIdentity.capture(child.pid))
        write_all(write_end, b"x")
        return child, pidfd
    except BaseException:
        if child is not None:
            try:
                if pidfd is None:
                    child.kill()  # This unreaped child is still behind the exec barrier.
                else:
                    send_signal(pidfd, signal.SIGKILL)
                child.wait(timeout=5)
            except subprocess.TimeoutExpired as error:
                raise ProcessSurvived("exec barrier child did not exit") from error
            finally:
                if pidfd is not None:
                    os.close(pidfd)
                for stream in (child.stdout, child.stderr):
                    if stream is not None:
                        stream.close()
        raise
    finally:
        os.close(read_end)
        os.close(write_end)
