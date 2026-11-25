"""Durable state, concurrency, expiry, closure and store survey for delegations."""
import concurrent.futures
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from autonomy.allowance import Campaign
from autonomy.delegation import KIND, Ceiling, Delegation, Start, definition, memory_floor, survey
from autonomy.run import RunRefused

MIB = 1 << 20
CEILING = Ceiling(96 * MIB, 1 << 30, 131_072, 768 * MIB, 60)


def make_store(tmp_path: Path) -> tuple[Path, Path]:
    store = tmp_path / "store"
    store.mkdir(mode=0o700)
    repo = tmp_path / "repo"
    repo.mkdir()
    return store, repo


def grant_config(repo: Path, *, delegation_id: str = "del-1", unit: str = "band.service", starts: int = 2, expires: int | None = None) -> dict:
    writable = 96 * MIB
    raw = {
        "kind": KIND,
        "delegation_id": delegation_id,
        "source": "approved",
        "expires": int(time.time()) + 3600 if expires is None else expires,
        "orchestrator": {"name": "band", "unit": unit},
        "repositories": {"autonomy": {"path": str(repo), "ref": "refs/heads/main"}},
        "actors": {"regen": ["/usr/bin/true"]},
        "limits": {
            "starts": starts,
            "deadline_seconds": 30,
            "writable_bytes": writable,
            "memory_bytes": memory_floor(writable, CEILING),
            "tasks": 32,
        },
        "model": None,
    }
    return definition(raw, CEILING)


def sample_start(tmp_path: Path, *, attempt: str = "att-1", run: str = "a" * 32, unit: str = "band.service") -> Start:
    return Start(
        ordinal=0,
        attempt=attempt,
        run=run,
        at=int(time.time()),
        state=tmp_path / "state",
        cache=tmp_path / "cache",
        repository="autonomy",
        actor="regen",
        base="1" * 40,
        deadline=30.0,
        unit=unit,
        cgroup=f"/user.slice/user-1000.slice/user@1000.service/app.slice/{unit}",
        invocation="b" * 32,
        allocated=False,
        outcome=None,
        disposition_sha256=None,
    )


def campaign_config() -> dict:
    limits = dict(attempts=1, input_tokens=100, output_tokens=100, micro_usd=1000, job_starts=0)
    return dict(
        campaign_id="camp-1",
        source="fixture",
        expires=int(time.time()) + 3600,
        limits=limits,
        tariff=dict(
            model="m",
            billing_mode="standard",
            context=100,
            output_cap=100,
            max_input_micro_usd_per_mtok=1000,
            output_micro_usd_per_mtok=1000,
            rates_micro_usd_per_mtok=dict(input=1000, output=1000, cache_read=100, cache_write_5m=1000, cache_write_1h=1000),
        ),
        members={"m1": dict(caller="e21", target={}, route_digest="e" * 64, limits=limits)},
    )


def test_attempt_never_starts_twice(tmp_path):
    store, repo = make_store(tmp_path)
    delg = Delegation.issue(store, grant_config(repo, starts=3))
    assert delg.begin(sample_start(tmp_path, attempt="att-1", run="1" * 32), margin=45.0) == 1
    delg.settle("1" * 32, "not-allocated", None)
    with pytest.raises(RunRefused) as caught:
        delg.begin(sample_start(tmp_path, attempt="att-1", run="2" * 32), margin=45.0)
    assert caught.value.code == "delegation-attempt-used"


def test_starts_are_never_returned(tmp_path):
    store, repo = make_store(tmp_path)
    delg = Delegation.issue(store, grant_config(repo, starts=1))
    assert delg.begin(sample_start(tmp_path, attempt="att-1", run="1" * 32), margin=45.0) == 1
    delg.settle("1" * 32, "not-allocated", None)
    with pytest.raises(RunRefused) as caught:
        delg.begin(sample_start(tmp_path, attempt="att-2", run="2" * 32), margin=45.0)
    assert caught.value.code == "delegation-exhausted"
    (recorded,) = delg.starts()
    assert recorded.ordinal == 1 and recorded.outcome == "not-allocated" and not recorded.allocated


def test_refusal_order(tmp_path):
    store, repo = make_store(tmp_path)
    delg = Delegation.issue(store, grant_config(repo, starts=1))
    assert delg.begin(sample_start(tmp_path, attempt="att-1", run="1" * 32), margin=45.0) == 1
    delg.mark("1" * 32)
    for attempt_id, run_id in (("att-1", "2" * 32), ("att-2", "3" * 32)):
        with pytest.raises(RunRefused) as caught:
            delg.begin(sample_start(tmp_path, attempt=attempt_id, run=run_id), margin=45.0)
        assert caught.value.code == "delegation-run-unfinished"

    delg.settle("1" * 32, "quarantined", "d" * 64)
    with pytest.raises(RunRefused) as same:
        delg.begin(sample_start(tmp_path, attempt="att-1", run="2" * 32), margin=45.0)
    assert same.value.code == "delegation-attempt-used"

    with pytest.raises(RunRefused) as other:
        delg.begin(sample_start(tmp_path, attempt="att-2", run="3" * 32), margin=45.0)
    assert other.value.code == "delegation-exhausted"


def test_two_processes_admit_one_start(tmp_path):
    store, repo = make_store(tmp_path)
    Delegation.issue(store, grant_config(repo, starts=1))
    code = """import sys, time
from pathlib import Path
from autonomy.delegation import Delegation, Start
from autonomy.run import RunRefused
store, base, idx = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
d = Delegation(store, "del-1")
try:
    with d.lock(wait=2.0):
        s = Start(0, f"att-{idx}", f"{idx}" * 32, int(time.time()), base / "s", base / "c",
                  "autonomy", "regen", "1" * 40, 30.0, "band.service", "/cg", "b" * 32, False, None, None)
        print("admitted", d.begin(s, margin=45.0))
except RunRefused as err:
    print(err.code)
"""

    def worker(i: int) -> str:
        return subprocess.run(
            [sys.executable, "-c", code, str(store), str(tmp_path), str(i)],
            env={"PATH": os.defpath, "HOME": str(tmp_path)},
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        ).stdout.strip()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(worker, (1, 2)))
    assert results == ["admitted 1", "delegation-exhausted"]


def test_closure_is_permanent_and_keeps_its_first_cause(tmp_path):
    store, repo = make_store(tmp_path)
    d1 = Delegation.issue(store, grant_config(repo, delegation_id="d1", unit="u1.service"))
    d1.contain()
    assert d1.grant().closed == "containment"
    assert d1.revoke() == "containment"
    assert d1.grant().closed == "containment"

    d2 = Delegation.issue(store, grant_config(repo, delegation_id="d2", unit="u2.service"))
    assert d2.revoke() == "revoked"
    d2.contain()
    assert d2.grant().closed == "revoked"
    with pytest.raises(RunRefused) as caught:
        d2.begin(sample_start(tmp_path, unit="u2.service"), margin=45.0)
    assert caught.value.code == "delegation-closed"


def test_expired_grant_stays_closed_when_the_clock_goes_back(tmp_path, monkeypatch):
    store, repo = make_store(tmp_path)
    now = int(time.time())
    delg = Delegation.issue(store, grant_config(repo, expires=now + 20))
    monkeypatch.setattr(time, "time", lambda: now + 30)
    with pytest.raises(RunRefused) as first:
        delg.begin(sample_start(tmp_path), margin=1.0)
    assert first.value.code == "delegation-expired"
    monkeypatch.setattr(time, "time", lambda: now + 5)
    assert delg.grant().closed == "expired"
    with pytest.raises(RunRefused) as second:
        delg.begin(sample_start(tmp_path), margin=1.0)
    assert second.value.code == "delegation-expired"


def test_mark_refuses_after_revoke(tmp_path):
    store, repo = make_store(tmp_path)
    delg = Delegation.issue(store, grant_config(repo))
    delg.begin(sample_start(tmp_path, run="1" * 32), margin=45.0)
    assert delg.revoke() == "revoked"
    with pytest.raises(RunRefused) as caught:
        delg.mark("1" * 32)
    assert caught.value.code == "delegation-closed"
    assert not delg.starts()[0].allocated


def test_issue_reuses_a_lock_without_a_database(tmp_path):
    store, repo = make_store(tmp_path)
    orphan_lock = store / "del-1.lock"
    orphan_lock.write_bytes(b"")
    orphan_lock.chmod(0o600)
    ino = orphan_lock.stat().st_ino
    delg = Delegation.issue(store, grant_config(repo, delegation_id="del-1"))
    assert orphan_lock.stat().st_ino == ino
    assert delg.grant().config["delegation_id"] == "del-1"


def test_issue_refuses_a_campaign_id(tmp_path):
    store, repo = make_store(tmp_path)
    Campaign.issue(store, campaign_config())
    with pytest.raises(RunRefused) as caught:
        Delegation.issue(store, grant_config(repo, delegation_id="camp-1"))
    assert caught.value.code == "delegation-closed"
    with pytest.raises(RunRefused) as missing:
        Delegation(store, "camp-1").grant()
    assert missing.value.code == "delegation-missing"


def test_issue_refuses_a_held_unit(tmp_path, monkeypatch):
    store, repo = make_store(tmp_path)
    now = int(time.time())
    Delegation.issue(store, grant_config(repo, delegation_id="first", unit="band.service", expires=now + 60))
    with pytest.raises(RunRefused) as live:
        Delegation.issue(store, grant_config(repo, delegation_id="second", unit="band.service", expires=now + 120))
    assert live.value.code == "delegation-unit-held"

    monkeypatch.setattr(time, "time", lambda: now + 100)
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl, sys, time; f = open(sys.argv[1], 'r+b'); fcntl.flock(f, fcntl.LOCK_EX); print('held', flush=True); time.sleep(30)",
            str(store / "first.lock"),
        ],
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(RunRefused) as stopping:
            Delegation.issue(store, grant_config(repo, delegation_id="second", unit="band.service", expires=now + 200))
        assert stopping.value.code == "delegation-unit-held"
    finally:
        holder.kill()
        holder.wait(timeout=5)

    reissued = Delegation.issue(store, grant_config(repo, delegation_id="second", unit="band.service", expires=now + 200))
    assert reissued.grant().config["delegation_id"] == "second"


def test_survey_reads_a_database_with_a_hot_journal(tmp_path):
    store, repo = make_store(tmp_path)
    Delegation.issue(store, grant_config(repo, delegation_id="first", unit="band.service"))
    db_path = store / "first.sqlite"
    code = """import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute("PRAGMA cache_size = 1")
db.execute("BEGIN IMMEDIATE")
db.execute("UPDATE grant_record SET closed='revoked'")
for _ in range(50):
    db.execute("INSERT INTO grant_record(cfg, issuer, issued) VALUES (?, 0, 0)", ("x" * 4000,))
os._exit(19)
"""
    res = subprocess.run(
        [sys.executable, "-c", code, str(db_path)],
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        timeout=20,
    )
    assert res.returncode == 19
    assert (store / "first.sqlite-journal").exists()
    found = survey(store, "band.service")
    assert found.holders == ("first",)
    assert not (store / "first.sqlite-journal").exists()


def test_survey_ignores_other_names(tmp_path):
    store, repo = make_store(tmp_path)
    delg = Delegation.issue(store, grant_config(repo, delegation_id="first", unit="band.service"))
    delg.begin(sample_start(tmp_path, run="1" * 32), margin=45.0)
    delg.mark("1" * 32)
    delg.revoke()
    for extra in ("stray.sqlite-journal", "other.lock", ".delegations.lock", ".issuing-abc"):
        p = store / extra
        p.write_bytes(b"noise")
        p.chmod(0o600)
    found = survey(store, "band.service")
    assert found.holders == ()
    assert len(found.unfinished) == 1 and found.unfinished[0].run == "1" * 32


def test_survey_refuses_an_unreadable_database(tmp_path):
    store, _repo = make_store(tmp_path)
    bad = store / "corrupt.sqlite"
    bad.write_bytes(b"not a sqlite file")
    bad.chmod(0o600)
    with pytest.raises(RunRefused) as caught:
        survey(store, "band.service")
    assert caught.value.code == "delegation-unavailable"


def test_digest_is_of_the_stored_record(tmp_path):
    store, repo = make_store(tmp_path)
    cfg = grant_config(repo)
    source_file = tmp_path / "grant.json"
    source_file.write_text(json.dumps(cfg))
    delg = Delegation.issue(store, json.loads(source_file.read_text()))
    first_digest = delg.grant().digest
    cfg["source"] = "mutated later"
    source_file.write_text(json.dumps(cfg))
    assert delg.grant().digest == first_digest


def test_missing_and_busy_errors(tmp_path):
    store, repo = make_store(tmp_path)
    with pytest.raises(RunRefused) as missing:
        Delegation(store, "absent").grant()
    assert missing.value.code == "delegation-missing"

    delg = Delegation.issue(store, grant_config(repo))
    fd = os.open(store / "del-1.lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RunRefused) as busy:
            with delg.lock(wait=0.05):
                pass
        assert busy.value.code == "delegation-busy"
    finally:
        os.close(fd)
