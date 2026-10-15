"""Lines to a caller's descriptor that can never hang the run (envelope design
decision 12): the report fd's two lines, and diagnostics on stderr before the actor
starts.

The caller's open file description is never changed. A pipe is written through a
private descriptor opened on /proc/self/fd/<n> with O_NONBLOCK: a new description of
the same pipe, whereas a dup would share, and change, the caller's flags. A socket is
written with MSG_DONTWAIT on each send. /dev/null is skipped. Nothing else is ever
written: a reopened regular file loses O_APPEND and its offset and would overwrite the
caller's log, a file write can block on the filesystem, and a terminal write from a
background process group can stop the process with SIGTTOU.

Each line is one write of at most PIPE_BUF bytes, after waiting at most POLL_WAIT for
the descriptor to poll writable. A line whose write fails, would block or is short is
dropped, and so is a line too long for one write, whole. After a drop nothing more is
written on that descriptor, so a short line is never followed by another.

Constructing a channel may open a descriptor, so a caller constructs it only after
step 2 has checked fds 0-2: opened while fd 0 is closed, it would take number 0."""

from __future__ import annotations

import os
import select
import socket
import stat
from collections.abc import Callable

POLL_WAIT = 1.0
"""Seconds a line may wait for its descriptor to poll writable."""

_NULL_RDEV = os.makedev(1, 3)

_before_write: Callable[[int], None] | None = None
"""Test hook (spec row E20): called with the caller's descriptor between the poll and
the write, where a competing writer can fill the channel."""


class LineChannel:
    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.dropped = False
        self._skip = False
        self._socket: socket.socket | None = None
        self._private = -1
        try:
            info = os.fstat(fd)
        except OSError:
            self.dropped = True
            return
        if stat.S_ISSOCK(info.st_mode):
            self._socket = socket.socket(fileno=os.dup(fd))
        elif stat.S_ISCHR(info.st_mode) and info.st_rdev == _NULL_RDEV:
            self._skip = True
        elif stat.S_ISFIFO(info.st_mode):
            try:
                self._private = os.open(f"/proc/self/fd/{fd}", os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            except OSError:
                self.dropped = True
        else:
            self.dropped = True  # a file, a terminal, a device: never written

    def write_line(self, line: str) -> bool:
        """Write `line` and a newline in one write; False when the line was dropped."""
        data = line.encode("utf-8") + b"\n"
        if b"\n" in data[:-1]:
            raise ValueError("a line holds no newline")
        if self.dropped:
            return False
        if len(data) > select.PIPE_BUF:
            self.close()  # dropped whole: a truncated line would say something false
            return False
        if self._skip:
            return True
        target = self._socket.fileno() if self._socket is not None else self._private
        poller = select.poll()
        poller.register(target, select.POLLOUT)
        poller.poll(POLL_WAIT * 1000)
        if _before_write is not None:
            _before_write(self.fd)
        try:
            if self._socket is not None:
                written = self._socket.send(data, socket.MSG_DONTWAIT | socket.MSG_NOSIGNAL)
            else:
                written = os.write(self._private, data)
        except OSError:
            written = -1
        if written != len(data):
            self.close()
            return False
        return True

    def close(self) -> None:
        """Release the private path and drop every later line; `fd` itself stays open."""
        self.dropped = True
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._private >= 0:
            os.close(self._private)
            self._private = -1
