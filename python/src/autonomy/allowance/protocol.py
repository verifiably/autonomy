"""Synchronous per-envelope allowance.v1 channels. One packet is one exchange."""
import socket
import threading

from . import _contract as c
from ._configuration import parse_json

VERSION = "allowance.v1"
PACKET = 16 * 1024
CODES = {"allowance-missing", "allowance-scope", "allowance-unpriced", "allowance-exhausted",
         "allowance-expired", "allowance-closed", "allowance-unavailable", "body-refused"}


def _receive(peer):
    data, _, flags, _ = peer.recvmsg(PACKET)
    if not data:
        raise EOFError
    if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
        raise ValueError("truncated frame")
    value = parse_json(data)
    if type(value) is not dict or value.get("version") != VERSION:
        raise ValueError("invalid allowance version")
    return value


def _send(peer, frame):
    data = c.canonical(frame).encode()
    if len(data) > PACKET or peer.send(data) != len(data):
        raise ValueError("unusable allowance packet")


def _settlement(role, args):
    if role == "job":
        c.keys(args, ("invocation_id", "phase", "ledger_ref", "status"))
        c.require(args["status"] in ("completed", "refused", "execution-failed", "run-cancelled", "unknown"), "job status")
        ref = args["ledger_ref"]
        if ref is None:
            c.require(args["status"] == "unknown", "missing job receipt")
        else:
            c.keys(ref, ("session_id", "invocation_id", "entry"))
            c.hexadecimal(ref["session_id"], 32)
            c.hexadecimal(ref["entry"], 64)
            c.require(args["invocation_id"] == ref["invocation_id"], "job settlement identity")
    else:
        c.keys(args, ("seq", "request_id", "message_id", "usage", "status"))
        complete = args["status"] == "complete"
        c.require(complete or args["status"] == "unknown", "model status")
        for field in ("request_id", "message_id"):
            c.require(args[field] is None or type(args[field]) is str and args[field], "invalid provider ID")
        c.require(not complete or args["message_id"] is not None, "missing message ID")
        if args["usage"] is not None or complete:
            c.keys(args["usage"], ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h"))
            for count in args["usage"].values():
                if complete or count is not None:
                    c.integer(count)


class HostPeer:
    """The host end of a role-bound socketpair. The delegate socket is handed off once."""
    def __init__(self, campaign, member, envelope, role):
        c.require(role in ("model", "job"), "invalid role")
        self._campaign, self._member, self._envelope, self._role = campaign, member, envelope, role
        self._host, self._delegate = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self._thread = threading.Thread(target=self._serve, name=f"allowance-{role}", daemon=True)
        self._thread.start()

    def take_socket(self):
        if self._delegate is None:
            raise ValueError("peer socket already transferred")
        delegate, self._delegate = self._delegate, None
        return delegate

    def _serve(self):
        previous = 0
        try:
            while True:
                row = _receive(self._host)
                if set(row) != {"version", "id", "op", "args"} or type(row["id"]) is not int or not previous < row["id"] <= c.MAXIMUM:
                    break
                previous = row["id"]
                try:
                    op, args = row["op"], row["args"]
                    c.require(isinstance(args, dict), "invalid arguments")
                    if op == "reserve-" + self._role:
                        result = self._campaign.reserve(self._member, self._envelope, self._role, args)
                    elif op == "settle-" + self._role:
                        _settlement(self._role, args)
                        result = self._campaign.settle(self._member, self._envelope, self._role, args)
                    else:
                        raise c.AllowanceRefused("allowance-scope", "operation outside channel role")
                except c.AllowanceRefused as exc:
                    result = {"result": "refused", "code": exc.code, **exc.data}
                _send(self._host, {"version": VERSION, "id": previous, **result})
        except (EOFError, OSError, ValueError, RecursionError):
            pass
        finally:
            self._host.close()

    def close(self):
        if self._delegate is not None:
            self._delegate.close()
            self._delegate = None
        try:
            self._host.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._thread.join(2)
        if self._thread.is_alive():
            raise c.AllowanceRefused("allowance-unavailable", "admission peer did not exit")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class PeerClient:
    """Serialize the proxy or endpoint's admissions and discard a desynchronized channel."""
    def __init__(self, peer):
        self._peer = peer
        self._peer.set_inheritable(False)
        self._peer.settimeout(2)
        self._lock = threading.Lock()
        self._id = 0

    def close(self):
        self._peer.close()

    def call(self, op, args):
        with self._lock:
            self._id += 1
            try:
                _send(self._peer, {"version": VERSION, "id": self._id, "op": op, "args": args})
                reply = _receive(self._peer)
                correlation = reply.pop("id", None)
                if type(correlation) is not int or correlation != self._id:
                    raise ValueError("invalid correlation ID")
                # Check the echoed ID independently of durable ticket identity.
                return self._reply(reply, op)
            except (ValueError, TypeError, OSError, EOFError, KeyError, RecursionError):
                self.close()
                raise c.AllowanceRefused("allowance-unavailable", "invalid or missing admission reply") from None

    def _reply(self, reply, op):
        del reply["version"]
        kind = reply.get("result")
        if kind == "refused":
            code = reply.get("code")
            fields = {"result", "code"}
            if "remaining" in reply:
                fields.add("remaining")
                if type(reply["remaining"]) is not dict or set(reply["remaining"]) != set(c.DIMENSIONS) or any(
                    type(v) is not int or not 0 <= v <= c.MAXIMUM for v in reply["remaining"].values()
                ):
                    raise ValueError("invalid remaining units")
            if code == "allowance-exhausted":
                fields.add("dimension")
                if reply.get("dimension") not in c.DIMENSIONS:
                    raise ValueError("missing exhausted dimension")
            if code not in CODES or set(reply) != fields:
                raise ValueError("invalid refusal")
            raise c.AllowanceRefused(code, reply.get("dimension", "admission refused"),
                                     **{key: reply[key] for key in fields - {"result", "code"}})
        if op.startswith("reserve-"):
            if reply == {"result": "admitted"} or (set(reply) == {"result", "state"}
                    and kind == "already-recorded" and reply["state"] in ("settled", "reserved")):
                return reply
        elif reply == {"result": "settled"}:
            return reply
        raise ValueError("unexpected result")
