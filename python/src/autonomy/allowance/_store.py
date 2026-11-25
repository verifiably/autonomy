"""One host-private SQLite file per issued campaign. The durable debit never decreases."""
import json
import os
import sqlite3
import stat
import tempfile
import time
from contextlib import closing, contextmanager
from pathlib import Path

from autonomy.baseline import fsync_dir
from . import _contract as c
from ._contract import AllowanceRefused

_SCHEMA = """
CREATE TABLE grant_record (cfg TEXT NOT NULL, issuer INTEGER NOT NULL, issued INTEGER NOT NULL, closed TEXT, closed_at INTEGER, closed_by INTEGER);
CREATE TABLE member (name TEXT PRIMARY KEY, limits TEXT NOT NULL, conversation TEXT, provider TEXT);
CREATE TABLE envelope (id TEXT PRIMARY KEY, name TEXT NOT NULL, closed INTEGER NOT NULL DEFAULT 0,
                       actor TEXT, report TEXT);
CREATE UNIQUE INDEX one_open ON envelope(name) WHERE closed=0;
CREATE TABLE reservation (envelope TEXT, role TEXT, ticket TEXT, request TEXT NOT NULL, debit TEXT NOT NULL,
                          actor TEXT, settlement TEXT, PRIMARY KEY(envelope,role,ticket));
"""


def _private(path, directory):
    info = path.lstat()
    mode = 0o700 if directory else 0o600
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    c.require(path.is_absolute() and path == path.resolve() and kind(info.st_mode)
              and stat.S_IMODE(info.st_mode) == mode and info.st_uid == os.geteuid(),
              "accounting requires private owned storage", "allowance-unavailable")


class Campaign:
    def __init__(self, root: Path, campaign_id: str):
        self.root = root
        self.name = c.opaque(campaign_id)
        self.path = root / (campaign_id + ".sqlite")

    @classmethod
    def issue(cls, root, config):
        c.definition(config)
        campaign = cls(root, config["campaign_id"])
        c.require(config["expires"] > time.time(), "grant already expired", "allowance-expired")
        try:
            _private(root, True)
            with tempfile.NamedTemporaryFile(dir=root, prefix=".issuing-") as temporary:
                with closing(sqlite3.connect(temporary.name)) as db:
                    db.execute("PRAGMA synchronous=FULL")
                    db.executescript(_SCHEMA)
                    db.execute("INSERT INTO grant_record(cfg,issuer,issued) VALUES (?,?,?)",
                               (c.canonical(config), os.geteuid(), int(time.time())))
                    db.executemany("INSERT INTO member(name,limits) VALUES (?,?)",
                                   [(name, c.canonical(row["limits"])) for name, row in config["members"].items()])
                    db.commit()
                os.fsync(temporary.fileno())
                os.link(temporary.name, campaign.path)
                fsync_dir(root)
        except FileExistsError:
            raise AllowanceRefused("allowance-closed", "campaign ID was already issued") from None
        except (OSError, sqlite3.Error) as exc:
            raise AllowanceRefused("allowance-unavailable", "cannot publish durable grant") from exc
        return campaign

    @contextmanager
    def _transaction(self):
        try:
            _private(self.root, True)
            try:
                _private(self.path, False)
            except FileNotFoundError:
                raise AllowanceRefused("allowance-missing", "unknown campaign") from None
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=1)) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA synchronous=FULL")
                db.execute("BEGIN IMMEDIATE")
                rows = db.execute("SELECT * FROM grant_record").fetchall()
                c.require(len(rows) == 1, "invalid grant record", "allowance-unavailable")
                config = json.loads(rows[0]["cfg"])
                c.require(config["campaign_id"] == self.name, "grant identity differs", "allowance-unavailable")
                db.execute("CREATE TABLE IF NOT EXISTS turn_dispute (envelope TEXT, report TEXT, PRIMARY KEY(envelope,report))")
                db.execute("CREATE TABLE IF NOT EXISTS turn_exit (envelope TEXT PRIMARY KEY, normal INTEGER NOT NULL)")
                cause = rows[0]["closed"]
                if cause is None and time.time() >= config["expires"]:
                    db.execute("UPDATE grant_record SET closed='expired',closed_at=?", (int(time.time()),))
                    db.commit()
                    db.execute("BEGIN IMMEDIATE")
                    cause = "expired"
                yield db, config, cause
                db.commit()
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError) as exc:
            raise AllowanceRefused("allowance-unavailable", "unusable accounting state") from exc

    @staticmethod
    def _active(cause):
        c.require(cause != "expired", "original deadline elapsed", "allowance-expired")
        c.require(cause is None, "campaign closed", "allowance-closed")

    @staticmethod
    def _envelope(db, member, envelope):
        row = db.execute("SELECT * FROM envelope WHERE id=? AND name=?", (envelope, member)).fetchone()
        c.require(row is not None, "envelope does not belong to member")
        return row

    @staticmethod
    def _opening_member(db, config, member, caller, target, route_digest, conversation_id, provider_session_id):
        spec = config["members"].get(member)
        c.require(spec and (caller, target, route_digest) == (spec["caller"], spec["target"], spec["route_digest"]),
                  "grant member binding differs")
        row = db.execute("SELECT * FROM member WHERE name=?", (member,)).fetchone()
        prior = db.execute("SELECT e.id,e.closed,e.report,x.normal FROM envelope e LEFT JOIN turn_exit x ON x.envelope=e.id WHERE e.name=? ORDER BY e.rowid", (member,)).fetchall()
        c.require(not any(not item["closed"] for item in prior), "member already open")
        if caller == "band":
            c.uid(conversation_id)
            c.require(row["conversation"] in (None, conversation_id), "different host conversation")
            if prior:
                c.require(all(item["report"] is not None for item in prior), "awaiting predecessor turn evidence")
                c.require(not db.execute("SELECT 1 FROM turn_dispute d JOIN envelope e ON e.id=d.envelope WHERE e.name=?",
                                         (member,)).fetchone(), "disputed predecessor turn", "allowance-unavailable")
                c.require(all(item["normal"] is not None for item in prior), "awaiting predecessor exit evidence")
                c.uid(provider_session_id)
            c.require(provider_session_id == row["provider"], "provider session is missing or changed")
        else:
            c.require(not prior and provider_session_id is None and conversation_id is None, "member already used")
        return row

    def check_open(self, member, **binding):
        with self._transaction() as (db, config, cause):
            self._active(cause)
            self._opening_member(db, config, member, **binding)
            remaining = self._remaining(db, config, member)
            if not remaining["attempts"]:
                raise AllowanceRefused("allowance-exhausted", "no provider attempts remain",
                                       dimension="attempts", remaining=remaining)

    def open(self, member, envelope, *, caller, target, route_digest,
             conversation_id=None, provider_session_id=None, lower_limits=None):
        c.hexadecimal(envelope, 32)
        with self._transaction() as (db, config, cause):
            self._active(cause)
            row = self._opening_member(db, config, member, caller, target, route_digest,
                                       conversation_id, provider_session_id)
            effective = json.loads(row["limits"])
            if lower_limits is not None:
                c.limits(lower_limits)
                c.require(all(lower_limits[k] <= effective[k] for k in effective), "limits may only decrease")
                effective = lower_limits
            c.require(not db.execute("SELECT 1 FROM envelope WHERE id=?", (envelope,)).fetchone(), "envelope already used")
            db.execute("UPDATE member SET limits=?,conversation=? WHERE name=?", (c.canonical(effective), conversation_id, member))
            db.execute("INSERT INTO envelope(id,name) VALUES (?,?)", (envelope, member))
            return {"grant_digest": c.digest(config), "expires": config["expires"], "limits": effective}

    def register_actor(self, member, envelope, session_id):
        c.hexadecimal(session_id, 32)
        with self._transaction() as (db, _, cause):
            self._active(cause)
            row = self._envelope(db, member, envelope)
            c.require(not row["closed"] and row["actor"] in (None, "session:" + session_id), "writer actor changed")
            db.execute("UPDATE envelope SET actor=? WHERE id=?", ("session:" + session_id, envelope))

    @staticmethod
    def _remaining(db, config, member):
        row = db.execute("SELECT limits FROM member WHERE name=?", (member,)).fetchone()
        c.require(row is not None, "unknown member")
        local = json.loads(row["limits"])
        pool = config["limits"].copy()
        for name, encoded in db.execute("SELECT e.name,r.debit FROM reservation r JOIN envelope e ON e.id=r.envelope"):
            try:
                charge = c.limits(json.loads(encoded))
            except AllowanceRefused as exc:
                raise AllowanceRefused("allowance-unavailable", "invalid stored debit") from exc
            for key, value in charge.items():
                pool[key] -= value
                if name == member:
                    local[key] -= value
        return {k: max(0, min(pool[k], local[k])) for k in pool}

    def reserve(self, member, envelope, role, request):
        ticket = c.ticket(role, request)
        with self._transaction() as (db, config, cause):
            self._active(cause)
            row = self._envelope(db, member, envelope)
            c.require(not row["closed"], "envelope closed", "allowance-closed")
            if role == "job":
                c.require(row["actor"] is not None, "writer actor is not bound")
            charge = c.debit(role, request, config["tariff"])
            key = (envelope, role, ticket)
            existing = db.execute("SELECT request,settlement FROM reservation WHERE envelope=? AND role=? AND ticket=?", key).fetchone()
            encoded = c.canonical(request)
            if existing is not None:
                c.require(existing["request"] == encoded, "reservation identity reused for different request")
                return {"result": "already-recorded", "state": "reserved" if existing["settlement"] is None else "settled"}
            remaining = self._remaining(db, config, member)
            for dimension, units in charge.items():
                if units > remaining[dimension]:
                    raise AllowanceRefused("allowance-exhausted", f"insufficient {dimension}",
                                           dimension=dimension, remaining=remaining)
            db.execute("INSERT INTO reservation VALUES (?,?,?,?,?,?,NULL)",
                       (*key, encoded, c.canonical(charge), row["actor"] if role == "job" else envelope))
            return {"result": "admitted"}

    def settle(self, member, envelope, role, evidence):
        key = (envelope, role, c.ticket(role, evidence))
        with self._transaction() as (db, _, _cause):
            self._envelope(db, member, envelope)
            row = db.execute("SELECT settlement,actor FROM reservation WHERE envelope=? AND role=? AND ticket=?", key).fetchone()
            if role == "job" and evidence.get("ledger_ref") is not None:
                c.require(row and row["actor"] == "session:" + evidence["ledger_ref"]["session_id"],
                          "terminal act belongs to a different writer")
            encoded = c.canonical(evidence)
            c.require(row and row["settlement"] in (None, encoded), "unknown or conflicting settlement")
            db.execute("UPDATE reservation SET settlement=? WHERE envelope=? AND role=? AND ticket=?", (encoded, *key))
            return {"result": "settled"}

    def seal(self, member, envelope, *, cancel=False):
        with self._transaction() as (db, config, _cause):
            self._envelope(db, member, envelope)
            db.execute("UPDATE envelope SET closed=1 WHERE id=?", (envelope,))
            if cancel:
                db.execute("UPDATE grant_record SET closed='cancelled',closed_at=? WHERE closed IS NULL", (int(time.time()),))
            elif len(config["members"]) == 1 and config["members"][member]["caller"] != "band":
                db.execute("UPDATE grant_record SET closed='completed',closed_at=? WHERE closed IS NULL", (int(time.time()),))

    def recover_envelope(self, member, envelope, digest, storage):
        with self._transaction() as (db, config, _cause):
            info = self.root.stat()
            c.require(storage == {"path": str(self.root), "device": info.st_dev, "inode": info.st_ino}
                      and c.digest(config) == digest and member in config["members"],
                      "recorded allowance identity differs", "allowance-unavailable")
            row = db.execute("SELECT name FROM envelope WHERE id=?", (envelope,)).fetchone()
            if row is not None:
                c.require(row["name"] == member, "recorded envelope belongs to a different member")
                db.execute("UPDATE envelope SET closed=1 WHERE id=?", (envelope,))

    def revoke(self):
        with self._transaction() as (db, _, cause):
            db.execute("UPDATE grant_record SET closed='revoked',closed_at=?,closed_by=? WHERE closed IS NULL",
                       (int(time.time()), os.geteuid()))
            return {"campaign_id": self.name, "cause": cause or "revoked",
                    "pending_envelopes": [r[0] for r in db.execute("SELECT id FROM envelope WHERE closed=0 ORDER BY id")]}

    @staticmethod
    def _exit_state(db, envelope, normal, report):
        if normal is not None:
            c.require(type(normal) is bool, "invalid actor exit evidence")
            db.execute("INSERT OR IGNORE INTO turn_exit VALUES (?,?)", (envelope, int(normal)))
        row = db.execute("SELECT normal FROM turn_exit WHERE envelope=?", (envelope,)).fetchone()
        if row is not None:
            c.require(normal is None or row["normal"] == normal, "conflicting actor exit evidence", "allowance-unavailable")
            if row["normal"] and report is not None and report["question_id"] is None:
                db.execute("UPDATE grant_record SET closed='completed',closed_at=? WHERE closed IS NULL", (int(time.time()),))

    def confirm_exit(self, member, envelope, normal):
        with self._transaction() as (db, _, _cause):
            row = self._envelope(db, member, envelope)
            c.require(row["closed"], "actor exit before envelope close")
            self._exit_state(db, envelope, normal, json.loads(row["report"]) if row["report"] else None)

    def record_turn(self, member, envelope, conversation, report, *, normal_exit=None):
        c.validate_report(report)
        provider = report["provider_session_id"]
        with self._transaction() as (db, _, _cause):
            row = self._envelope(db, member, envelope)
            host = db.execute("SELECT conversation,provider FROM member WHERE name=?", (member,)).fetchone()
            c.require(c.uid(conversation) == host["conversation"] and host["provider"] in (None, provider), "turn identity differs")
            encoded = c.canonical(report)
            if row["report"] not in (None, encoded):
                db.execute("INSERT OR IGNORE INTO turn_dispute VALUES (?,?)", (envelope, encoded))
                db.commit()
                raise AllowanceRefused("allowance-scope", "conflicting turn evidence")
            c.require(normal_exit is None or row["closed"], "exit evidence for an open envelope")
            self._exit_state(db, envelope, normal_exit, report)
            db.execute("UPDATE member SET provider=? WHERE name=?", (provider, member))
            db.execute("UPDATE envelope SET report=? WHERE id=?", (encoded, envelope))
            return {"version": "band-turn.v1", "envelope_id": envelope, "provider_session_id": provider}

    def receipt(self):
        with self._transaction() as (db, config, cause):
            row = db.execute("SELECT issuer,issued FROM grant_record").fetchone()
            info = self.root.stat()
            return {"grant": config, "issuer_uid": row["issuer"], "issued": row["issued"],
                    "grant_digest": c.digest(config), "tariff_digest": c.digest(config["tariff"]),
                    "closed": cause, "storage": {"path": str(self.root), "device": info.st_dev, "inode": info.st_ino}}

    def snapshot(self, member):
        with self._transaction() as (db, config, cause):
            remaining = self._remaining(db, config, member)
            reservations = []
            for row in db.execute("SELECT r.* FROM reservation r JOIN envelope e ON e.id=r.envelope WHERE e.name=? ORDER BY r.rowid", (member,)):
                record = dict(row)
                for field in ("request", "debit", "settlement"):
                    if record[field] is not None:
                        record[field] = json.loads(record[field])
                reservations.append(record)
            envelopes = []
            for row in db.execute("SELECT * FROM envelope WHERE name=? ORDER BY rowid", (member,)):
                entry = dict(row)
                if entry["report"] is not None:
                    entry["report"] = json.loads(entry["report"])
                entry["disputes"] = [json.loads(r[0]) for r in db.execute(
                    "SELECT report FROM turn_dispute WHERE envelope=? ORDER BY report", (entry["id"],))]
                envelopes.append(entry)
            identity = db.execute("SELECT conversation,provider FROM member WHERE name=?", (member,)).fetchone()
            return {"grant": config, "closed": cause, "remaining": remaining, "reservations": reservations,
                    "envelopes": envelopes, "conversation_id": identity["conversation"], "provider_session_id": identity["provider"]}
