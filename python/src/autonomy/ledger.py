"""An independent reader of the kernel's session ledger, `ledger.v1` (envelope
design §4, §9; decision 10).

autonomy imports no kernel, so this reads the published format itself: canonical
JSON lines, `session-open` first, nothing after `session-close`. It never raises on
ledger content: a ledger it cannot use comes back as `LedgerUnusable`, which the
closing check turns into a finding.
"""

from __future__ import annotations

import json
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


@dataclass(frozen=True)
class Ledger:
    session_id: str
    actor: str
    permit: Permit
    acts: tuple[ActLine, ...]
    open_invocations: tuple[str, ...]
    closed: bool
    torn_tail: bool

    @property
    def incomplete(self) -> bool:
        """Spec §9: only an incomplete ledger can explain a missing act line."""
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
    opened: list[str] = []
    closed_invocations: set[str] = set()
    session_closed = False
    for number, chunk in enumerate(chunks, start=1):
        if chunk.endswith(b"\r"):
            raise _Malformed(f"line {number}: a CRLF line ending")
        try:
            parsed = json.loads(chunk.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError) as caught:
            raise _Malformed(f"line {number}: not JSON: {type(caught).__name__}") from caught
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
            opened.append(invocation)
            continue
        if invocation not in opened:
            raise _Malformed(f"line {number}: {kind} names invocation {invocation!r}, never opened")
        if invocation in closed_invocations:
            raise _Malformed(f"line {number}: {kind} names invocation {invocation!r}, already closed")
        if kind == "invocation-close":
            closed_invocations.add(invocation)
        elif kind == "act":
            acts.append(
                ActLine(
                    invocation,
                    _hex(parsed["corpus"], 32, f"line {number}: corpus id"),
                    _hex(parsed["entry"], 64, f"line {number}: entry digest"),
                    _hex(parsed["intent"], 64, f"line {number}: intent digest"),
                )
            )
    assert head is not None  # line 1 was checked above
    try:
        permit = Permit.from_json(head["permit"])
    except ValueError as caught:
        raise _Malformed(f"line 1: {caught}") from caught
    return Ledger(
        session_id=session_id,
        actor=_text(head["actor"], "line 1: actor"),
        permit=permit,
        acts=tuple(acts),
        open_invocations=tuple(i for i in opened if i not in closed_invocations),
        closed=session_closed,
        torn_tail=torn_tail,
    )
