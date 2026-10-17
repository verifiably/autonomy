"""The namespace helper (envelope design decision 13). Before the gate's release it
puts the proxy's listener on 127.0.0.1:4780 inside the actor's own network namespace,
where a loopback address is private to the actor. No process runs inside the sandbox
for it.

The helper is a separate, single-threaded `/usr/bin/python3 -I`, because joining a
user namespace needs a single-threaded process. It opens the actor's network namespace
through the init's pid and checks the init's pidfd is still alive after the open, so a
reused pid is never joined. bwrap nests a second user namespace inside the one that
owns the network namespace, so the helper joins the owner (`NS_GET_USERNS`), not the
init's own: that one gives `EPERM`. Then it joins the network namespace, binds, listens
and passes the socket back over `SCM_RIGHTS`."""

from __future__ import annotations

import socket
import subprocess

from autonomy.egress.errors import EgressUnproven

MODEL_PORT = 4780
MODEL_URL = f"http://127.0.0.1:{MODEL_PORT}"
HELPER_TIMEOUT = 10.0

HELPER = r"""
import fcntl, os, signal, socket, sys
NS_GET_USERNS = 0xB701
pid, pidfd, back, port = (int(arg) for arg in sys.argv[1:5])
if not hasattr(os, "setns"):
    sys.stderr.write("this python lacks os.setns (Python 3.12 or later is needed)\n")
    sys.exit(3)
net = os.open(f"/proc/{pid}/ns/net", os.O_RDONLY | os.O_CLOEXEC)
signal.pidfd_send_signal(pidfd, 0)
owner = fcntl.ioctl(net, NS_GET_USERNS)
os.setns(owner, os.CLONE_NEWUSER)
os.setns(net, os.CLONE_NEWNET)
listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.bind(("127.0.0.1", port))
listener.listen(64)
socket.send_fds(socket.socket(fileno=back), [b"L"], [listener.fileno()])
"""


def make_listener(child_pid: int, pidfd: int, *, port: int = MODEL_PORT, source: str = HELPER) -> socket.socket:
    here, back = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        try:
            result = subprocess.run(
                ["/usr/bin/python3", "-I", "-c", source, str(child_pid), str(pidfd), str(back.fileno()), str(port)],
                pass_fds=(pidfd, back.fileno()), stdin=subprocess.DEVNULL, capture_output=True,
                timeout=HELPER_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            raise EgressUnproven("listener-failed", f"the namespace helper did not finish in {HELPER_TIMEOUT:g} s") from None
        finally:
            back.close()
        if result.returncode != 0:
            lines = result.stderr.decode("utf-8", "replace").strip().splitlines()
            raise EgressUnproven("listener-failed", lines[-1] if lines else f"the helper exited {result.returncode}")
        here.settimeout(1.0)
        _, fds, _, _ = socket.recv_fds(here, 1, 1)
        if len(fds) != 1:
            raise EgressUnproven("listener-failed", "the helper passed back no listener")
        return socket.socket(fileno=fds[0])
    finally:
        here.close()
