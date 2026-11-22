"""Classify a closed science interval from protected records and detached reads."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import math
import os
from pathlib import Path
import re
import signal
import stat
import time

from autonomy import development
from autonomy.baseline import decode_object, fsync_dir, read_private_bytes, read_record
from autonomy.closing import SEVERITY, close as classify, disposition_of
from autonomy.egress.session import EgressClosed, kill_orphan
from autonomy.endpoint import EndpointError, SessionOpen, check_seal
from autonomy.evidence import Chain, RunEvidence
from autonomy.ledger import Ledger, LedgerUnusable, load_ledger
from autonomy.membership import Finding
from autonomy.process import ProcessIdentity, exited, send_signal
from autonomy.run import DISPOSITION, EXIT_CODES, Diag, RunRefused, RunResult, state_root, write_disposition
from autonomy.science_reads import ChainHead, Heads, ReadUnavailable, ScienceReader
from autonomy.science_run._admission import ADMISSION_LOCK, SUPERVISOR_LOCK, _journal, _no_possible_writer, lock
from autonomy.science_run._config import Config, read_config
from autonomy.tiers import Permit

_ID = re.compile(r"[0-9a-f]{32}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_ERRORS = (OSError, ValueError, KeyError, TypeError, RecursionError)
_MARGIN = 5.0


@dataclass(frozen=True)
class Baseline:
    world_root: Path
    world_id: str
    world_genesis: str
    world_tip: str
    permit: Permit
    written: tuple[ChainHead, ...]
    mounts: tuple[ChainHead, ...]


def _match(value: object, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError("invalid identity or digest in protected run record")
    return value


def _path(value: object) -> Path:
    if not isinstance(value, str) or "\0" in value:
        raise ValueError("invalid path in protected run record")
    path = Path(value)
    if path.anchor != "/" or ".." in path.parts or str(path) != value:
        raise ValueError("noncanonical path in protected run record")
    return path


def _chains(value: object) -> tuple[ChainHead, ...]:
    if not isinstance(value, dict):
        raise ValueError("invalid baseline chain list")
    chains = []
    for key, row in value.items():
        if not isinstance(row, dict) or set(row) != {"role", "root", "genesis", "tip"}:
            raise ValueError("invalid baseline chain")
        role = row["role"]
        if role not in ("store", "corpus"):
            raise ValueError("invalid baseline chain role")
        chains.append(ChainHead(role, _match(key, _ID), _path(row["root"]),
                                _match(row["genesis"], _DIGEST), _match(row["tip"], _DIGEST), ()))
    return tuple(chains)


def _baseline(run_dir: Path) -> Baseline:
    row = read_record(run_dir / "baseline.json")
    if type(row.get("version")) is not int or row["version"] != 1 or row.get("run") != run_dir.name:
        raise ValueError("baseline identity differs from run")
    written, mounts = _chains(row["written"]), _chains(row["mounts"])
    if tuple(sorted(c.role for c in written)) not in (("corpus",), ("corpus", "store")):
        raise ValueError("baseline does not identify the written chains")
    if len({c.chain_id for c in (*written, *mounts)}) != len(written) + len(mounts):
        raise ValueError("baseline contains repeated chain IDs")
    if len({c.root for c in (*written, *mounts)}) != len(written) + len(mounts):
        raise ValueError("baseline contains repeated chain roots")
    world = row["world"]
    return Baseline(_path(world["root"]), _match(world["id"], _ID), _match(world["genesis"], _DIGEST),
                    _match(world["tip"], _DIGEST), Permit.from_json(row["permit"]), written, mounts)


def _event(events: Sequence[dict], kind: str) -> dict | None:
    matches = [row for row in events if row.get("event") == kind]
    if len(matches) > 1:
        raise ValueError(f"repeated {kind} event")
    return matches[0] if matches else None


def _session(events: Sequence[dict], operations: Path) -> SessionOpen | None:
    row = _event(events, "session-open")
    if row is None:
        return None
    sid = _match(row["session_id"], _ID)
    expected = operations / "sessions" / sid / "ledger.v1"
    if _path(row["ledger_path"]) != expected or expected.resolve() != expected:
        raise ValueError("wrong ledger location for this endpoint session")
    return SessionOpen(sid, expected, _match(row["basis_open"], _DIGEST))


def trusted_seal(run_dir: Path, written: tuple[ChainHead, ...], session: SessionOpen | None,
                 ledger: Ledger | LedgerUnusable | None, events: Sequence[dict]) -> dict[str, object] | None:
    if any(row.get("event") in ("seal-timeout", "seal-failed") for row in events):
        return None
    ack = _event(events, "sealed")
    if ack is not None and session is not None:
        return check_seal(ack["seal"], written)
    if (session is None or not isinstance(ledger, Ledger) or not ledger.closed or ledger.incomplete
            or ledger.session_id != session.session_id or ledger.actor != f"session:{session.session_id}"):
        return None
    try:
        return check_seal(read_record(run_dir / "seal.json"), written)
    except _ERRORS + (EndpointError,):
        return None


def _timestamp(text: object) -> datetime:
    if not isinstance(text, str):
        raise ValueError("missing session timestamp")
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("session timestamp has no timezone")
    return value


def _later(operations: Path, ledger: Ledger | LedgerUnusable | None, world_id: str,
           events: Sequence[dict]) -> tuple[Ledger, ...]:
    try:
        boundary = _timestamp(ledger.opened_at if isinstance(ledger, Ledger) else events[0].get("at"))
        paths = sorted((operations / "sessions").iterdir())
    except (IndexError, OSError, ValueError):
        return ()
    verified = []
    for directory in paths:
        if directory.is_symlink() or not _ID.fullmatch(directory.name):
            continue
        if ledger is not None and directory.name == ledger.session_id:
            continue
        path = directory / "ledger.v1"
        if path.is_symlink() or not path.is_file():
            continue
        other = load_ledger(path, directory.name)
        if (not isinstance(other, Ledger) or other.torn_tail or other.world != world_id
                or other.actor != f"session:{directory.name}"):
            continue
        try:
            if _timestamp(other.opened_at) > boundary:
                verified.append(other)
        except ValueError:
            continue
    return tuple(verified)


def _inspect(snapshot: Baseline, metadata: Mapping[str, object], env: Mapping[str, str]) -> tuple[ScienceReader, Config, Heads | None]:
    path, operations = _path(metadata["config"]), _path(metadata["operations"])
    config = read_config(path)
    if (config.path != path or config.operations != operations or config.world_id != snapshot.world_id
            or config.world_root != snapshot.world_root):
        raise ReadUnavailable("configuration does not address the original world and operations root")
    written = {c.role: c.root for c in snapshot.written}
    if written["corpus"] != config.write_root or ("store" in written and config.store_root != written["store"]):
        raise ReadUnavailable("configuration does not address the original written roots")
    reader = ScienceReader(_path(metadata["executable"]), config.path, env=env)
    changed = config.digest != _match(metadata["config_sha256"], _DIGEST)
    config.verify()
    try:
        heads = reader.heads(resolve=False)
    except ReadUnavailable:
        config.verify()
        if changed:
            raise
        return reader, config, None
    config.verify()
    if changed:
        prior = {(c.role, c.chain_id, c.genesis, c.root) for c in (*snapshot.written, *snapshot.mounts)}
        current = {(c.role, c.chain_id, c.genesis, c.root) for c in heads.chains}
        if heads.world_genesis != snapshot.world_genesis or not prior <= current:
            raise ReadUnavailable("edited config does not identify the original chains")
    return reader, config, heads


def _evidence(
    run_dir: Path, snapshot: Baseline, metadata: Mapping[str, object], events: Sequence[dict],
    env: Mapping[str, str], findings: list[Finding],
) -> RunResult:
    operations = _path(metadata["operations"])
    session = _session(events, operations)
    ledger = load_ledger(session.ledger_path, session.session_id) if session else None
    if isinstance(ledger, Ledger) and (ledger.actor != f"session:{ledger.session_id}" or ledger.world != snapshot.world_id):
        findings.append(Finding("actor-mismatch", ledger.session_id, "ledger does not identify this run actor and world"))
        ledger = LedgerUnusable(ledger.session_id, "ledger-malformed", "wrong actor or world")
    try:
        seal = trusted_seal(run_dir, snapshot.written, session, ledger, events)
    except _ERRORS + (EndpointError,):
        findings.append(Finding("seal-failed", "seal", "invalid journaled seal"))
        seal = None
    if seal and seal["basis_seal"] is not None and session is not None and seal["basis_seal"] != session.basis_open:
        findings.append(Finding("basis-moved", "basis", "the derivation context changed between open and seal"))
    for name in ("seal-timeout", "seal-failed"):
        if any(row.get("event") == name for row in events) and not any(f.code == name for f in findings):
            findings.append(Finding(name, "endpoint", "the endpoint did not prove seal persistence"))

    try:
        reader, config, heads = _inspect(snapshot, metadata, env)
    except _ERRORS + (ReadUnavailable, RunRefused, RuntimeError):
        findings.append(Finding("read-unavailable", "config", "the original interval could not be verified"))
        return RunResult(tuple(findings), {}, None)

    baseline_raced = _event(events, "baseline-raced")
    refused_claim = baseline_raced is not None and _event(events, "actor-releasing") is None
    if refused_claim and not any(f.code == "baseline-raced" for f in findings):
        findings.append(Finding("baseline-raced", "endpoint", "the actor was held after a baseline race"))
    available = {c.chain_id: c for c in heads.chains} if heads is not None else {}
    through = {row["id"]: row["tip"] for row in seal["sealed_tips"]} if seal is not None else {}
    intervals: list[Chain] = []
    for chain in snapshot.written:
        current = available.get(chain.chain_id)
        if heads is not None and (current is None or (current.role, current.root, current.genesis) !=
                                  (chain.role, chain.root, chain.genesis)):
            intervals.append(Chain(chain.chain_id, chain.role, False, ()))
            continue
        tip = through.get(chain.chain_id) if seal is not None else (current.tip if current is not None else None)
        if tip is None:
            findings.append(Finding("read-unavailable", chain.chain_id, "the through-tip could not be established"))
            continue
        through[chain.chain_id] = tip
        if refused_claim:
            # The actor was held. This observed movement preceded the acquired claim.
            continue
        try:
            config.verify()
            interval = reader.interval(chain, after=chain.tip, through=tip)
            config.verify()
            intervals.append(interval)
        except ReadUnavailable as error:
            findings.append(Finding("read-unavailable", chain.chain_id, str(error)))

    mount_heads = {c.chain_id: available[c.chain_id].tip for c in snapshot.mounts if c.chain_id in available}
    world = heads.world_head if heads is not None else None
    if heads is not None and heads.world_genesis != snapshot.world_genesis:
        findings.append(Finding("world-moved", "world", "the world genesis changed between opening and close"))
    verdict = classify(RunEvidence(
        f"session:{session.session_id}" if session is not None else "",
        snapshot.permit, True, ledger, tuple(intervals), seal is not None,
        False, False, snapshot.world_tip, world,
        {c.chain_id: c.tip for c in snapshot.mounts}, mount_heads if heads is not None else None,
        session.basis_open if session is not None else None, seal["basis_seal"] if seal is not None else None,
        _later(operations, ledger, snapshot.world_id, events) if seal is None else (),
    ))
    members = set(verdict.members)
    grouped = {chain.chain_id: [entry.digest for entry in chain.entries if entry.digest in members] for chain in intervals}
    findings.extend(f for f in verdict.findings if not any((old.code, old.ref) == (f.code, f.ref) for old in findings))
    return RunResult(tuple(findings), grouped, {"world": world, "written": through, "mounts": mount_heads})


def collect(run_dir: Path, env: Mapping[str, str], initial: Sequence[Finding] = (), *, orphan: bool = False) -> RunResult:
    findings = list(initial)
    if orphan:
        findings.append(Finding("orchestrator-lost", "events.jsonl", "the supervisor is gone"))
    try:
        snapshot = _baseline(run_dir)
    except _ERRORS:
        findings.append(Finding("baseline-unavailable", "baseline.json", "the original baseline is unavailable"))
        return RunResult(tuple(findings), {}, None)
    try:
        return _evidence(run_dir, snapshot, read_record(run_dir / "run.json"), _journal(run_dir), env, findings)
    except _ERRORS:
        findings.append(Finding("read-unavailable", "events.jsonl", "the protected interval metadata is unavailable"))
        return RunResult(tuple(findings), {}, None)


def _identity(row: Mapping[str, object]) -> ProcessIdentity:
    return ProcessIdentity(row["pid"], row["start_time"], row["boot_id"])


def _supervisor(events: Sequence[dict], run_id: str) -> ProcessIdentity | None:
    record = _event(events, "allocated")
    if record is None:
        return None
    if record.get("run") != run_id or record.get("mode") != "science":
        raise ValueError("invalid science allocation event")
    return _identity(record)


def _terminate_recorded(row: Mapping[str, object], seconds: float, *, seal_path: Path | None = None) -> None:
    pidfd = _identity(row).pin()
    if pidfd is None:
        return
    try:
        if seal_path is not None:
            until = time.monotonic() + seconds
            while time.monotonic() < until and not seal_path.is_file():
                if exited(pidfd, min(0.1, until - time.monotonic())):
                    return
            if seal_path.is_file() and exited(pidfd, _MARGIN):
                return
        elif exited(pidfd, seconds):
            return
        send_signal(pidfd, signal.SIGKILL)
        if not exited(pidfd, _MARGIN):
            raise ValueError("cannot confirm recorded process has exited")
    finally:
        os.close(pidfd)


def _orphan_findings(run_dir: Path, meta: Mapping[str, object], events: Sequence[dict]) -> tuple[Finding, ...]:
    endpoint = _event(events, "endpoint-starting")
    if endpoint is None and not _no_possible_writer(run_dir):
        raise ValueError("cannot confirm writer absence without an endpoint identity")
    if endpoint is not None:
        seconds = meta["seal_timeout_seconds"]
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 300:
            raise ValueError("invalid recorded seal timeout")
        _terminate_recorded(endpoint, seconds + _MARGIN, seal_path=run_dir / "seal.json")
    actor = _event(events, "actor-releasing")
    if actor is not None:
        _terminate_recorded(actor, 0)
    settlements = [row for row in events if row.get("event") in ("egress-closed", "egress-close-timeout", "egress-lost")]
    if settlements:
        last = settlements[-1]
        result = EgressClosed(last.get("cause"), last.get("last_seq"), last.get("event") == "egress-close-timeout")
    else:
        result = kill_orphan(run_dir) if _event(events, "egress-proxy") is not None else None
    return result.findings() if result is not None else ()


def _terminal(run_dir: Path, emit: Callable[[str], None]) -> int | None:
    try:
        raw = read_private_bytes(run_dir / DISPOSITION)
    except FileNotFoundError:
        return None
    doc = decode_object(raw)
    if (set(doc) != {"version", "run", "disposition", "findings", "closed_at", "members", "closing_heads"}
            or type(doc["version"]) is not int or doc["version"] != 1 or doc["run"] != run_dir.name
            or not isinstance(doc["members"], dict) or not isinstance(doc["findings"], list)):
        raise ValueError("invalid stored science disposition")
    _timestamp(doc["closed_at"])
    for chain_id, entries in doc["members"].items():
        _match(chain_id, _ID)
        if not isinstance(entries, list) or len(set(entries)) != len(entries):
            raise ValueError("invalid terminal chain members")
        for digest in entries:
            _match(digest, _DIGEST)
    heads = doc["closing_heads"]
    if heads is not None:
        if not isinstance(heads, dict) or set(heads) != {"world", "written", "mounts"}:
            raise ValueError("invalid terminal closing heads")
        if heads["world"] is not None:
            _match(heads["world"], _DIGEST)
        for entries in (heads["written"], heads["mounts"]):
            if not isinstance(entries, dict):
                raise ValueError("invalid terminal chain heads")
            for chain_id, tip in entries.items():
                _match(chain_id, _ID)
                _match(tip, _DIGEST)
    findings = []
    for row in doc["findings"]:
        if (not isinstance(row, dict) or set(row) != {"code", "ref", "message"}
                or not all(isinstance(item, str) for item in row.values()) or row["code"] not in SEVERITY):
            raise ValueError("invalid stored finding")
        findings.append(Finding(row["code"], row["ref"], row["message"]))
    if doc["disposition"] != disposition_of(findings):
        raise ValueError("stored disposition disagrees with its findings")
    fsync_dir(run_dir)
    emit(raw.decode())
    return EXIT_CODES[doc["disposition"]]


def _lookup(state: Path, run_id: str) -> tuple[Path, dict[str, object]]:
    _match(run_id, _ID)
    path = state / "runs" / run_id
    if path.resolve(strict=True) != path:
        raise ValueError("run path is not canonical")
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
        raise ValueError("run path is not a private owned directory")
    try:
        meta = read_record(path / "run.json")
    except FileNotFoundError:
        if any((path / record).exists() for record in ("grant.json", "publication.lock", "candidate.json")):
            raise ValueError("run mode is ambiguous")
        return path, {}
    if (type(meta.get("version")) is not int or meta["version"] != 1 or meta.get("run") != run_id
            or meta.get("mode") not in ("science", "development")):
        raise ValueError("run identity is invalid")
    return path, meta


def control(action: str, run_id: str, env: Mapping[str, str], *, diag: Diag, emit: Callable[[str], None]) -> int:
    if action not in ("close", "stop"):
        raise ValueError("invalid run control action")
    state = state_root(env).resolve()
    try:
        _match(run_id, _ID)
        try:
            with lock(state / ADMISSION_LOCK, create=True):
                run_dir, meta = _lookup(state, run_id)
        except FileNotFoundError:
            raise RunRefused("development-run-invalid", f"run {run_id} does not exist") from None
        if meta.get("mode") == "development":
            if not development.valid_run(run_dir, env):
                raise ValueError("development run identity is damaged")
            verb = development.stop if action == "stop" else development.close
            return verb(run_id, env, diag=diag)

        if (status := _terminal(run_dir, emit)) is not None:
            return status
        events = _journal(run_dir)
        owner = _supervisor(events, run_id)
        if meta and owner is None and not _no_possible_writer(run_dir):
            raise ValueError("cannot confirm supervisor identity")
        pidfd = owner.pin() if owner is not None else None
        if pidfd is not None:
            try:
                if action == "stop":
                    send_signal(pidfd, signal.SIGTERM)
                    return 0
            finally:
                os.close(pidfd)
            raise RunRefused("run-supervisor-live", f"run {run_id} is active; use run stop")
        if action == "stop":
            raise RunRefused("run-supervisor-gone", f"run {run_id} has no live supervisor; use run close")
        with lock(run_dir / SUPERVISOR_LOCK, create=owner is None):
            if (status := _terminal(run_dir, emit)) is not None:
                return status
            events = _journal(run_dir)
            findings = _orphan_findings(run_dir, meta, events)
            result = collect(run_dir, env, findings, orphan=True)
            write_disposition(run_dir, run_id, disposition_of(result.findings), result.findings,
                              members=result.members, closing_heads=result.closing_heads)
            status = _terminal(run_dir, emit)
            if status is None:
                raise ValueError("published disposition disappeared")
            return status
    except _ERRORS as error:
        raise RunRefused("run-close-unproven", f"cannot confirm or read run {run_id}: {error}") from error
