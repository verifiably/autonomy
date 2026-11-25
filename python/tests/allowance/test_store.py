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
                    output_cap=100, max_input_micro_usd_per_mtok=4000000, output_micro_usd_per_mtok=5000000,
                    rates_micro_usd_per_mtok=dict(input=1000000, output=5000000, cache_read=100000,
                                                  cache_write_5m=2000000, cache_write_1h=4000000)),
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


def test_orphan_close_uses_original_storage_grant_and_member(tmp_path):
    pool = issued(tmp_path)
    receipt = pool.receipt()
    digest, storage = receipt["grant_digest"], receipt["storage"]
    for member, sha, identity in [("smoke", digest, storage), ("action", "f" * 64, storage),
                                  ("action", digest, storage | {"inode": storage["inode"] + 1})]:
        with pytest.raises(AllowanceRefused):
            pool.recover_envelope(member, R, sha, identity)
    pool.recover_envelope("action", R2, digest, storage)  # death before registration
    assert [(row["id"], row["closed"]) for row in pool.snapshot("action")["envelopes"]] == [(R, 0)]
    for _ in range(2):
        pool.recover_envelope("action", R, digest, storage)
    assert pool.snapshot("action")["envelopes"][0]["closed"] == 1


def test_open_and_late_report_cannot_change_identity(tmp_path):
    pool = issued(tmp_path)
    pool.seal("action", R)
    report = dict(version="band-turn.v1", provider_session_id=P, settlement=None,
                  question_id=None, answer_id=None, submission_id=None, responses=[])
    opening = dict(caller="band", target={"proposition": "target"}, route_digest=ROUTE, conversation_id=C)
    with pytest.raises(AllowanceRefused, match="allowance-scope"):
        pool.open("action", R2, **opening, provider_session_id=P)
    receipt = pool.record_turn("action", R, C, report, normal_exit=False)
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
        assert sorted(executor.map(contender, range(1, 5))) == ["admitted"] + ["allowance-exhausted"] * 3
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


def test_route_grant_resolves_before_reading_credential(tmp_path):
    from autonomy.egress.route import load_governed_route
    from egress_fixtures import pi_route, write_route
    route = pi_route(credential=tmp_path / "missing-key")
    write_route(tmp_path, "pi", route)
    with pytest.raises(AllowanceRefused, match="allowance-missing"):
        load_governed_route(tmp_path, "pi", None, caller="analyst")


def test_disputed_turn_is_retained_once_without_overwriting_the_accepted_projection(tmp_path):
    pool = issued(tmp_path)
    pool.seal("action", R)
    report = dict(version="band-turn.v1", provider_session_id=P, settlement=None,
                  question_id=None, answer_id=None, submission_id=1, responses=[])
    pool.record_turn("action", R, C, report)
    for _ in range(2):
        with pytest.raises(AllowanceRefused):
            pool.record_turn("action", R, C, report | {"submission_id": 2})
    envelope, = pool.snapshot("action")["envelopes"]
    assert envelope["report"] == report
    assert envelope["disputes"] == [report | {"submission_id": 2}]


def test_terminal_projection_closes_the_campaign_even_for_another_member(tmp_path):
    pool = issued(tmp_path)
    pool.seal("action", R)
    report = dict(version="band-turn.v1", provider_session_id=P, settlement=None,
                  question_id=None, answer_id=None, submission_id=1, responses=[])
    pool.record_turn("action", R, C, report, normal_exit=True)
    assert pool.receipt()["closed"] == "completed"
    with pytest.raises(AllowanceRefused, match="allowance-closed"):
        pool.open("smoke", R2, caller="e21", target={}, route_digest=ROUTE)


@pytest.mark.parametrize("substitution", ["argv", "bytes"])
def test_band_worker_is_checked_before_credential_access(tmp_path, substitution):
    import hashlib
    from autonomy.egress.errors import RouteRefused
    from autonomy.egress.route import load_governed_route
    from egress_fixtures import governed_route, pi_route

    config = tmp_path / "operator"
    worker = tmp_path / "worker.ts"
    worker.write_bytes(b"authorized worker")
    argv = ["/usr/bin/node", str(worker)]
    target = {"worker": {"argv": list(argv), "sha256": hashlib.sha256(worker.read_bytes()).hexdigest()}}
    governed_route(config, "pi", pi_route(credential=tmp_path / "absent"), caller="band", target=target)
    if substitution == "argv":
        argv[1] = str(tmp_path / "another")
    else:
        worker.write_bytes(b"changed worker")
    with pytest.raises(RouteRefused, match="worker") as refused:
        load_governed_route(config, "pi", None, caller="band", conversation_id=C, actor_argv=argv)
    assert refused.value.code == "allowance-scope"

def test_early_report_cannot_reopen_before_host_confirms_the_terminal_exit(tmp_path):
    pool = issued(tmp_path)
    report = dict(version="band-turn.v1", provider_session_id=P, settlement=None,
                  question_id=None, answer_id=None, submission_id=1, responses=[])
    pool.record_turn("action", R, C, report)
    pool.seal("action", R)
    opening = dict(caller="band", target={"proposition": "target"}, route_digest=ROUTE, conversation_id=C, provider_session_id=P)
    with pytest.raises(AllowanceRefused, match="awaiting predecessor exit"):
        pool.open("action", R2, **opening)
    pool.confirm_exit("action", R, True)
    with pytest.raises(AllowanceRefused, match="allowance-closed"):
        pool.open("action", R2, **opening)


@pytest.mark.parametrize("delta", [3600, -30])
def test_another_kind_of_grant_is_missing_here(tmp_path, delta):
    import json
    import sqlite3

    path = tmp_path / "pool.sqlite"
    cfg = {"kind": "development-delegation.v1", "delegation_id": "pool", "expires": int(time.time()) + delta}
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE grant_record ("
            "cfg TEXT NOT NULL, issuer INTEGER NOT NULL, issued INTEGER NOT NULL, "
            "closed TEXT, closed_at INTEGER, closed_by INTEGER)"
        )
        db.execute(
            "INSERT INTO grant_record(cfg, issuer, issued) VALUES (?, ?, ?)",
            (json.dumps(cfg, sort_keys=True, separators=(",", ":")), os.geteuid(), int(time.time())),
        )
    path.chmod(0o600)
    before = path.read_bytes()
    with pytest.raises(AllowanceRefused, match="allowance-missing"):
        Campaign(tmp_path, "pool").receipt()
    assert path.read_bytes() == before

