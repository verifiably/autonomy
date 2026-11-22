import os
import signal
import socket
import subprocess
import textwrap
import time

import pytest

from autonomy.egress.errors import EgressUnproven
from autonomy.egress import helper
from autonomy.egress.helper import HELPER, MODEL_PORT, make_listener
from autonomy.sandbox.bwrap import launch
from autonomy.sandbox.spec import SandboxSpec

pytestmark = pytest.mark.bwrap

CLIENT = textwrap.dedent(f"""
    import socket
    with socket.create_connection(("127.0.0.1", {MODEL_PORT}), timeout=10) as s:
        s.sendall(b"ping")
        print(s.recv(16).decode(), flush=True)
""")


def test_the_listener_lives_in_the_actors_network_namespace(tmp_path):
    held = {}
    # The test closes the listener at the end: it holds the actor's network namespace.

    def hook(child_pid, pidfd):
        held["listener"] = make_listener(child_pid, pidfd)

    out_read, out_write = os.pipe()
    null = os.open(os.devnull, os.O_RDWR)
    sandbox = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/python3", "-I", "-c", CLIENT],
                     stdin=null, stdout=out_write, stderr=null, before_release=hook)
    os.close(out_write)
    try:
        listener = held["listener"]
        listener.settimeout(10)
        conn, _ = listener.accept()
        assert conn.recv(16) == b"ping"
        conn.sendall(b"pong")
        conn.close()
        assert sandbox.wait(timeout=30) == 0
        assert os.read(out_read, 64).strip() == b"pong"
    finally:
        sandbox.close()
        os.close(out_read)
        os.close(null)
        if "listener" in held:
            held["listener"].close()
    with pytest.raises(ConnectionRefusedError):  # the host's own loopback has nothing there
        socket.create_connection(("127.0.0.1", MODEL_PORT), timeout=2)


def hold_and_try(tmp_path, attempt):
    """Launch a sleeper whose release hook runs `attempt(child_pid, pidfd)`."""
    null = os.open(os.devnull, os.O_RDWR)
    try:
        with pytest.raises(EgressUnproven) as caught:
            launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/sleep", "30"],
                   stdin=null, stdout=null, stderr=null, before_release=attempt)
    finally:
        os.close(null)
    return caught.value


def test_joining_the_inits_own_user_namespace_is_refused(tmp_path):
    # Negative: bwrap nests a user namespace inside the one that owns the network, so
    # joining the init's own gets EPERM at the network join (docs/egress.md, NS_GET_USERNS).
    wrong = HELPER.replace("fcntl.ioctl(net, NS_GET_USERNS)", 'os.open(f"/proc/{pid}/ns/user", os.O_RDONLY)')
    assert wrong != HELPER
    error = hold_and_try(tmp_path, lambda child, pidfd: make_listener(child, pidfd, source=wrong))
    assert error.code == "listener-failed" and "Operation not permitted" in error.message


def test_a_dead_init_is_refused(tmp_path):
    def kill_first(child, pidfd):
        signal.pidfd_send_signal(pidfd, signal.SIGKILL)
        time.sleep(0.5)  # its namespaces are released when it exits
        make_listener(child, pidfd)

    assert hold_and_try(tmp_path, kill_first).code == "listener-failed"


def test_a_pidfd_that_no_longer_names_the_init_is_refused(tmp_path):
    # The helper checks the pidfd after opening the namespace by pid, so a reused pid
    # is never joined: a stale pidfd is refused even while the pid's /proc entry exists.
    gone = subprocess.Popen(["/usr/bin/true"])
    stale = os.pidfd_open(gone.pid)
    gone.wait()
    try:
        error = hold_and_try(tmp_path, lambda child, pidfd: make_listener(child, stale))
    finally:
        os.close(stale)
    assert error.code == "listener-failed" and "ProcessLookupError" in error.message


def test_the_helper_gets_stdin_from_dev_null(monkeypatch):  # Helper stdin is /dev/null
    seen = {}

    def spy(argv, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(argv, 0)

    monkeypatch.setattr(helper.subprocess, "run", spy)
    with pytest.raises(EgressUnproven):
        make_listener(1, 0)
    assert seen["stdin"] is subprocess.DEVNULL


def test_helper_returns_a_close_on_exec_listener():
    source = """import socket, sys
back = socket.socket(fileno=int(sys.argv[3]))
listener = socket.socket()
listener.bind(("127.0.0.1", 0))
listener.listen()
socket.send_fds(back, [b"L"], [listener.fileno()])
"""
    with os.fdopen(os.open(os.devnull, os.O_RDONLY)) as placeholder:
        with make_listener(1, placeholder.fileno(), source=source) as listener:
            assert not os.get_inheritable(listener.fileno())


def test_proxy_receives_close_on_exec_descriptors():
    from autonomy.egress.proxy import receive_message, send_message

    with os.fdopen(os.open(os.devnull, os.O_RDONLY)) as payload:
        sender, receiver = socket.socketpair()
        with sender, receiver:
            send_message(sender, {"op": "listener"}, [payload.fileno()])
            message, fds = receive_message(receiver)
            try:
                assert message == {"op": "listener"} and len(fds) == 1
                assert not os.get_inheritable(fds[0])
            finally:
                for fd in fds:
                    os.close(fd)
