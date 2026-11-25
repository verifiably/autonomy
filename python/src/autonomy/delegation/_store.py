"""One host-private SQLite file per issued development delegation."""
from __future__ import annotations

import os
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

from autonomy.allowance import (
    GrantMissing,
    GrantUnusable,
    grant_transaction,
    private_path,
    publish_grant_file,
    stored_grant,
)
from autonomy.baseline import lock as file_lock, publish_bytes
from autonomy.run import RunRefused

from ._contract import KIND, canonical, digest, identifier, valid_unit

_SCHEMA = """
CREATE TABLE grant_record (
    cfg TEXT NOT NULL,
    issuer INTEGER NOT NULL,
    issued INTEGER NOT NULL,
    closed TEXT,
    closed_at INTEGER,
    closed_by INTEGER
);
CREATE TABLE delegation_start (
    ordinal INTEGER PRIMARY KEY,
    attempt TEXT NOT NULL UNIQUE,
    run TEXT NOT NULL UNIQUE,
    at INTEGER NOT NULL,
    state TEXT NOT NULL,
    cache TEXT NOT NULL,
    repository TEXT NOT NULL,
    actor TEXT NOT NULL,
    base TEXT NOT NULL,
    deadline REAL NOT NULL,
    unit TEXT NOT NULL,
    cgroup TEXT NOT NULL,
    invocation TEXT NOT NULL,
    allocated INTEGER NOT NULL DEFAULT 0,
    outcome TEXT,
    disposition_sha256 TEXT
);
"""
_RUN_ID = re.compile(r"[0-9a-f]{32}")
_STORE_LOCK = ".delegations.lock"


@dataclass(frozen=True)
class Start:
    ordinal: int
    attempt: str
    run: str
    at: int
    state: Path
    cache: Path
    repository: str
    actor: str
    base: str
    deadline: float
    unit: str
    cgroup: str
    invocation: str
    allocated: bool
    outcome: str | None
    disposition_sha256: str | None


@dataclass(frozen=True)
class Grant:
    config: dict
    digest: str
    storage: dict
    closed: str | None


@dataclass(frozen=True)
class Survey:
    holders: tuple[str, ...]
    unfinished: tuple[Start, ...]


def _row_to_start(row: sqlite3.Row) -> Start:
    return Start(
        ordinal=int(row["ordinal"]),
        attempt=str(row["attempt"]),
        run=str(row["run"]),
        at=int(row["at"]),
        state=Path(row["state"]),
        cache=Path(row["cache"]),
        repository=str(row["repository"]),
        actor=str(row["actor"]),
        base=str(row["base"]),
        deadline=float(row["deadline"]),
        unit=str(row["unit"]),
        cgroup=str(row["cgroup"]),
        invocation=str(row["invocation"]),
        allocated=bool(row["allocated"]),
        outcome=row["outcome"],
        disposition_sha256=row["disposition_sha256"],
    )


def _unavailable(detail: str, cause: BaseException | None = None) -> RunRefused:
    err = RunRefused("delegation-unavailable", detail)
    if cause is not None:
        err.__cause__ = cause
    return err


def _lock_held(lock_path: Path) -> bool:
    try:
        private_path(lock_path, directory=False)
    except GrantUnusable as exc:
        raise _unavailable(f"unusable delegation lock {lock_path.name}", exc) from exc
    try:
        with file_lock(lock_path, create=False, nowait=True):
            return False
    except BlockingIOError:
        return True
    except (OSError, ValueError) as exc:
        raise _unavailable(f"cannot inspect delegation lock {lock_path.name}", exc) from exc


def _unfinished_rows(path: Path) -> tuple[Start, ...]:
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=1)
    except (sqlite3.Error, OSError, ValueError) as exc:
        raise _unavailable("cannot open delegation database", exc) from exc
    with closing(conn) as db:
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=EXTRA")
            rows = db.execute(
                "SELECT * FROM delegation_start WHERE allocated=1 AND outcome IS NULL ORDER BY ordinal"
            ).fetchall()
            return tuple(_row_to_start(row) for row in rows)
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError) as exc:
            raise _unavailable("unreadable delegation starts", exc) from exc


def survey(root: Path, unit: str) -> Survey:
    valid_unit(unit)
    try:
        private_path(root, directory=True)
        entries = sorted(root.iterdir())
    except (GrantUnusable, OSError) as exc:
        raise _unavailable("cannot inspect delegation store", exc) from exc

    holders: list[str] = []
    unfinished: list[Start] = []
    now = time.time()
    for entry in entries:
        if not entry.name.endswith(".sqlite"):
            continue
        stem = entry.name[:-len(".sqlite")]
        try:
            config, closed = stored_grant(root, entry)
        except GrantUnusable as exc:
            raise _unavailable(f"unreadable grant database {entry.name}", exc) from exc

        if "campaign_id" in config and "delegation_id" not in config:
            if config.get("campaign_id") != stem:
                raise _unavailable(f"campaign identity mismatch in {entry.name}")
            continue

        if (
            config.get("kind") != KIND
            or config.get("delegation_id") != stem
            or not isinstance(config.get("orchestrator"), dict)
            or type(config.get("expires")) is not int
        ):
            raise _unavailable(f"invalid delegation record in {entry.name}")

        if config["orchestrator"].get("unit") != unit:
            continue

        live = closed is None and now < config["expires"]
        held = _lock_held(root / f"{stem}.lock")
        if live or held:
            holders.append(stem)
        unfinished.extend(_unfinished_rows(entry))

    return Survey(tuple(holders), tuple(unfinished))


class Delegation:
    def __init__(self, root: Path, delegation_id: str) -> None:
        self.root = root
        self.name = identifier(delegation_id)
        self.path = root / f"{self.name}.sqlite"
        self.lock_path = root / f"{self.name}.lock"

    @classmethod
    def issue(cls, root: Path, config: dict) -> Delegation:
        if (
            type(config) is not dict
            or config.get("kind") != KIND
            or not isinstance(config.get("orchestrator"), dict)
            or type(config.get("expires")) is not int
            or config["expires"] < 1
        ):
            raise RunRefused("delegation-invalid", "invalid delegation configuration")
        delegation_id = identifier(config.get("delegation_id"))
        unit = valid_unit(config["orchestrator"].get("unit"))
        if config["expires"] <= time.time():
            raise RunRefused("delegation-expired", "grant has already expired")

        try:
            private_path(root, directory=True)
        except GrantUnusable as exc:
            raise _unavailable("delegation store is not private", exc) from exc

        try:
            store_guard = file_lock(root / _STORE_LOCK, create=True, until=time.monotonic() + 5.0)
        except (OSError, TimeoutError, ValueError) as exc:
            raise _unavailable("cannot lock delegation store", exc) from exc

        with store_guard:
            found = survey(root, unit)
            if found.holders:
                raise RunRefused(
                    "delegation-unit-held",
                    f"unit {unit} already has an active or stopping grant ({found.holders[0]})",
                )
            delegation = cls(root, delegation_id)
            if delegation.path.is_symlink():
                raise _unavailable("grant path is a symbolic link")
            if delegation.path.exists():
                raise RunRefused("delegation-closed", f"grant ID {delegation_id} was already used")

            if delegation.lock_path.exists() or delegation.lock_path.is_symlink():
                try:
                    private_path(delegation.lock_path, directory=False)
                    info = delegation.lock_path.stat()
                except (GrantUnusable, OSError) as exc:
                    raise _unavailable("unusable orphan delegation lock", exc) from exc
                if info.st_nlink != 1 or info.st_size != 0:
                    raise _unavailable("orphan delegation lock is not an empty single-link file")
                if _lock_held(delegation.lock_path):
                    raise RunRefused("delegation-unit-held", f"lock for {delegation_id} is still held")
            else:
                try:
                    publish_bytes(delegation.lock_path, b"")
                except OSError as exc:
                    raise _unavailable("cannot publish delegation lock", exc) from exc

            def build(db: sqlite3.Connection) -> None:
                db.executescript(_SCHEMA)
                db.execute(
                    "INSERT INTO grant_record(cfg, issuer, issued) VALUES (?, ?, ?)",
                    (canonical(config), os.geteuid(), int(time.time())),
                )

            try:
                publish_grant_file(root, delegation.path, build)
            except FileExistsError:
                raise RunRefused("delegation-closed", f"grant ID {delegation_id} was already used") from None
            except GrantUnusable as exc:
                raise _unavailable("cannot publish delegation database", exc) from exc
            return delegation

    @contextmanager
    def _transaction(self) -> Iterator[tuple[sqlite3.Connection, dict, str | None]]:
        try:
            with grant_transaction(self.root, self.path, "delegation_id", self.name) as (db, config, cause):
                if config.get("kind") != KIND:
                    raise GrantUnusable("unexpected grant kind")
                yield db, config, cause
        except GrantMissing:
            raise RunRefused("delegation-missing", f"unknown delegation {self.name}") from None
        except RunRefused:
            raise
        except (GrantUnusable, sqlite3.Error, OSError, ValueError, KeyError, TypeError) as exc:
            raise _unavailable("unusable delegation state", exc) from exc

    @contextmanager
    def _lock_ctx(self, *, wait: float) -> Iterator[None]:
        try:
            private_path(self.root, directory=True)
        except GrantUnusable as exc:
            raise _unavailable("delegation store is not private", exc) from exc
        try:
            private_path(self.lock_path, directory=False)
        except GrantUnusable as exc:
            if isinstance(exc.__cause__, FileNotFoundError) and not self.path.exists() and not self.path.is_symlink():
                raise RunRefused("delegation-missing", f"unknown delegation {self.name}") from None
            raise _unavailable("unusable delegation lock", exc) from exc
        try:
            if wait <= 0:
                guard = file_lock(self.lock_path, create=False, nowait=True)
            else:
                guard = file_lock(self.lock_path, create=False, until=time.monotonic() + wait)
            with guard:
                yield
        except (BlockingIOError, TimeoutError):
            raise RunRefused("delegation-busy", "another run holds this delegation") from None
        except (OSError, ValueError) as exc:
            raise _unavailable("cannot lock delegation", exc) from exc

    def lock(self, *, wait: float) -> AbstractContextManager[None]:
        return self._lock_ctx(wait=wait)

    def grant(self) -> Grant:
        with self._transaction() as (_db, config, cause):
            info = self.root.stat()
            storage_id = {"path": str(self.root), "device": info.st_dev, "inode": info.st_ino}
            return Grant(config=config, digest=digest(config), storage=storage_id, closed=cause)

    def starts(self) -> tuple[Start, ...]:
        with self._transaction() as (db, _config, _cause):
            rows = db.execute("SELECT * FROM delegation_start ORDER BY ordinal").fetchall()
            return tuple(_row_to_start(row) for row in rows)

    def begin(self, start: Start, *, margin: float) -> int:
        attempt = identifier(start.attempt)
        if not _RUN_ID.fullmatch(start.run):
            raise RunRefused("delegation-invalid", "invalid run identifier")
        with self._transaction() as (db, config, cause):
            if db.execute("SELECT 1 FROM delegation_start WHERE allocated=1 AND outcome IS NULL").fetchone():
                raise RunRefused(
                    "delegation-run-unfinished",
                    "an earlier marked start has no verdict; run autonomy run close first",
                )
            if cause == "expired":
                raise RunRefused("delegation-expired", "delegation has expired")
            if cause is not None:
                raise RunRefused("delegation-closed", f"delegation is closed ({cause})")
            if time.time() + margin > config["expires"]:
                raise RunRefused("delegation-expired", "run could outlive delegation expiry")
            if db.execute("SELECT 1 FROM delegation_start WHERE attempt=?", (attempt,)).fetchone():
                raise RunRefused("delegation-attempt-used", f"attempt {attempt} already started under this grant")
            count = int(db.execute("SELECT COUNT(*) FROM delegation_start").fetchone()[0])
            if count >= int(config["limits"]["starts"]):
                raise RunRefused("delegation-exhausted", "no starts remain under this grant")
            ordinal = count + 1
            db.execute(
                """
                INSERT INTO delegation_start (
                    ordinal, attempt, run, at, state, cache, repository, actor, base,
                    deadline, unit, cgroup, invocation, allocated, outcome, disposition_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    ordinal,
                    attempt,
                    start.run,
                    int(start.at),
                    str(start.state),
                    str(start.cache),
                    start.repository,
                    start.actor,
                    start.base,
                    float(start.deadline),
                    start.unit,
                    start.cgroup,
                    start.invocation,
                    int(bool(start.allocated)),
                ),
            )
            return ordinal

    def mark(self, run: str) -> None:
        with self._transaction() as (db, _config, cause):
            if cause == "expired":
                raise RunRefused("delegation-expired", "delegation expired before run allocation completed")
            if cause is not None:
                raise RunRefused("delegation-closed", f"delegation closed ({cause}) before run allocation completed")
            row = db.execute("SELECT allocated, outcome FROM delegation_start WHERE run=?", (run,)).fetchone()
            if row is None or row["allocated"] or row["outcome"] is not None:
                raise _unavailable("start cannot be marked allocated")
            db.execute("UPDATE delegation_start SET allocated=1 WHERE run=?", (run,))

    def settle(self, run: str, outcome: str, disposition_sha256: str | None) -> None:
        with self._transaction() as (db, _config, _cause):
            row = db.execute(
                "SELECT outcome, disposition_sha256 FROM delegation_start WHERE run=?",
                (run,),
            ).fetchone()
            if row is None:
                raise _unavailable("unknown delegation start")
            if row["outcome"] is not None:
                if (row["outcome"], row["disposition_sha256"]) != (outcome, disposition_sha256):
                    raise _unavailable("conflicting settlement for delegation start")
                return
            db.execute(
                "UPDATE delegation_start SET outcome=?, disposition_sha256=? WHERE run=?",
                (outcome, disposition_sha256, run),
            )

    def contain(self) -> None:
        with self._transaction() as (db, _config, _cause):
            db.execute(
                "UPDATE grant_record SET closed='containment', closed_at=? WHERE closed IS NULL",
                (int(time.time()),),
            )

    def revoke(self) -> str:
        with self._transaction() as (db, _config, cause):
            db.execute(
                "UPDATE grant_record SET closed='revoked', closed_at=?, closed_by=? WHERE closed IS NULL",
                (int(time.time()), os.geteuid()),
            )
            return cause or "revoked"
