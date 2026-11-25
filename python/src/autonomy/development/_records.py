"""Protected run identity, cross-process locks and immutable development records."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import stat
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from autonomy.baseline import ADMISSION_LOCK, EVENTS, append_event, fsync_dir, lock, publish_bytes, utc_now
from autonomy.closing import disposition_of
from autonomy.membership import Finding
from autonomy.run import EXIT_CODES, RunRefused, _xdg
from autonomy.stdio import StdioKind

MODE = "development"
REF = "refs/heads/development"
BASE_REF = "refs/heads/base"
_RUN_ID = re.compile(r"[0-9a-f]{32}")
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SUPERVISOR = "supervisor.lock"
_PUBLICATION = "publication.lock"


class DevelopmentAborted(Exception):
    """A classified post-allocation refusal to continue a development run."""

    def __init__(self, finding: Finding) -> None:
        super().__init__(f"{finding.code}: {finding.message}")
        self.finding = finding


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    run_dir: Path
    scratch: Path
    run_sha256: str
    boot_id: str


@dataclass(frozen=True)
class Terminal:
    exit: int
    disposition: str
    sha256: str
    containment_proven: bool


@dataclass(frozen=True)
class DevelopmentPlaces:
    state: Path
    cache: Path
    config: Path


def boot_id() -> str:
    value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if str(uuid.UUID(value)) != value:
        raise ValueError("boot ID is not canonical")
    return value


def development_places(env: Mapping[str, str]) -> DevelopmentPlaces:
    return DevelopmentPlaces(
        state=(_xdg(env, "XDG_STATE_HOME", ".local", "state") / "verifiably-autonomy").resolve(),
        cache=(_xdg(env, "XDG_CACHE_HOME", ".cache") / "verifiably-autonomy").resolve(),
        config=(_xdg(env, "XDG_CONFIG_HOME", ".config") / "verifiably-autonomy").resolve(),
    )


def _invalid(detail: str) -> RunRefused:
    return RunRefused("development-run-invalid", f"{detail}; resolve the recorded development run ID")


def _open_regular(path: Path) -> int:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"{path.name} is not a regular file")
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def _locked(path: Path, *, nowait: bool = False, wait: float | None = None) -> Iterator[None]:
    try:
        fd = _open_regular(path)
    except (OSError, ValueError) as caught:
        raise _invalid(f"cannot open {path.name}: {caught}") from caught
    try:
        if nowait:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as caught:
                raise RunRefused("development-supervisor-live", "the supervisor owns this run; use stop or wait") from caught
        elif wait is not None:
            deadline = time.monotonic() + max(0.0, wait)
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(f"timed out waiting for {path.name}") from None
                    time.sleep(min(0.02, remaining))
        else:
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


@contextmanager
def supervisor_lock(run: RunPaths) -> Iterator[None]:
    with _locked(run.run_dir / _SUPERVISOR, nowait=True):
        yield


@contextmanager
def publication_lock(run: RunPaths, *, wait: float | None = None) -> Iterator[None]:
    with _locked(run.run_dir / _PUBLICATION, wait=wait):
        yield


def publish_json(path: Path, value: Mapping[str, object]) -> str:
    data = (json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    publish_bytes(path, data)
    return hashlib.sha256(data).hexdigest()


def _read_bytes(path: Path) -> bytes:
    with os.fdopen(_open_regular(path), "rb") as stream:
        return stream.read()


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"duplicate JSON field {name}")
        result[name] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def _json(data: bytes) -> dict[str, object]:
    value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def read_json(path: Path) -> dict[str, object]:
    return _json(_read_bytes(path))


def _durable_parents(path: Path) -> None:
    for directory in (*reversed(path.parents), path):
        if directory == directory.parent:
            continue
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            if not directory.is_dir():
                raise
        # A concurrent first allocation may have created a directory just
        # before we entered it. Sync existing parents as well.
        fsync_dir(directory.parent)


def _valid_boot_id(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _valid_run_delegation(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != {"id", "grant_digest", "attempt"}:
        return False
    return (
        all(isinstance(value[key], str) and _ID.fullmatch(value[key]) is not None for key in ("id", "attempt"))
        and isinstance(value["grant_digest"], str)
        and _DIGEST.fullmatch(value["grant_digest"]) is not None
    )


@contextmanager
def allocate_run(
    places: DevelopmentPlaces,
    *,
    repository: Path,
    base: str,
    deadline_seconds: float,
    run_id: str | None = None,
    delegation: Mapping[str, str] | None = None,
) -> Iterator[RunPaths]:
    made: list[Path] = []
    retained = False
    try:
        chosen_id = secrets.token_hex(16) if run_id is None else run_id
        if not _RUN_ID.fullmatch(chosen_id):
            raise ValueError("invalid run ID")
        run_delegation = None if delegation is None else dict(delegation)
        if not _valid_run_delegation(run_delegation):
            raise ValueError("invalid run delegation identity")
        current_boot = boot_id()
        run_dir = places.state / "runs" / chosen_id
        scratch = places.cache / "scratch" / chosen_id
        for parent in (run_dir.parent, scratch.parent):
            _durable_parents(parent)
        with ExitStack() as lifetime:
            with lock(places.state / ADMISSION_LOCK, create=True, until=time.monotonic() + deadline_seconds):
                try:
                    for directory in (run_dir, scratch):
                        directory.mkdir(mode=0o700)
                        made.append(directory)
                        fsync_dir(directory.parent)
                    for name in (_SUPERVISOR, _PUBLICATION):
                        fd = os.open(run_dir / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
                        os.close(fd)
                    lifetime.enter_context(_locked(run_dir / _SUPERVISOR, nowait=True))
                    digest = publish_json(run_dir / "run.json", {
                        "version": 2, "run": chosen_id, "mode": MODE, "created_at": utc_now(),
                        "repository": str(repository), "base": base, "ref": REF,
                        "deadline_seconds": deadline_seconds, "scratch": str(scratch),
                        "boot_id": current_boot, "delegation": run_delegation,
                    })
                    append_event(run_dir, "allocated", run=chosen_id, mode=MODE)
                except BaseException:
                    for directory in reversed(made):
                        if directory == run_dir:
                            for name in (_SUPERVISOR, _PUBLICATION, "run.json", "events.jsonl"):
                                (directory / name).unlink(missing_ok=True)
                        directory.rmdir()
                        fsync_dir(directory.parent)
                    raise
            retained = True
            yield RunPaths(chosen_id, run_dir, scratch, digest, current_boot)
    except (OSError, ValueError, RunRefused) as caught:
        if retained:
            raise
        raise RunRefused("allocation-failed", f"cannot allocate a development run: {caught}; restore state or cache storage") from caught


def read_journal(run: RunPaths) -> tuple[dict[str, object], ...]:
    data = _read_bytes(run.run_dir / EVENTS)
    if not data.endswith(b"\n"):
        raise ValueError("empty or incomplete event journal")
    return tuple(_json(line) for line in data[:-1].split(b"\n"))


def _canonical_path(value: object) -> bool:
    return isinstance(value, str) and value.startswith("/") and os.path.normpath(value) == value


def _valid_oid(value: object) -> bool:
    return isinstance(value, str) and _OID.fullmatch(value) is not None


def _bound(value: object) -> bool:
    return type(value) in (int, float) and value > 0 and (type(value) is int or math.isfinite(value))


def lookup_run(places: DevelopmentPlaces, run_id: str) -> RunPaths:
    if not _RUN_ID.fullmatch(run_id):
        raise _invalid("invalid run ID")
    run_dir = places.state / "runs" / run_id
    scratch = places.cache / "scratch" / run_id
    try:
        if run_dir.resolve(strict=True) != run_dir or not run_dir.is_dir():
            raise ValueError("run directory is not canonical")
        data = _read_bytes(run_dir / "run.json")
        record = _json(data)
        if (
            record.get("version") != 2 or record.get("mode") != MODE or record.get("run") != run_id
            or record.get("scratch") != str(scratch) or record.get("ref") != REF
            or not _canonical_path(record.get("repository"))
            or not _valid_oid(record.get("base")) or not _bound(record.get("deadline_seconds"))
            or not _valid_boot_id(record.get("boot_id"))
            or "delegation" not in record or not _valid_run_delegation(record["delegation"])
        ):
            raise ValueError("run header identity or scope is invalid")
        return RunPaths(run_id, run_dir, scratch, hashlib.sha256(data).hexdigest(), str(record["boot_id"]))
    except (OSError, ValueError) as caught:
        raise _invalid(str(caught)) from caught


def valid_run(run_dir: Path, env: Mapping[str, str]) -> bool:
    """Whether this directory has a valid development identity under the invoking roots."""
    try:
        run = lookup_run(development_places(env), run_dir.name)
    except RunRefused:
        return False
    return run.run_dir == run_dir.resolve()


def publish_grant(
    run: RunPaths, *, base_sha256: str, walk_sha256: str, read_only: tuple[Path, ...],
    denied: tuple[Path, ...], stdio: tuple[StdioKind, StdioKind, StdioKind],
    limits: Mapping[str, int | float], delegation: Mapping[str, object] | None = None,
) -> str:
    approval = "supervised-invocation" if delegation is None else "delegation"
    record = {
        "version": 2, "run": run.run_id, "mode": MODE, "issued_at": utc_now(),
        "run_sha256": run.run_sha256, "approval": approval,
        "delegation": None if delegation is None else dict(delegation),
        "operation": "prepare-git-candidate",
        "base_sha256": base_sha256, "route": None, "allowance": None,
        "scope": {"read_only": list(map(str, read_only)), "denied": list(map(str, denied)), "walk_sha256": walk_sha256},
        "stdio": dict(zip(("stdin", "stdout", "stderr"), stdio, strict=True)), "limits": dict(limits),
    }
    try:
        return publish_json(run.run_dir / "grant.json", record)
    except (OSError, ValueError) as caught:
        raise DevelopmentAborted(Finding(
            "development-gate-unproven", "grant.json", f"cannot publish grant: {caught}; repair state storage and rerun",
        )) from caught


def _matches_digest(actual: str, expected: object, name: str) -> None:
    if not isinstance(expected, str) or not _DIGEST.fullmatch(expected) or actual != expected:
        raise ValueError(f"{name} does not match its recorded digest")


def file_digest(path: Path) -> str:
    with os.fdopen(_open_regular(path), "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _checked_json(path: Path, digest: object) -> dict[str, object]:
    data = _read_bytes(path)
    _matches_digest(hashlib.sha256(data).hexdigest(), digest, path.name)
    return _json(data)


def _delegations_agree(header: Mapping[str, object], grant: Mapping[str, object]) -> bool:
    if "delegation" not in header or "delegation" not in grant:
        return False
    run_delegation = header["delegation"]
    grant_delegation = grant["delegation"]
    if run_delegation is None:
        return grant.get("approval") == "supervised-invocation" and grant_delegation is None
    if not isinstance(run_delegation, dict) or not isinstance(grant_delegation, dict):
        return False
    return (
        grant.get("approval") == "delegation"
        and {key: grant_delegation.get(key) for key in ("id", "grant_digest", "attempt")} == run_delegation
    )


def _verify_clean(run: RunPaths, grant_sha256: object, candidate_sha256: object) -> None:
    header = _checked_json(run.run_dir / "run.json", run.run_sha256)
    grant = _checked_json(run.run_dir / "grant.json", grant_sha256)
    candidate = _checked_json(run.run_dir / "candidate.json", candidate_sha256)
    if any(record.get("version") != 2 for record in (header, grant, candidate)):
        raise ValueError("clean evidence requires version 2 records")
    base_digest = file_digest(run.run_dir / "base.bundle")
    _matches_digest(base_digest, grant.get("base_sha256"), "base.bundle")
    _matches_digest(base_digest, candidate.get("base_sha256"), "base.bundle")
    _matches_digest(file_digest(run.run_dir / "candidate.bundle"), candidate.get("bundle_sha256"), "candidate.bundle")
    scope = grant.get("scope")
    if not isinstance(scope, dict):
        raise ValueError("grant scope is missing")
    _matches_digest(file_digest(run.run_dir / "walk.json"), scope.get("walk_sha256"), "walk.json")
    if (
        any(record.get("run") != run.run_id or record.get("mode") != MODE for record in (grant, candidate))
        or grant.get("run_sha256") != run.run_sha256 or candidate.get("grant_sha256") != grant_sha256
        or not _delegations_agree(header, grant)
        or candidate.get("base") != header.get("base") or candidate.get("ref") != REF
        or not _valid_oid(candidate.get("tip")) or candidate.get("tip") == candidate.get("base")
        or type(candidate.get("actor_exit")) is not int or candidate.get("actor_exit") != 0
    ):
        raise ValueError("candidate and grant identities do not agree")


def publish_terminal(
    run: RunPaths,
    findings: Sequence[Finding],
    *,
    grant_sha256: str | None,
    candidate_sha256: str | None,
    containment_proven: bool,
) -> int:
    if type(containment_proven) is not bool:
        raise ValueError("containment_proven must be a boolean")
    disposition = disposition_of(findings)
    if disposition == "clean":
        if not containment_proven:
            raise ValueError("a clean disposition requires proven containment")
        _verify_clean(run, grant_sha256, candidate_sha256)
    else:
        candidate_sha256 = None
    publish_json(run.run_dir / "disposition.json", {
        "version": 2, "run": run.run_id, "mode": MODE, "disposition": disposition,
        "findings": [{"code": f.code, "ref": f.ref, "message": f.message} for f in findings],
        "closed_at": utc_now(), "grant_sha256": grant_sha256, "candidate_sha256": candidate_sha256,
        "containment_proven": containment_proven,
    })
    return EXIT_CODES[disposition]


def read_terminal(run: RunPaths) -> Terminal | None:
    try:
        data = _read_bytes(run.run_dir / "disposition.json")
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as caught:
        raise _invalid(str(caught)) from caught
    try:
        record = _json(data)
        disposition = record.get("disposition")
        containment_proven = record.get("containment_proven")
        if (
            record.get("version") != 2 or record.get("mode") != MODE or record.get("run") != run.run_id
            or type(containment_proven) is not bool
        ):
            raise ValueError("invalid development disposition identity")
        if disposition == "clean":
            if not containment_proven:
                raise ValueError("a clean disposition requires proven containment")
            _verify_clean(run, record.get("grant_sha256"), record.get("candidate_sha256"))
        elif record.get("candidate_sha256") is not None:
            raise ValueError("a non-clean disposition cannot link a candidate")
        status = EXIT_CODES[disposition]
        fsync_dir(run.run_dir)
        return Terminal(status, str(disposition), hashlib.sha256(data).hexdigest(), containment_proven)
    except (OSError, ValueError, KeyError, TypeError) as caught:
        raise _invalid(str(caught)) from caught


def terminal_exit(run: RunPaths) -> int | None:
    terminal = read_terminal(run)
    return None if terminal is None else terminal.exit
