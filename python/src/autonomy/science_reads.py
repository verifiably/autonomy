"""Strict subprocess reader for science's heads.v1 and log.v1 evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from typing import Literal, cast

from autonomy.evidence import Chain, Entry, Intent, Registration, Settlement
from autonomy.process import ProcessIdentity, ProcessSurvived, send_signal, spawn_recorded

__all__ = ["ChainHead", "Heads", "ReadUnavailable", "ScienceReader", "has_handle"]

Role = Literal["corpus", "store"]
Pending = tuple[tuple[str, str], ...]
_HANDLES = ("VERIFIABLY_ENDPOINT", "VERIFIABLY_TOKEN_FILE")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[0-9a-f]{32}")
_TXID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_TRAILER = re.compile(r"\n… truncated at [1-9][0-9]* bytes; continue with cursor (scur1\.[A-Za-z0-9_-]+)\n\Z")
_STATES = {
    "absent": ("kind",),
    "file": ("kind", "content_hash", "mode", "byte_len"),
    "directory": ("kind", "mode"),
    "symlink": ("kind", "target", "mode"),
}
_HOLDINGS_ACTS = {"write", "tree-write", "delete", "move-source", "move-destination", "re-check"}


@dataclass(frozen=True)
class ChainHead:
    role: Role
    chain_id: str
    root: Path
    genesis: str
    tip: str
    pending: Pending


@dataclass(frozen=True)
class Heads:
    world_genesis: str
    world_head: str
    world_pending: Pending
    chains: tuple[ChainHead, ...]


class ReadUnavailable(Exception):
    """The command could not prove the requested evidence."""


class _TipNotOnChain(Exception):
    pass


def has_handle(env: Mapping[str, str]) -> bool:
    return any(name in env for name in _HANDLES)


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ReadUnavailable("duplicate field in science evidence")
    return value


def _rows(text: str) -> list[dict[str, object]]:
    if not text.endswith("\n"):
        raise ReadUnavailable("science evidence has no complete final row")
    try:
        rows = [json.loads(line, object_pairs_hook=_object) for line in text[:-1].split("\n")]
    except (ValueError, RecursionError) as error:
        raise ReadUnavailable("invalid science evidence JSON") from error
    if any(type(row) is not dict for row in rows):
        raise ReadUnavailable("science evidence rows must be objects")
    return rows


def _fields(row: dict, required: str) -> None:
    if set(row) != set(required.split()):
        raise ReadUnavailable("wrong fields in science evidence row")


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ReadUnavailable("science evidence requires a nonempty string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ReadUnavailable("science evidence string is not UTF-8") from error
    return value


def _matches(value: object, pattern: re.Pattern[str]) -> str:
    token = _text(value)
    if not pattern.fullmatch(token):
        raise ReadUnavailable("invalid identifier in science evidence")
    return token


def _pending(value: object) -> Pending:
    if not isinstance(value, list):
        raise ReadUnavailable("invalid pending transactions")
    pairs = []
    for row in value:
        if not isinstance(row, list) or len(row) != 2:
            raise ReadUnavailable("invalid pending transaction pair")
        pairs.append((_matches(row[0], _TXID), _matches(row[1], _DIGEST)))
    if len({txid for txid, _ in pairs}) != len(pairs):
        raise ReadUnavailable("duplicate pending transaction")
    return tuple(pairs)


def _chain_head(row: object) -> ChainHead:
    if not isinstance(row, dict):
        raise ReadUnavailable("chain head must be an object")
    _fields(row, "role id root genesis tip pending")
    role = row["role"]
    if role not in ("corpus", "store"):
        raise ReadUnavailable("unrecognized chain role")
    root_text = _text(row["root"])
    root = Path(root_text)
    if not root.is_absolute() or root.anchor != "/" or ".." in root.parts or str(root) != root_text:
        raise ReadUnavailable("chain root is not canonical")
    return ChainHead(cast(Role, role), _matches(row["id"], _ID), root, _matches(row["genesis"], _DIGEST),
                     _matches(row["tip"], _DIGEST), _pending(row["pending"]))


def _bare_path(value: object) -> str:
    path = _text(value)
    if any(part in {"", ".", ".."} for part in path.split("/")):
        raise ReadUnavailable("registration path is not a bare relative path")
    return path


def _surface_paths(surface: object) -> tuple[str, ...]:
    if not isinstance(surface, list):
        raise ReadUnavailable("registration surface must be a list")
    paths = []
    for row in surface:
        if not isinstance(row, list) or len(row) != 2 or not isinstance(row[1], list):
            raise ReadUnavailable("invalid registration path/state pair")
        path, state = row
        paths.append(_bare_path(path))
        _validate_state(state)
    if sorted(set(paths)) != paths:
        raise ReadUnavailable("registration surface is unordered or contains duplicates")
    return tuple(paths)


def _validate_state(state: list) -> None:
    if any(not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(v, str) for v in pair)
           for pair in state):
        raise ReadUnavailable("invalid path state facts")
    facts = dict(state)
    if tuple(key for key, _ in state) != _STATES.get(facts.get("kind")):
        raise ReadUnavailable("unknown or malformed path state")
    if "mode" in facts:
        _matches(facts["mode"], re.compile(r"0o(?:0|[1-7][0-7]{0,3})"))
    if facts["kind"] == "file":
        digest = _matches(facts["content_hash"], _DIGEST)
        length = _matches(facts["byte_len"], re.compile(r"0|[1-9][0-9]{0,18}"))
        if int(length) >= 2**63 or (length == "0") != (digest == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"):
            raise ReadUnavailable("invalid file length and digest")
    if facts["kind"] == "symlink":
        _text(facts["target"])


def _entry(row: dict) -> Entry:
    digest = _matches(row.get("digest"), _DIGEST)
    match row.get("type"):
        case "intent":
            if row.get("kind") == "holdings":
                _fields(row, "type digest actor kind holdings_act store_id location")
                act = _text(row["holdings_act"])
                if act not in _HOLDINGS_ACTS:
                    raise ReadUnavailable("unrecognized holdings act")
                store_id = None if row["store_id"] is None else _matches(row["store_id"], _ID)
                location = _text(row["location"])
                if act == "tree-write":
                    _matches(location, _DIGEST)
                elif store_id is not None and (act != "re-check" or not _DIGEST.fullmatch(location)):
                    _bare_path(location)
                return Intent(digest, _text(row["actor"]), "holdings", act, location, store_id)
            _fields(row, "type digest actor kind")
            actor = None if row["actor"] is None else _text(row["actor"])
            kind = None if row["kind"] is None else _text(row["kind"])
            return Intent(digest, actor, kind, None, None)
        case "registration":
            _fields(row, "type digest txid fulfills consumer_tag initial final")
            fulfills = None if row["fulfills"] is None else _matches(row["fulfills"], _DIGEST)
            tag = None if row["consumer_tag"] is None else _text(row["consumer_tag"])
            initial, final = _surface_paths(row["initial"]), _surface_paths(row["final"])
            return Registration(digest, _matches(row["txid"], _TXID), fulfills, tag, frozenset((*initial, *final)))
        case "settlement":
            _fields(row, "type digest txid registration committed")
            if type(row["committed"]) is not bool:
                raise ReadUnavailable("settlement outcome must be boolean")
            return Settlement(digest, _matches(row["txid"], _TXID), _matches(row["registration"], _DIGEST),
                              row["committed"])
        case _:
            raise ReadUnavailable("unrecognized log entry type")


def _refusal(result: subprocess.CompletedProcess[str], command: str, *, first_page: bool) -> None:
    try:
        rows = _rows(result.stderr)
        refusal = rows[0]["refusal"] if len(rows) == 1 else None
        if not isinstance(refusal, dict):
            raise ReadUnavailable("no structured refusal")
        _fields(refusal, "code message data")
        code = _text(refusal["code"])
        _text(refusal["message"])
        if not isinstance(refusal["data"], dict):
            raise ReadUnavailable("invalid refusal data")
    except (KeyError, ReadUnavailable) as error:
        raise ReadUnavailable(f"science {command} exited {result.returncode}") from error
    if (first_page and command == "log" and result.returncode == 3 and not result.stdout
            and code == "tip-unknown" and refusal["data"].get("reason") == "tip-not-on-chain"):
        raise _TipNotOnChain
    raise ReadUnavailable(f"science {command} refused: {code}")


def _recorded_read(
    argv: list[str], env: Mapping[str, str], record: Callable[[ProcessIdentity], None], deadline: float,
) -> subprocess.CompletedProcess[str]:
    child, pidfd = spawn_recorded(argv, env=env, record=record, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
    try:
        stdout, stderr = child.communicate(timeout=max(0, deadline - time.monotonic()))
        return subprocess.CompletedProcess(argv, child.returncode, stdout, stderr)
    except BaseException:
        send_signal(pidfd, signal.SIGKILL)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired as error:
            raise ProcessSurvived("resolving science read did not exit") from error
        raise
    finally:
        os.close(pidfd)
        child.stdout.close()
        child.stderr.close()


class ScienceReader:
    """Detached or resolving operator reads from one configured executable."""

    def __init__(self, executable: Path, config: Path, *, env: Mapping[str, str], timeout: float = 30.0) -> None:
        if has_handle(env):
            raise ReadUnavailable("operator evidence unavailable with a science handle")
        if not executable.is_absolute() or not config.is_absolute():
            raise ValueError("science executable and config must be absolute")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("science read timeout must be positive and finite")
        self.executable = executable
        self.config = config
        self._env = dict(env)
        self._timeout = timeout

    def _read(self, command: str, *args: str, until: float | None = None,
              record: Callable[[ProcessIdentity], None] | None = None) -> list[dict[str, object]]:
        base = [str(self.executable), command, "--config", str(self.config), *args]
        deadline = time.monotonic() + self._timeout
        if until is not None:
            deadline = min(deadline, until)
        seen: set[str] = set()
        fragments: list[str] = []
        cursor: str | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReadUnavailable(f"science {command} timed out")
            argv = [*base, "--continue", cursor] if cursor is not None else base
            try:
                if record is None:
                    result = subprocess.run(argv, env=self._env, stdin=subprocess.DEVNULL, capture_output=True,
                                            encoding="utf-8", timeout=remaining)
                else:
                    result = _recorded_read(argv, self._env, record, deadline)
            except (OSError, UnicodeError, subprocess.TimeoutExpired) as error:
                raise ReadUnavailable(f"science {command} failed: {type(error).__name__}") from error
            if result.returncode != 0:
                _refusal(result, command, first_page=cursor is None)
            trailer = _TRAILER.search(result.stdout)
            if trailer is None:
                fragments.append(result.stdout)
                return _rows("".join(fragments))
            cursor = trailer[1]
            if cursor in seen or not trailer.start():
                raise ReadUnavailable(f"science {command} did not advance the continuation")
            seen.add(cursor)
            fragments.append(result.stdout[:trailer.start()])

    def heads(self, *, resolve: bool, until: float | None = None,
              record: Callable[[ProcessIdentity], None] | None = None) -> Heads:
        rows = self._read("heads", *(("--resolve",) if resolve else ()), until=until, record=record)
        if len(rows) != 1:
            raise ReadUnavailable("heads must contain exactly one row")
        row = rows[0]
        _fields(row, "version world_genesis world_head world_pending chains")
        if row["version"] != "heads.v1" or not isinstance(row["chains"], list):
            raise ReadUnavailable("unrecognized heads version or chain list")
        chains = tuple(_chain_head(chain) for chain in row["chains"])
        if len({(c.role, c.chain_id) for c in chains}) != len(chains) or len({c.root for c in chains}) != len(chains):
            raise ReadUnavailable("duplicate chain identity or root")
        return Heads(_matches(row["world_genesis"], _DIGEST), _matches(row["world_head"], _DIGEST),
                     _pending(row["world_pending"]), chains)

    def interval(self, chain: ChainHead, *, after: str, through: str) -> Chain:
        _matches(after, _DIGEST)
        _matches(through, _DIGEST)
        selector = "store" if chain.role == "store" else chain.chain_id
        try:
            header, *rows = self._read("log", "--chain", selector, "--after", after, "--through", through)
        except _TipNotOnChain:
            return Chain(chain.chain_id, chain.role, False, ())
        if header != {"version": "log.v1", "role": chain.role, "id": chain.chain_id, "root": str(chain.root),
                      "genesis": chain.genesis, "after": after, "through": through}:
            raise ReadUnavailable("log header does not match the requested interval")
        entries = tuple(_entry(row) for row in rows)
        digests = {entry.digest for entry in entries}
        if len(digests) != len(entries) or after in digests or (entries[-1].digest if entries else after) != through:
            raise ReadUnavailable("log entries do not match the requested through-tip")
        return Chain(chain.chain_id, chain.role, True, entries)
