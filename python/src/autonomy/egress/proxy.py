"""The model proxy's process (envelope design decision 13). `autonomy.egress.session`
starts it in its own bwrap as
`/usr/bin/python3 -I -c BOOT <package parent> <control fd> <records fd>`.

Its main thread is the control thread. It waits on the control socket, the SIGTERM
wake-up pipe and the lease's deadline. On the first of these it returns a cause, and
`main` takes the close transition, which waits on nothing but the gate's lock."""

from __future__ import annotations

import base64
import json
import os
import re
import select
import signal
import socket
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from autonomy.egress.errors import EgressUnproven, RouteRefused
from autonomy.egress.route import parse_route
from autonomy.egress.server import ProxyServer, Recorder
from autonomy.egress.upstream import tls_context

BOOT = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "from autonomy.egress.proxy import main; raise SystemExit(main(sys.argv[2:]))"
)
IN_SANDBOX_CREDENTIAL = Path("/run/va/credential")
IN_SANDBOX_CA = Path("/run/va/ca.pem")
MAX_MESSAGE = 1 << 20
_VISIBLE = re.compile(r"[\x21-\x7e]+")


def read_credential(path: Path) -> str:
    """One line of visible ASCII. One trailing newline is allowed, as `echo key > file`
    writes it; anything else could corrupt the upstream request's headers."""
    data = path.read_bytes()
    text = data[:-1] if data.endswith(b"\n") else data
    try:
        value = text.decode("ascii")
    except UnicodeDecodeError:
        raise EgressUnproven("credential-invalid", "the credential is not ASCII") from None
    if not _VISIBLE.fullmatch(value):
        raise EgressUnproven("credential-invalid", "the credential must be one line of visible ASCII")
    return value


def send_message(control: socket.socket, message: dict, fds: Iterable[int] = ()) -> None:
    """Never blocks: a reply the peer cannot take is dropped, and the peer's own wait
    bounds what it costs."""
    data = json.dumps(message).encode()
    fds = list(fds)
    try:
        if fds:
            socket.send_fds(control, [data], fds, socket.MSG_DONTWAIT)
        else:
            control.send(data, socket.MSG_DONTWAIT)
    except OSError:
        pass


def receive_message(control: socket.socket) -> tuple[dict | None, list[int]]:
    data, fds, _, _ = socket.recv_fds(control, MAX_MESSAGE, 1)
    if not data:
        for fd in fds:
            os.close(fd)
        return None, []
    return json.loads(data), fds


def control_loop(
    server: ProxyServer, control: socket.socket, wake: int, lease: float, *, clock: Callable[[], float] = time.monotonic,
) -> str:
    """Serve the control socket until a close cause: `close`, `lease`, `eof` or `term`.
    The lease is the proxy's own deadline, renewed only by `renew` (spec §8)."""
    deadline = clock() + lease
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            return "lease"
        ready, _, _ = select.select([control, wake], [], [], min(remaining, 3600.0))
        if wake in ready:
            return "term"
        if control not in ready:
            continue
        message, fds = receive_message(control)
        if message is None:
            return "eof"
        op = message.get("op")
        if op == "listener" and len(fds) == 1:
            if server.serve(socket.socket(fileno=fds[0])):
                send_message(control, {"op": "listening"})
            else:
                send_message(control, {"op": "error", "code": "listener-failed", "message": "the accept thread could not start"})
        elif op == "renew":
            deadline = clock() + lease
        elif op == "close":
            return "close"
        else:
            for fd in fds:
                os.close(fd)


def main(argv: list[str]) -> int:
    wake_read, wake_write = os.pipe()
    os.set_blocking(wake_write, False)
    signal.set_wakeup_fd(wake_write)
    signal.signal(signal.SIGTERM, lambda signum, frame: None)
    control = socket.socket(fileno=int(argv[0]))
    records = int(argv[1])
    message, _ = receive_message(control)
    if message is None or message.get("op") != "route":
        return 2
    try:
        route = parse_route(base64.b64decode(message["route"]))
        credential = read_credential(IN_SANDBOX_CREDENTIAL)
    except (RouteRefused, EgressUnproven) as caught:
        send_message(control, {"op": "error", "code": caught.code, "message": caught.message})
        return 3
    except OSError as caught:
        send_message(control, {"op": "error", "code": "credential-unreadable", "message": str(caught)})
        return 3
    try:
        context = tls_context(IN_SANDBOX_CA if route.ca_file is not None else None)
    except OSError as caught:
        send_message(control, {"op": "error", "code": "ca-unreadable", "message": str(caught)})
        return 3
    server = ProxyServer(route, credential, Recorder(records), context=context, run=str(message.get("run", "")))
    send_message(control, {"op": "ready"})
    cause = control_loop(server, control, wake_read, float(message["lease"]))
    server.close(cause)
    send_message(control, {"op": "closed", "cause": cause, "last_seq": server.gate.last_seq})
    return 0
