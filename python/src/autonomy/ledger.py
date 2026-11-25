"""An independent reader of the kernel's session ledger, `ledger.v1` (docs/records.md).

autonomy imports no kernel, so this reads the published format itself: canonical
JSON lines, `session-open` first, nothing after `session-close`. It never raises on
ledger content: a ledger it cannot use comes back as `LedgerUnusable`, which the
closing check turns into a finding.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from autonomy.tiers import Permit

_KEYS: dict[str, frozenset[str]] = {
    "session-open": frozenset({"line", "session", "actor", "world", "permit", "at"}),
    "invocation-open": frozenset({"line", "invocation", "command", "input_digest", "at"}),
    "act": frozenset({"line", "invocation", "corpus", "entry", "intent", "records"}),
    "invocation-close": frozenset({"line", "invocation", "outcome"}),
    "session-close": frozenset({"line", "at"}),
    "select": frozenset({"line", "invocation", "project"}),
}
_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class ActLine:
    invocation: str
    corpus: str
    entry: str
    intent: str
    records: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Invocation:
    invocation: str
    command: str
    input_digest: str
    outcome: dict | None


@dataclass(frozen=True)
class Ledger:
    session_id: str
    actor: str
    permit: Permit
    acts: tuple[ActLine, ...]
    open_invocations: tuple[str, ...]
    closed: bool
    torn_tail: bool
    world: str | None = None
    opened_at: str | None = None
    invocations: tuple[Invocation, ...] = ()

    @property
    def incomplete(self) -> bool:
        """Only an incomplete ledger can explain a missing act line."""
        return self.torn_tail or bool(self.open_invocations) or not self.closed


@dataclass(frozen=True)
class LedgerUnusable:
    session_id: str
    code: str
    message: str


class _Malformed(Exception):
    pass


def _hex(value: object, width: int, what: str) -> str:
    if type(value) is not str or len(value) != width or not set(value) <= _HEX:
        raise _Malformed(f"{what} must be {width} lowercase hexadecimal characters")
    return value


def _text(value: object, what: str) -> str:
    if type(value) is not str or not value:
        raise _Malformed(f"{what} must be a non-empty string")
    return value


def _pairs(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or any(
        not isinstance(pair, list) or len(pair) != 2 for pair in value
    ):
        raise _Malformed("expected ordered record pairs")
    return tuple((_text(uid, "record uid"), _text(address, "record id")) for uid, address in value)


def _outcome(value: object) -> dict:
    if isinstance(value, dict) and set(value) == {"done"}:
        _pairs(value["done"])
        return value
    if isinstance(value, dict) and set(value) == {"refusal"}:
        reason = value["refusal"]
        if (isinstance(reason, dict) and set(reason) == {"code", "message", "data"}
                and isinstance(reason["message"], str) and isinstance(reason["data"], dict)):
            _text(reason["code"], "refusal code")
            return value
    raise _Malformed("invalid invocation outcome")


def read_ledger(session_id: str, raw: bytes) -> Ledger | LedgerUnusable:
    try:
        return _parse(session_id, raw)
    except _Malformed as caught:
        return LedgerUnusable(session_id, "ledger-malformed", str(caught))


def load_ledger(path: Path, session_id: str) -> Ledger | LedgerUnusable:
    try:
        raw = path.read_bytes()
    except OSError as caught:
        return LedgerUnusable(session_id, "ledger-unavailable", f"{path.name}: {caught.strerror}")
    return read_ledger(session_id, raw)


def _parse(session_id: str, raw: bytes) -> Ledger:
    if not raw:
        raise _Malformed("the ledger is empty; no session-open")
    torn_tail = not raw.endswith(b"\n")
    chunks = raw.split(b"\n")[:-1]  # the last piece is empty after a newline, or the torn tail
    if not chunks:
        raise _Malformed("no complete line; no session-open")
    head: dict[str, object] | None = None
    acts: list[ActLine] = []
    opened: dict[str, tuple[str, str]] = {}
    closed_invocations: dict[str, dict] = {}
    session_closed = False
    for number, chunk in enumerate(chunks, start=1):
        if chunk.endswith(b"\r"):
            raise _Malformed(f"line {number}: a CRLF line ending")
        try:
            parsed = json.loads(chunk.decode("utf-8"))
            canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                   allow_nan=False).encode("utf-8")
        except (ValueError, RecursionError) as caught:
            raise _Malformed(f"line {number}: not JSON: {type(caught).__name__}") from caught
        if canonical != chunk:
            raise _Malformed(f"line {number}: not canonical JSON")
        if not isinstance(parsed, dict):
            raise _Malformed(f"line {number}: not a JSON object")
        kind = parsed.get("line")
        if type(kind) is not str or kind not in _KEYS:  # an unhashable discriminator must not raise
            raise _Malformed(f"line {number}: unknown line kind {kind!r}")
        expected = _KEYS[kind] | ({"project"} if kind == "session-open" and "project" in parsed else set())
        if set(parsed) != expected:
            raise _Malformed(f"line {number}: {kind} carries exactly {sorted(expected)}")
        if session_closed:
            raise _Malformed(f"line {number}: a line after session-close")
        if number == 1:
            if kind != "session-open":
                raise _Malformed("line 1 is not session-open")
            if _hex(parsed["session"], 32, "session id") != session_id:
                raise _Malformed(f"line 1 names session {parsed['session']}, not {session_id}")
            head = parsed
            continue
        if kind == "session-open":
            raise _Malformed(f"line {number}: a second session-open")
        if kind == "session-close":
            session_closed = True
            continue
        invocation = _text(parsed["invocation"], f"line {number}: invocation")
        if kind == "invocation-open":
            if invocation in opened:
                raise _Malformed(f"line {number}: invocation {invocation!r} is already open")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", invocation):
                raise _Malformed("invalid invocation identifier")
            opened[invocation] = _text(parsed["command"], "command"), _hex(parsed["input_digest"], 64, "input digest")
            continue
        if invocation not in opened:
            raise _Malformed(f"line {number}: {kind} names invocation {invocation!r}, never opened")
        if invocation in closed_invocations:
            raise _Malformed(f"line {number}: {kind} names invocation {invocation!r}, already closed")
        if kind == "invocation-close":
            closed_invocations[invocation] = _outcome(parsed["outcome"])
        elif kind == "act":
            acts.append(
                ActLine(
                    invocation,
                    _hex(parsed["corpus"], 32, f"line {number}: corpus id"),
                    _hex(parsed["entry"], 64, f"line {number}: entry digest"),
                    _hex(parsed["intent"], 64, f"line {number}: intent digest"),
                    _pairs(parsed["records"]),
                )
            )
    assert head is not None  # line 1 was checked above
    try:
        permit = Permit.from_json(head["permit"])
    except ValueError as caught:
        raise _Malformed(f"line 1: {caught}") from caught
    return Ledger(
        session_id=session_id,
        invocations=tuple(Invocation(i, command, digest, closed_invocations.get(i)) for i, (command, digest) in opened.items()),
        actor=_text(head["actor"], "line 1: actor"),
        permit=permit,
        acts=tuple(acts),
        open_invocations=tuple(i for i in opened if i not in closed_invocations),
        closed=session_closed,
        torn_tail=torn_tail,
        world=head["world"] if isinstance(head["world"], str) else None,
        opened_at=head["at"] if isinstance(head["at"], str) else None,
    )
