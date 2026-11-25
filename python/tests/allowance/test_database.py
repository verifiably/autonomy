"""Shared private-file checks, exclusive publication and transactions for grant stores."""
import json
import os
import subprocess
import sys
import time

import pytest

from autonomy.allowance import (
    GrantMissing,
    GrantUnusable,
    grant_transaction,
    private_config,
    private_path,
    publish_grant_file,
    storage,
    stored_grant,
)

SCHEMA = (
    "CREATE TABLE grant_record ("
    "cfg TEXT NOT NULL, issuer INTEGER NOT NULL, issued INTEGER NOT NULL, "
    "closed TEXT, closed_at INTEGER, closed_by INTEGER);"
)


def write_grant(root, name, config):
    path = root / f"{name}.sqlite"

    def build(db):
        db.executescript(SCHEMA)
        db.execute(
            "INSERT INTO grant_record(cfg, issuer, issued) VALUES (?, ?, ?)",
            (json.dumps(config, sort_keys=True, separators=(",", ":")), os.geteuid(), int(time.time())),
        )

    publish_grant_file(root, path, build)
    return path


def test_every_connection_syncs_the_directory(tmp_path):
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    path = root / "pool.sqlite"
    seen = []

    def build(db):
        seen.append(db.execute("PRAGMA synchronous").fetchone()[0])
        db.executescript(SCHEMA)
        db.execute(
            "INSERT INTO grant_record(cfg, issuer, issued) VALUES (?, ?, ?)",
            (json.dumps({"delegation_id": "pool", "expires": int(time.time()) + 60}), os.geteuid(), 1),
        )

    publish_grant_file(root, path, build)
    with grant_transaction(root, path, "delegation_id", "pool") as (db, config, closed):
        seen.append(db.execute("PRAGMA synchronous").fetchone()[0])
        assert config["delegation_id"] == "pool" and closed is None
    assert seen == [3, 3]
    assert private_config is not None and storage is not None


def test_private_path_and_exclusive_publication(tmp_path):
    root = tmp_path / "store"
    root.mkdir(mode=0o755)
    with pytest.raises(GrantUnusable):
        private_path(root, directory=True)
    root.chmod(0o700)
    private_path(root, directory=True)

    path = write_grant(root, "pool", {"delegation_id": "pool", "expires": int(time.time()) + 60})
    private_path(path, directory=False)
    with pytest.raises(FileExistsError):
        write_grant(root, "pool", {"delegation_id": "pool", "expires": int(time.time()) + 60})


def test_grant_transaction_checks_kind_and_name_before_any_write(tmp_path):
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    with pytest.raises(GrantMissing):
        with grant_transaction(root, root / "absent.sqlite", "campaign_id", "absent"):
            pass

    expired = int(time.time()) - 10
    path = write_grant(root, "pool", {"kind": "development-delegation.v1", "delegation_id": "pool", "expires": expired})
    before = path.read_bytes()
    with pytest.raises(GrantMissing):
        with grant_transaction(root, path, "campaign_id", "pool"):
            pass
    assert path.read_bytes() == before

    with pytest.raises(GrantUnusable):
        with grant_transaction(root, path, "delegation_id", "other"):
            pass
    assert path.read_bytes() == before


def test_grant_transaction_records_expiry_and_keeps_caller_errors(tmp_path):
    class CallerError(Exception):
        pass

    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    path = write_grant(root, "pool", {"delegation_id": "pool", "expires": int(time.time()) - 5})
    with pytest.raises(CallerError):
        with grant_transaction(root, path, "delegation_id", "pool") as (_db, _cfg, closed):
            assert closed == "expired"
            raise CallerError("stop")
    assert stored_grant(root, path)[1] == "expired"


def test_stored_grant_writes_nothing_and_recovers_a_hot_journal(tmp_path):
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    expired = int(time.time()) - 30
    path = write_grant(root, "pool", {"delegation_id": "pool", "expires": expired})
    before = path.read_bytes()
    config, closed = stored_grant(root, path)
    assert config["delegation_id"] == "pool" and closed is None
    assert path.read_bytes() == before

    code = """import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute("PRAGMA cache_size = 1")
db.execute("BEGIN IMMEDIATE")
db.execute("UPDATE grant_record SET closed='revoked'")
for _ in range(50):
    db.execute("INSERT INTO grant_record(cfg, issuer, issued) VALUES (?, 0, 0)", ("x" * 4000,))
os._exit(17)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        timeout=20,
    )
    assert result.returncode == 17
    assert (root / "pool.sqlite-journal").exists()
    import sqlite3

    with pytest.raises(sqlite3.OperationalError):
        ro = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            ro.execute("SELECT * FROM grant_record").fetchall()
        finally:
            ro.close()
    config, closed = stored_grant(root, path)
    assert config["delegation_id"] == "pool" and closed is None
    assert not (root / "pool.sqlite-journal").exists()
