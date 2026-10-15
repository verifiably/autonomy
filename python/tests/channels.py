"""Helpers for tests that drive a caller's descriptors: pipes shrunk to one page,
channels filled to the last byte, and reads that fail rather than hang."""

import fcntl
import os
import select
import socket
import stat
import time


def one_page_pipe() -> tuple[int, int]:
    read_end, write_end = os.pipe()
    fcntl.fcntl(write_end, fcntl.F_SETPIPE_SZ, 4096)
    return read_end, write_end


def fill(fd: int) -> None:
    """Fill a pipe or stream socket to its last byte through a private non-blocking
    path, leaving `fd`'s own flags alone."""
    if stat.S_ISSOCK(os.fstat(fd).st_mode):
        sock = socket.socket(fileno=os.dup(fd))
        try:
            for size in (4096, 1):
                try:
                    while True:
                        sock.send(b"x" * size, socket.MSG_DONTWAIT)
                except BlockingIOError:
                    pass
        finally:
            sock.close()
        return
    private = os.open(f"/proc/self/fd/{fd}", os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        for size in (4096, 1):
            try:
                while True:
                    os.write(private, b"x" * size)
            except BlockingIOError:
                pass
    finally:
        os.close(private)


def blocking(fd: int) -> bool:
    return not fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_NONBLOCK


def read_all(fd: int, timeout: float = 10.0) -> bytes:
    """Everything up to EOF; fails the test rather than hang."""
    data = b""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        assert remaining > 0, f"no EOF on fd {fd} within {timeout} s"
        if not select.select([fd], [], [], remaining)[0]:
            continue
        chunk = os.read(fd, 65536)
        if not chunk:
            return data
        data += chunk


def drain(fd: int) -> bytes:
    """What is readable now, without waiting for EOF. Sets `fd` non-blocking: check
    `blocking` first."""
    os.set_blocking(fd, False)
    data = b""
    try:
        while chunk := os.read(fd, 65536):
            data += chunk
    except BlockingIOError:
        pass
    return data
