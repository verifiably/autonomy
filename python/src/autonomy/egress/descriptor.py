"""Receive egress control descriptors with close-on-exec set by the kernel."""

from array import array
import socket


def receive_fds(stream: socket.socket, size: int) -> tuple[bytes, list[int]]:
    fds = array("i")
    data, ancillary, _, _ = stream.recvmsg(size, socket.CMSG_LEN(fds.itemsize), socket.MSG_CMSG_CLOEXEC)
    for level, kind, raw in ancillary:
        if (level, kind) == (socket.SOL_SOCKET, socket.SCM_RIGHTS):
            fds.frombytes(raw[:len(raw) - len(raw) % fds.itemsize])
    return data, list(fds)
