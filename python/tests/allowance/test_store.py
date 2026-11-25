"""A campaign's limits survive envelope closure, races, lost replies and restarts."""
import concurrent.futures
import os
import subprocess
import sys
import time

import pytest

from autonomy.allowance import AllowanceRefused, Campaign

LIMITS = dict(attempts=2, input_tokens=400, output_tokens=200, micro_usd=2400, job_starts=2)
C = "512b02da-ccbe-47cd-bd24-2a9d2f62c5f5"
P = "46a174a6-d091-460c-a41c-b43631297c67"
R = "a" * 32
R2 = "b" * 32
ROUTE = "e" * 64


def definition():
    action = {"proposition": "target"}
    return dict(campaign_id="pool", source="offline fixture", expires=int(time.time()) + 3600,
                limits=LIMITS, tariff=dict(model="fixture", billing_mode="standard", context=200,
                    output_cap=100, max_input_micro_usd_per_mtok=4000000, output_micro_usd_per_mtok=5000000),
                members={"action": dict(caller="band", target=action, route_digest=ROUTE, limits=LIMITS),
                         "smoke": dict(caller="e21", target={}, route_digest=ROUTE,
                                       limits={**LIMITS, "job_starts": 0, "attempts": 1})})


def issued(tmp_path, **changes):
    cfg = definition() | changes
    pool = Campaign.issue(tmp_path, cfg)
    pool.open("action", R, caller="band", target=cfg["members"]["action"]["target"], route_digest=ROUTE,
              conversation_id=C)
    return pool


def model(pool, seq=1, envelope=R, member="action"):
    return pool.reserve(member, envelope, "model", dict(seq=seq, model="fixture", max_tokens=80, billing_mode="standard"))


def test_shared_debit_and_idempotent_settlement_after_close(tmp_path):
    pool = issued(tmp_path)
    assert model(pool) == {"result": "admitted"}
    assert model(Campaign(tmp_path, "pool")) == {"result": "already-recorded", "state": "reserved"}
    pool.open("smoke", R2, caller="e21", target={}, route_digest=ROUTE)
    assert model(pool, envelope=R2, member="smoke") == {"result": "admitted"}
    with pytest.raises(AllowanceRefused, match="allowance-exhausted"):
        model(pool, 2)
    pool.seal("smoke", R2)
    pool.revoke()
    evidence = dict(seq=1, status="unknown", request_id=None, message_id=None, usage=None)
    for _ in range(2):
        assert pool.settle("action", R, "model", evidence) == {"result": "settled"}
    with pytest.raises(AllowanceRefused, match="allowance-scope"):
        pool.settle("action", R, "model", evidence | {"message_id": "changed"})
    with pytest.raises(AllowanceRefused, match="allowance-closed"):
        model(pool, 2)
    with pytest.raises(AllowanceRefused, match="allowance-closed"):
        Campaign.issue(tmp_path, definition())
    report = pool.snapshot("action")
    assert report["remaining"]["micro_usd"] == 0
    assert len(report["reservations"]) == 1


def test_open_and_late_report_cannot_change_identity(tmp_path):
    pool = issued(tmp_path)
    pool.seal("action", R)
    report = dict(version="band-turn.v1", provider_session_id=P, settlement=None,
                  question_id=None, answer_id=None, submission_id=None, responses=[])
    opening = dict(caller="band", target={"proposition": "target"}, route_digest=ROUTE, conversation_id=C)
    with pytest.raises(AllowanceRefused, match="allowance-scope"):
        pool.open("action", R2, **opening, provider_session_id=P)
    receipt = pool.record_turn("action", R, C, report)
    assert pool.record_turn("action", R, C, report) == receipt
    with pytest.raises(AllowanceRefused, match="allowance-scope"):
        pool.record_turn("action", R, C, report | {"provider_session_id": C})
    pool.open("action", R2, **opening, provider_session_id=P)
    with pytest.raises(AllowanceRefused, match="allowance-closed"):
        pool.reserve("action", R, "job", {"invocation_id": "pi-t2", "phase": "original"})
    pool.register_actor("action", R2, "c" * 32)
    assert pool.reserve("action", R2, "job", {"invocation_id": "pi-t3", "phase": "replay"})["result"] == "admitted"


def test_last_unit_is_serialized_between_python_processes(tmp_path):
    pool = issued(tmp_path, limits=LIMITS | {"attempts": 1})
    code = """from autonomy.allowance import Campaign, AllowanceRefused
from pathlib import Path
import sys
try:
    print(Campaign(Path(sys.argv[1]), 'pool').reserve('action', 'a'*32, 'model',
          dict(seq=int(sys.argv[2]), model='fixture', max_tokens=80, billing_mode='standard'))['result'])
except AllowanceRefused as error:
    print(error.code)
"""
    def contender(i):
        return subprocess.run([sys.executable, "-c", code, str(tmp_path), str(i)],
                              env={"PATH": os.defpath, "HOME": str(tmp_path)}, capture_output=True,
                              text=True, timeout=20, check=True).stdout.strip()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        assert sorted(executor.map(contender, range(4))) == ["admitted"] + ["allowance-exhausted"] * 3
    assert pool.snapshot("action")["remaining"]["attempts"] == 0


def test_missing_or_unsafe_accounting_refuses_without_creating(tmp_path):
    with pytest.raises(AllowanceRefused, match="allowance-missing"):
        model(Campaign(tmp_path, "pool"))
    assert not list(tmp_path.iterdir())
    pool = issued(tmp_path)
    assert pool.path.stat().st_mode & 0o777 == 0o600
    pool.path.chmod(0o644)
    with pytest.raises(AllowanceRefused, match="allowance-unavailable"):
        model(pool)


@pytest.fixture
def local_directory():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as root:
        yield Path(root)


def test_operator_issue_and_revoke(local_directory, monkeypatch, capfd):
    tmp_path = local_directory
    import json
    from autonomy.cli import main
    config = tmp_path / "conf" / "verifiably-autonomy"
    root = tmp_path / "qualified"
    root.mkdir(mode=0o700)
    grants = config / "allowances"
    grants.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config.parent))
    info = root.stat()
    storage = config / "allowance-storage.json"
    storage.write_text(json.dumps(dict(version=1, path=str(root), device=info.st_dev, inode=info.st_ino)))
    storage.chmod(0o600)
    grant = grants / "trial.json"
    grant.write_text(json.dumps(definition()))
    grant.chmod(0o600)
    assert main(["allowance", "issue", "trial"]) == 0
    receipt = json.loads(capfd.readouterr().out)
    assert receipt["grant"]["campaign_id"] == "pool"
    assert receipt["storage"]["inode"] == info.st_ino
    assert main(["allowance", "revoke", "pool"]) == 0
    assert json.loads(capfd.readouterr().out)["cause"] == "revoked"
    assert main(["allowance", "issue", "trial"]) == 2
    assert "allowance-closed" in capfd.readouterr().err
    moved = root.with_name("old")
    root.rename(moved)
    root.mkdir(mode=0o700)
    assert main(["allowance", "issue", "trial"]) == 2
    assert "allowance-unavailable" in capfd.readouterr().err


def test_lost_process_preserves_commit_and_rolls_back_interrupted_transaction(tmp_path):
    pool = issued(tmp_path)
    code = """import os, sys
from pathlib import Path
from autonomy.allowance import Campaign
pool = Campaign(Path(sys.argv[1]), 'pool')
pool.reserve('action', 'a'*32, 'model', dict(seq=1, model='fixture', max_tokens=80, billing_mode='standard'))
with pool._transaction() as (db, cfg, cause):
    db.execute('DELETE FROM reservation')
    os._exit(19)
"""
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)],
                            env={"HOME": str(tmp_path), "PATH": os.defpath}, timeout=20)
    assert result.returncode == 19
    assert model(pool)["result"] == "already-recorded"
    assert pool.snapshot("action")["remaining"]["micro_usd"] == 1200


@pytest.mark.parametrize(("overrides", "code"), [
    ({"seq": -1}, "allowance-scope"),
    ({"model": "unpriced"}, "allowance-unpriced"),
    ({"max_tokens": 101}, "body-refused"),
])
def test_bad_reservations_never_debit(tmp_path, overrides, code):
    pool = issued(tmp_path)
    args = dict(seq=2, model="fixture", max_tokens=80, billing_mode="standard") | overrides
    with pytest.raises(AllowanceRefused, match=code):
        pool.reserve("action", R, "model", args)
    assert pool.snapshot("action")["reservations"] == []


def test_expiry_persists_through_clock_reversal(tmp_path, monkeypatch):
    now = int(time.time())
    pool = issued(tmp_path, expires=now + 10)
    monkeypatch.setattr(time, "time", lambda: now + 20)
    with pytest.raises(AllowanceRefused, match="allowance-expired"):
        model(pool)
    monkeypatch.setattr(time, "time", lambda: now)
    with pytest.raises(AllowanceRefused, match="allowance-expired"):
        model(pool)


def test_corrupt_negative_debit_refuses_instead_of_adding_capacity(tmp_path):
    import sqlite3
    pool = issued(tmp_path)
    model(pool)
    with sqlite3.connect(pool.path) as db:
        db.execute("""UPDATE reservation SET debit='{"micro_usd":-500}'""")
    with pytest.raises(AllowanceRefused, match="allowance-unavailable"):
        model(pool, 2)
