import errno
import os
import socket
import subprocess
import sys
import textwrap
import time

import pytest

import autonomy.channel as channel
from autonomy.channel import LineChannel
from autonomy.stdio import StdioRefused
from channels import blocking, drain, fill, one_page_pipe


@pytest.fixture(autouse=True)
def short_poll(monkeypatch):
    monkeypatch.setattr(channel, "POLL_WAIT", 0.2)


def test_a_line_reaches_a_pipe_and_the_callers_flags_are_untouched():
    read_end, write_end = os.pipe()
    try:
        line = LineChannel(write_end)
        assert line.write_line('{"run": "x"}') is True
        assert drain(read_end) == b'{"run": "x"}\n'
        assert blocking(write_end)
        line.close()
        os.fstat(write_end)  # still open
    finally:
        os.close(read_end)
        os.close(write_end)


def test_a_line_reaches_a_socket_and_the_callers_flags_are_untouched():
    mine, theirs = socket.socketpair()
    with mine, theirs:
        line = LineChannel(mine.fileno())
        assert line.write_line("hello") is True
        assert theirs.recv(64) == b"hello\n"
        assert blocking(mine.fileno())
        line.close()


def test_a_process_wide_default_socket_timeout_is_refused_not_dropped():
    mine, theirs = socket.socketpair()
    with mine, theirs:
        before = os.get_blocking(mine.fileno())
        socket.setdefaulttimeout(5.0)
        try:
            with pytest.raises(StdioRefused):
                LineChannel(mine.fileno())
        finally:
            socket.setdefaulttimeout(None)
        assert os.get_blocking(mine.fileno()) == before  # refused before the dup


def test_a_default_socket_timeout_leaves_a_pipe_channel_alone():
    read_end, write_end = os.pipe()
    try:
        socket.setdefaulttimeout(5.0)
        try:
            line = LineChannel(write_end)
            assert line.write_line('{"run": "x"}') is True
        finally:
            socket.setdefaulttimeout(None)
        assert drain(read_end) == b'{"run": "x"}\n'
        assert blocking(write_end)  # the caller's description is untouched
        line.close()
    finally:
        os.close(read_end)
        os.close(write_end)


def test_dev_null_is_skipped():
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        assert LineChannel(null).write_line("nothing") is True
    finally:
        os.close(null)


def test_a_closed_descriptor_drops_every_line():
    closed = os.open(os.devnull, os.O_RDONLY)
    os.close(closed)
    line = LineChannel(closed)
    assert line.write_line("lost") is False and line.dropped


def test_a_socket_that_cannot_be_duplicated_drops_every_line(monkeypatch):  # I1: EMFILE
    def no_descriptor_left(fd):
        raise OSError(errno.EMFILE, os.strerror(errno.EMFILE))

    mine, theirs = socket.socketpair()
    with mine, theirs:
        with monkeypatch.context() as patch:
            patch.setattr(channel.os, "dup", no_descriptor_left)
            line = LineChannel(mine.fileno())
        assert line.write_line("lost") is False and line.dropped


def test_an_appended_log_is_never_written(tmp_path):  # a reopen would lose O_APPEND and the offset
    log = tmp_path / "existing.log"
    log.write_bytes(b"earlier lines\n")
    fd = os.open(log, os.O_WRONLY | os.O_APPEND)  # `2>>existing.log`
    try:
        line = LineChannel(fd)
        assert line.write_line("autonomy: refused: stdio-refused: fd 2 is a regular file") is False
        assert line.dropped and line._private == -1
    finally:
        os.close(fd)
    assert log.read_bytes() == b"earlier lines\n"


@pytest.mark.parametrize("kind", ["terminal", "zero"])
def test_a_terminal_or_a_device_is_never_written(kind):
    # a terminal write from a background process group can stop the process (SIGTTOU)
    if kind == "terminal":
        master, fd = os.openpty()
    else:
        master, fd = None, os.open("/dev/zero", os.O_WRONLY)
    try:
        line = LineChannel(fd)
        assert line.write_line("never") is False and line._private == -1
        if master is not None:
            os.set_blocking(master, False)
            with pytest.raises(BlockingIOError):
                os.read(master, 64)  # nothing reached the terminal (read while its slave is open)
    finally:
        os.close(fd)
        if master is not None:
            os.close(master)


def test_a_full_pipe_drops_the_line_within_the_poll_wait_and_nothing_follows():
    read_end, write_end = one_page_pipe()
    try:
        fill(write_end)
        line = LineChannel(write_end)
        started = time.monotonic()
        assert line.write_line("first") is False
        assert time.monotonic() - started < 2
        drain(read_end)
        assert line.write_line("second") is False  # after a drop, nothing more
        assert drain(read_end) == b""
        assert blocking(write_end)
    finally:
        os.close(read_end)
        os.close(write_end)


@pytest.mark.parametrize("kind", ["pipe", "socket"])
def test_a_competing_writer_after_the_poll_gives_a_drop(monkeypatch, kind):
    if kind == "pipe":
        read_end, write_end = one_page_pipe()
        ends = (read_end, write_end)
    else:
        a, b = socket.socketpair()
        read_end, write_end = b.fileno(), a.fileno()
        ends = (a, b)
    second = os.dup(write_end)  # the second writer the caller holds
    monkeypatch.setattr(channel, "_before_write", lambda fd: fill(second) if fd == write_end else None)
    try:
        line = LineChannel(write_end)
        assert line.write_line('{"run": "x"}') is False
        assert line.dropped
        assert blocking(write_end) and blocking(second)
    finally:
        os.close(second)
        for end in ends:
            end.close() if isinstance(end, socket.socket) else os.close(end)


def test_a_pipe_with_no_reader_drops_the_line():
    read_end, write_end = os.pipe()
    os.close(read_end)
    try:
        assert LineChannel(write_end).write_line("lost") is False
    finally:
        os.close(write_end)


def test_a_line_longer_than_pipe_buf_is_dropped_whole():  # Review Focus 4
    read_end, write_end = os.pipe()
    try:
        line = LineChannel(write_end)
        assert line.write_line("x" * 4095) is True  # 4096 bytes with its newline: one write
        assert line.write_line("x" * 4096) is False  # 4097: dropped, never truncated or split
        assert line.dropped
        assert line.write_line("short") is False  # after a drop, nothing more
        assert drain(read_end) == b"x" * 4095 + b"\n"
    finally:
        os.close(read_end)
        os.close(write_end)


def test_a_line_holding_a_newline_is_a_callers_bug():
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        with pytest.raises(ValueError):
            LineChannel(null).write_line("two\nlines")
    finally:
        os.close(null)


def test_the_private_descriptor_is_not_inheritable():
    read_end, write_end = os.pipe()
    try:
        line = LineChannel(write_end)
        assert os.get_inheritable(line._private) is False
        line.close()
    finally:
        os.close(read_end)
        os.close(write_end)


# Negatives: why the channel reopens instead of setting flags, and never blocks.

def test_a_nonblocking_dup_leaves_the_original_description_nonblocking():
    read_end, write_end = os.pipe()
    duplicate = os.dup(write_end)
    try:
        os.set_blocking(duplicate, False)
        assert not blocking(write_end)
    finally:
        for fd in (read_end, write_end, duplicate):
            os.close(fd)


HANGS = {
    "a blocking write to a full pipe": """
        import os, fcntl
        r, w = os.pipe(); fcntl.fcntl(w, fcntl.F_SETPIPE_SZ, 4096)
        os.write(w, b"x" * 4096)
        os.write(w, b"line\\n")
    """,
    "a poll followed by a blocking write": """
        import os, fcntl, select
        r, w = os.pipe(); fcntl.fcntl(w, fcntl.F_SETPIPE_SZ, 4096)
        p = select.poll(); p.register(w, select.POLLOUT)
        assert p.poll(1000)
        os.write(w, b"x" * 4096)  # the competing writer fills it
        os.write(w, b"line\\n")
    """,
}


@pytest.mark.parametrize("name", sorted(HANGS))
def test_a_blocking_write_hangs(name):
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run([sys.executable, "-c", textwrap.dedent(HANGS[name])], timeout=2, stdin=subprocess.DEVNULL)
