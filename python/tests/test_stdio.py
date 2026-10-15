import os
import socket
import stat
import secrets

import pytest

from autonomy.stdio import StdioRefused, check_report_fd, check_stdio, classify


@pytest.fixture
def opened(tmp_path):
    """make(kind) -> an fd of that kind, closed at teardown."""
    held: list = []

    def keep(*items):
        held.extend(items)

    def make(kind: str) -> int:
        if kind in ("pipe-read", "pipe-write"):
            read_end, write_end = os.pipe()
            keep(read_end, write_end)
            return read_end if kind == "pipe-read" else write_end
        if kind == "socketpair":
            a, b = socket.socketpair()
            keep(a, b)
            return a.fileno()
        if kind == "unix-seqpacket":
            a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            keep(a, b)
            return a.fileno()
        if kind == "terminal":
            master, slave = os.openpty()
            keep(master, slave)
            return slave
        if kind == "fifo":
            os.mkfifo(tmp_path / "fifo")
            fd = os.open(tmp_path / "fifo", os.O_RDWR)
        elif kind == "null":
            fd = os.open(os.devnull, os.O_RDWR)
        elif kind == "zero":
            fd = os.open("/dev/zero", os.O_RDONLY)
        elif kind == "regular":
            fd = os.open(tmp_path / "file", os.O_RDWR | os.O_CREAT, 0o600)
        elif kind == "directory":
            fd = os.open(tmp_path, os.O_RDONLY)
        elif kind == "closed":
            fd = os.open(os.devnull, os.O_RDONLY)
            os.close(fd)
            return fd
        elif kind == "udp":
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            keep(sock)
            return sock.fileno()
        elif kind == "unix-unconnected":
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            keep(sock)
            return sock.fileno()
        elif kind == "unix-listening":
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(f"\0va-test-{secrets.token_hex(8)}")  # abstract: no path-length limit
            sock.listen()
            keep(sock)
            return sock.fileno()
        elif kind == "inet-connected":
            server = socket.create_server(("127.0.0.1", 0))
            client = socket.create_connection(server.getsockname())
            keep(server, client)
            return client.fileno()
        else:
            raise AssertionError(kind)
        keep(fd)
        return fd

    yield make
    for item in held:
        if isinstance(item, socket.socket):
            item.close()
        else:
            try:
                os.close(item)
            except OSError:
                pass


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("pipe-read", "pipe"), ("pipe-write", "pipe"), ("socketpair", "socket"), ("null", "null")],
)
def test_the_three_kinds_pass(opened, kind, expected):
    assert classify(opened(kind)) == expected


@pytest.mark.parametrize(
    ("kind", "what"),
    [
        ("terminal", "a terminal"),
        ("regular", "a regular file"),
        ("directory", "a directory"),
        ("zero", "a character device (1:5)"),
        ("fifo", "a named FIFO"),
        ("udp", "a socket (AF_INET, datagram)"),
        ("unix-unconnected", "an unconnected AF_UNIX stream socket"),
        ("unix-listening", "a listening AF_UNIX stream socket"),
        ("unix-seqpacket", "a socket (AF_UNIX, seqpacket)"),
        ("inet-connected", "a socket (AF_INET, stream)"),
        ("closed", "closed"),
    ],
)
def test_everything_else_is_refused_naming_the_fd_and_what_it_is(opened, kind, what):
    fd = opened(kind)
    with pytest.raises(StdioRefused) as caught:
        classify(fd)
    assert (caught.value.code, caught.value.fd, caught.value.what) == ("stdio-refused", fd, what)
    assert caught.value.message == f"fd {fd} is {what}"


def test_inspecting_a_socket_leaves_its_flags_alone(opened):
    fd = opened("socketpair")
    before = os.get_blocking(fd)
    classify(fd)
    assert os.get_blocking(fd) == before and os.get_inheritable(fd) is False


def test_check_stdio_reports_each_kind(opened):
    fds = (opened("null"), opened("socketpair"), opened("pipe-write"))
    assert check_stdio(fds) == ("null", "socket", "pipe")


def test_check_stdio_names_the_first_refused_fd(opened):
    fds = (opened("null"), opened("terminal"), opened("regular"))
    with pytest.raises(StdioRefused) as caught:
        check_stdio(fds)
    assert caught.value.fd == fds[1]


@pytest.mark.parametrize("kind", ["pipe-write", "socketpair"])
def test_a_report_fd_may_be_a_pipe_or_a_connected_stream(opened, kind):
    actor = (opened("null"), opened("pipe-write"), opened("pipe-write"))
    assert check_report_fd(opened(kind), actor) in ("pipe", "socket")


def test_a_report_fd_that_is_an_actor_fd_is_refused(opened):
    actor = (opened("null"), opened("pipe-write"), opened("pipe-write"))
    with pytest.raises(StdioRefused) as caught:
        check_report_fd(actor[1], actor)
    assert "the actor's" in caught.value.what


def test_a_report_fd_duplicated_from_an_actor_fd_is_refused(opened):
    actor = (opened("null"), opened("pipe-write"), opened("pipe-write"))
    duplicate = os.dup(actor[2])  # `3>&2`
    try:
        with pytest.raises(StdioRefused) as caught:
            check_report_fd(duplicate, actor)
    finally:
        os.close(duplicate)
    assert caught.value.what == f"the same file as fd {actor[2]}"


@pytest.mark.parametrize("kind", ["null", "terminal", "regular", "closed"])
def test_a_report_fd_of_another_kind_is_refused(opened, kind):
    actor = (opened("null"), opened("pipe-write"), opened("pipe-write"))
    with pytest.raises(StdioRefused):
        check_report_fd(opened(kind), actor)


def test_a_report_fd_that_is_a_read_end_is_refused(opened):  # Review Focus 3
    actor = (opened("null"), opened("pipe-write"), opened("pipe-write"))
    with pytest.raises(StdioRefused) as caught:
        check_report_fd(opened("pipe-read"), actor)
    assert "read-only" in caught.value.what


# Negatives: each weaker check passes something step 2 must refuse.

def test_any_character_device_but_a_tty_would_pass_dev_zero(opened):
    zero = opened("zero")
    assert stat.S_ISCHR(os.fstat(zero).st_mode) and not os.isatty(zero)


def test_s_issock_alone_would_pass_a_udp_socket(opened):
    assert stat.S_ISSOCK(os.fstat(opened("udp")).st_mode)


def test_so_peercred_alone_would_pass_an_unconnected_unix_socket(opened):
    probe = socket.socket(fileno=os.dup(opened("unix-unconnected")))
    try:
        probe.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)  # raises nothing
    finally:
        probe.close()


def test_a_report_check_by_number_alone_would_pass_a_duplicate_of_fd_2(opened):
    actor = (opened("null"), opened("pipe-write"), opened("pipe-write"))
    duplicate = os.dup(actor[2])
    try:
        assert duplicate not in actor
    finally:
        os.close(duplicate)


@pytest.mark.bwrap
def test_a_udp_socket_on_stdio_reaches_the_host_under_network_none(tmp_path, opened):
    from autonomy.sandbox.bwrap import launch
    from autonomy.sandbox.spec import SandboxSpec

    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    listener.settimeout(10)
    port = listener.getsockname()[1]
    udp, null = opened("udp"), opened("null")
    try:
        sandboxed = launch(
            SandboxSpec(scratch=tmp_path, network="none"),
            ["/usr/bin/python3", "-I", "-c", f"import socket; socket.socket(fileno=1).sendto(b'out', ('127.0.0.1', {port}))"],
            stdin=null, stdout=udp, stderr=null,
        )
        try:
            assert sandboxed.wait(timeout=10) == 0
        finally:
            sandboxed.close()
        assert listener.recvfrom(16)[0] == b"out"
    finally:
        listener.close()
    with pytest.raises(StdioRefused):
        classify(udp)
