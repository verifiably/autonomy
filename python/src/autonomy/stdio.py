"""What the actor's stdio and the report fd may be (envelope design decision 12, §3
step 2).

Each of fds 0, 1 and 2 must be an anonymous pipe, a connected AF_UNIX stream socket,
or /dev/null. Anything else hands the actor a host object by descriptor, past the
static check and the probe: a terminal's keystrokes, a file it can reopen read-write
through /proc/self/fd, a socket into the host's network namespace. The report fd must
be a writable pipe or connected stream that is none of the actor's three."""

from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import socket
import stat
from typing import Literal

StdioKind = Literal["pipe", "socket", "null"]
ACTOR_FDS: tuple[int, int, int] = (0, 1, 2)
PIPEFS_MAGIC = 0x50495045
_NULL_RDEV = os.makedev(1, 3)
_FAMILIES = {socket.AF_UNIX: "AF_UNIX", socket.AF_INET: "AF_INET", socket.AF_INET6: "AF_INET6"}
_TYPES = {socket.SOCK_STREAM: "stream", socket.SOCK_DGRAM: "datagram", socket.SOCK_SEQPACKET: "seqpacket"}

_libc = ctypes.CDLL(None, use_errno=True)
_libc.fstatfs.argtypes = (ctypes.c_int, ctypes.c_void_p)


class StdioRefused(Exception):
    """A descriptor step 2 refuses: the run exits 2 `stdio-refused`."""

    code = "stdio-refused"

    def __init__(self, fd: int, what: str) -> None:
        self.fd = fd
        self.what = what
        self.message = f"fd {fd} is {what}"
        super().__init__(f"{self.code}: {self.message}")


def _fs_type(fd: int) -> int:
    """fstatfs(2)'s f_type: the first field of struct statfs, a long on 64-bit Linux."""
    buffer = ctypes.create_string_buffer(256)  # struct statfs is 120 bytes
    if _libc.fstatfs(fd, buffer) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return ctypes.c_long.from_buffer(buffer).value


def _socket_kind(fd: int) -> StdioKind:
    probe = socket.socket(fileno=os.dup(fd))  # a private duplicate; its close leaves `fd` open
    try:
        family = probe.getsockopt(socket.SOL_SOCKET, socket.SO_DOMAIN)
        kind = probe.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
        if family != socket.AF_UNIX or kind != socket.SOCK_STREAM:
            name = f"{_FAMILIES.get(family, f'family {family}')}, {_TYPES.get(kind, f'type {kind}')}"
            raise StdioRefused(fd, f"a socket ({name})")
        if probe.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN):
            raise StdioRefused(fd, "a listening AF_UNIX stream socket")
        try:
            probe.getpeername()
        except OSError as caught:
            if caught.errno != errno.ENOTCONN:
                raise
            raise StdioRefused(fd, "an unconnected AF_UNIX stream socket") from None
        return "socket"
    finally:
        probe.close()


def classify(fd: int) -> StdioKind:
    try:
        info = os.fstat(fd)
    except OverflowError:
        raise StdioRefused(fd, "beyond any descriptor number") from None
    except OSError as caught:
        if caught.errno == errno.EBADF:
            raise StdioRefused(fd, "closed") from None
        raise
    mode = info.st_mode
    if stat.S_ISFIFO(mode):
        if _fs_type(fd) == PIPEFS_MAGIC:
            return "pipe"
        raise StdioRefused(fd, "a named FIFO")
    if stat.S_ISSOCK(mode):
        return _socket_kind(fd)
    if stat.S_ISCHR(mode):
        if info.st_rdev == _NULL_RDEV:
            return "null"
        if os.isatty(fd):
            raise StdioRefused(fd, "a terminal")
        raise StdioRefused(fd, f"a character device ({os.major(info.st_rdev)}:{os.minor(info.st_rdev)})")
    if stat.S_ISREG(mode):
        raise StdioRefused(fd, "a regular file")
    if stat.S_ISDIR(mode):
        raise StdioRefused(fd, "a directory")
    raise StdioRefused(fd, f"a file of mode {stat.filemode(mode)}")


def check_stdio(fds: tuple[int, int, int] = ACTOR_FDS) -> tuple[StdioKind, StdioKind, StdioKind]:
    first, second, third = (classify(fd) for fd in fds)
    return first, second, third


def _identity(fd: int) -> tuple[int, int]:
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def check_report_fd(fd: int, actor_fds: tuple[int, int, int] = ACTOR_FDS) -> Literal["pipe", "socket"]:
    """Call after `check_stdio(actor_fds)` has passed, so every actor fd is open."""
    if fd in actor_fds:
        raise StdioRefused(fd, f"the actor's fd {actor_fds.index(fd)}; the report fd must be another descriptor")
    kind = classify(fd)
    if kind == "null":
        raise StdioRefused(fd, "/dev/null; the report fd must be an anonymous pipe or a connected AF_UNIX stream socket")
    if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY:
        raise StdioRefused(fd, "opened read-only, such as a pipe's read end")
    identity = _identity(fd)
    for actor_fd in actor_fds:
        if _identity(actor_fd) == identity:
            raise StdioRefused(fd, f"the same file as fd {actor_fd}")
    return kind
