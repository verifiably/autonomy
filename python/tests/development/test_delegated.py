import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from autonomy.baseline import append_event, publish_bytes
from autonomy.delegation import Delegation, Host, Start
from autonomy.development._records import (
    DevelopmentPlaces,
    allocate_run,
    development_places,
    publication_lock,
    publish_grant,
    publish_json,
    publish_terminal,
)
from autonomy.development._supervisor import recover_run
from autonomy.development._workspace import Limits
from autonomy.membership import Finding
from autonomy.run import RunRefused


@pytest.fixture
def delegated():
    from autonomy.development import _delegated

    return _delegated


class FakeCgroup:
    def __init__(
        self,
        path: Path,
        *,
        removable: bool = True,
        occupied_polls: int = 0,
        stays_occupied: bool = False,
    ) -> None:
        self.path = path
        self.removable = removable
        self.occupied_polls = occupied_polls
        self.stays_occupied = stays_occupied
        self.killed = 0
        self.removed = 0
        self._polls = 0

    def create(self, *, memory_bytes: int, tasks: int) -> None:
        self.path.mkdir(parents=True, exist_ok=True)

    def check(self, pid: int, *, memory_bytes: int, tasks: int) -> None:
        pass

    def empty(self) -> bool:
        if self.stays_occupied:
            return False
        self._polls += 1
        return self._polls > self.occupied_polls

    def kill(self) -> None:
        self.killed += 1
        if not self.stays_occupied:
            self.occupied_polls = 0

    def remove(self, *, wait: float) -> bool:
        self.removed += 1
        return self.removable and not self.stays_occupied


def _local_dir(tmp_path: Path) -> Path:
    # Ensure ext4/xfs/btrfs storage for allowance.storage() qualification.
    root = tmp_path / "local"
    root.mkdir(mode=0o700)
    return root


def _setup_host_and_grant(delegated, tmp_path: Path, *, starts: int = 4):
    from autonomy.delegation import definition

    base_dir = _local_dir(tmp_path)
    config_dir = base_dir / "config"
    config_dir.mkdir(mode=0o700)
    store_dir = base_dir / "store"
    store_dir.mkdir(mode=0o700)
    info = store_dir.stat()
    publish_bytes(
        config_dir / "allowance-storage.json",
        json.dumps({"version": 1, "path": str(store_dir), "device": info.st_dev, "inode": info.st_ino}).encode("utf-8"),
    )
    repo_dir = base_dir / "repo"
    repo_dir.mkdir()

    cgroups_map: dict[tuple[str, str], FakeCgroup] = {}

    def get_cg(unit_cgroup: str, run_id: str) -> FakeCgroup:
        key = (unit_cgroup, run_id)
        if key not in cgroups_map:
            cgroups_map[key] = FakeCgroup(base_dir / "cgroups" / f"actor-{run_id}")
        return cgroups_map[key]

    uid = os.getuid()
    unit_cg = f"/user.slice/user-{uid}.slice/user@{uid}.service/band.service"
    host = Host(
        config=config_dir,
        cgroup=f"{unit_cg}/main",
        cgroups=base_dir / "cgroups",
        show=lambda _u: {},
        actor_cgroup=get_cg,
    )
    ceil = delegated.ceiling(Limits())
    cfg = definition(
        {
            "kind": "development-delegation.v1",
            "delegation_id": "del-1",
            "source": "autonomy-a22882 fixture",
            "expires": int(time.time()) + 3600,
            "orchestrator": {"name": "band", "unit": "band.service"},
            "repositories": {"autonomy": {"path": str(repo_dir), "ref": "refs/heads/main"}},
            "actors": {"run": ["/usr/bin/true"]},
            "limits": {
                "starts": starts,
                "deadline_seconds": 30,
                "writable_bytes": 96 << 20,
                "memory_bytes": 416 << 20,
                "tasks": 64,
            },
            "model": None,
        },
        ceil,
    )
    grant = Delegation.issue(store_dir, cfg)
    places = development_places(
        {
            "XDG_STATE_HOME": str(base_dir / "state"),
            "XDG_CACHE_HOME": str(base_dir / "cache"),
            "XDG_CONFIG_HOME": str(config_dir),
        }
    )
    return host, grant, places, repo_dir, unit_cg, cgroups_map


def _record_start(
    grant: Delegation,
    places: DevelopmentPlaces,
    unit_cg: str,
    attempt: str,
    run_id: str,
    *,
    allocated: bool,
) -> int:
    ordinal = grant.begin(
        Start(
            ordinal=0,
            attempt=attempt,
            run=run_id,
            at=int(time.time()),
            state=places.state,
            cache=places.cache,
            repository="autonomy",
            actor="run",
            base="a" * 40,
            deadline=10.0,
            unit="band.service",
            cgroup=unit_cg,
            invocation="b" * 32,
            allocated=False,
            outcome=None,
            disposition_sha256=None,
        ),
        margin=30.0,
    )
    if allocated:
        grant.mark(run_id)
    return ordinal


def _write_run_verdict(
    places: DevelopmentPlaces,
    repo_dir: Path,
    run_id: str,
    disposition: str,
    *,
    containment_proven: bool = True,
) -> str:
    with allocate_run(places, repository=repo_dir, base="a" * 40, deadline_seconds=10.0, run_id=run_id) as run:
        base_path = run.run_dir / "base.bundle"
        base_path.write_bytes(b"base")
        base_digest = hashlib.sha256(b"base").hexdigest()
        walk_digest = publish_json(run.run_dir / "walk.json", {"trees": []})
        grant_digest = publish_grant(
            run,
            base_sha256=base_digest,
            walk_sha256=walk_digest,
            read_only=(),
            denied=(),
            stdio=("null", "null", "null"),
            limits={"deadline_seconds": 10.0},
        )
        candidate_digest = None
        findings = []
        if disposition == "clean":
            bundle_path = run.run_dir / "candidate.bundle"
            bundle_path.write_bytes(b"bundle")
            candidate_digest = publish_json(
                run.run_dir / "candidate.json",
                {
                    "version": 2,
                    "run": run.run_id,
                    "mode": "development",
                    "base": "a" * 40,
                    "ref": "refs/heads/development",
                    "tip": "b" * 40,
                    "base_sha256": base_digest,
                    "bundle_sha256": hashlib.sha256(b"bundle").hexdigest(),
                    "grant_sha256": grant_digest,
                    "actor_exit": 0,
                    "closed_at": "2026-11-25T00:00:00Z",
                },
            )
        elif disposition == "quarantined":
            findings.append(Finding("development-actor-failed", "development", "failed"))
        else:
            findings.append(Finding("development-workspace-unproven", "development", "unwired"))
        with publication_lock(run):
            publish_terminal(
                run,
                findings,
                grant_sha256=grant_digest,
                candidate_sha256=candidate_digest,
                containment_proven=containment_proven,
            )
        return hashlib.sha256((run.run_dir / "disposition.json").read_bytes()).hexdigest()


def test_settle_outcomes(delegated, tmp_path):
    host, grant, places, repo_dir, unit_cg, _ = _setup_host_and_grant(delegated, tmp_path, starts=6)
    d1 = _write_run_verdict(places, repo_dir, "1" * 32, "clean")
    _record_start(grant, places, unit_cg, "att-1", "1" * 32, allocated=True)
    with grant.lock(wait=1.0):
        delegated.settle(grant, host)

    d2 = _write_run_verdict(places, repo_dir, "2" * 32, "quarantined")
    _record_start(grant, places, unit_cg, "att-2", "2" * 32, allocated=True)
    with grant.lock(wait=1.0):
        delegated.settle(grant, host)

    d3 = _write_run_verdict(places, repo_dir, "3" * 32, "unwired")
    _record_start(grant, places, unit_cg, "att-3", "3" * 32, allocated=True)
    with grant.lock(wait=1.0):
        delegated.settle(grant, host)

    # Unmarked without a verdict -> not-allocated
    _record_start(grant, places, unit_cg, "att-4", "4" * 32, allocated=False)
    # Unmarked WITH a verdict -> verdict's disposition and digest
    d5 = _write_run_verdict(places, repo_dir, "5" * 32, "quarantined")
    _record_start(grant, places, unit_cg, "att-5", "5" * 32, allocated=False)
    # Marked WITHOUT a verdict -> remains unfinished (outcome is None)
    with allocate_run(places, repository=repo_dir, base="a" * 40, deadline_seconds=10.0, run_id="6" * 32):
        pass
    _record_start(grant, places, unit_cg, "att-6", "6" * 32, allocated=True)

    with grant.lock(wait=1.0):
        delegated.settle(grant, host)

    rows = grant.starts()
    assert [(r.attempt, r.outcome, r.disposition_sha256) for r in rows] == [
        ("att-1", "clean", d1),
        ("att-2", "quarantined", d2),
        ("att-3", "unwired", d3),
        ("att-4", "not-allocated", None),
        ("att-5", "quarantined", d5),
        ("att-6", None, None),
    ]
    assert grant.grant().closed is None


def test_unproven_containment_closes_the_grant(delegated, tmp_path):
    host, grant, places, repo_dir, unit_cg, _ = _setup_host_and_grant(delegated, tmp_path, starts=2)
    digest = _write_run_verdict(places, repo_dir, "1" * 32, "quarantined", containment_proven=False)
    _record_start(grant, places, unit_cg, "att-1", "1" * 32, allocated=True)
    with grant.lock(wait=1.0):
        delegated.settle(grant, host)
    assert grant.grant().closed == "containment"
    assert grant.starts()[0].outcome == "quarantined"
    assert grant.starts()[0].disposition_sha256 == digest


def test_a_cgroup_that_will_not_empty_closes_the_grant(delegated, tmp_path):
    host, grant, places, repo_dir, unit_cg, cgroups = _setup_host_and_grant(delegated, tmp_path, starts=2)
    run_id = "1" * 32
    _write_run_verdict(places, repo_dir, run_id, "clean", containment_proven=True)
    _record_start(grant, places, unit_cg, "att-1", run_id, allocated=True)
    cgroups[(unit_cg, run_id)] = FakeCgroup(tmp_path / "stuck-cg", removable=False)
    with grant.lock(wait=1.0):
        delegated.settle(grant, host)
    assert grant.grant().closed == "containment"
    assert grant.starts()[0].outcome == "clean"


def test_confirmed_recovery_and_reboot_do_not_close(delegated, tmp_path, monkeypatch):
    from autonomy.development import _supervisor

    host, grant, places, repo_dir, unit_cg, _ = _setup_host_and_grant(delegated, tmp_path, starts=3)
    # 1. Same-boot confirmed recovery (exited PID)
    r1 = "1" * 32
    with allocate_run(places, repository=repo_dir, base="a" * 40, deadline_seconds=10.0, run_id=r1) as run1:
        g1 = publish_grant(
            run1, base_sha256="1" * 64, walk_sha256="2" * 64, read_only=(), denied=(),
            stdio=("null", "null", "null"), limits={},
        )
        append_event(run1.run_dir, "releasing", child_pid=2_000_000_000, start_time=1, boot_id=run1.boot_id, grant_sha256=g1)
    assert recover_run(run1) == 3
    _record_start(grant, places, unit_cg, "att-1", r1, allocated=True)
    with grant.lock(wait=1.0):
        delegated.settle(grant, host)
    assert grant.grant().closed is None

    # 2. Torn journal after reboot
    r2 = "2" * 32
    with allocate_run(places, repository=repo_dir, base="a" * 40, deadline_seconds=10.0, run_id=r2) as run2:
        publish_grant(
            run2, base_sha256="1" * 64, walk_sha256="2" * 64, read_only=(), denied=(),
            stdio=("null", "null", "null"), limits={},
        )
        with (run2.run_dir / "events.jsonl").open("a") as stream:
            stream.write('{"event":"releasing"')
    monkeypatch.setattr(_supervisor, "boot_id", lambda: "00000000-0000-0000-0000-000000000099")
    assert recover_run(run2) == 3
    _record_start(grant, places, unit_cg, "att-2", r2, allocated=True)
    with grant.lock(wait=1.0):
        delegated.settle(grant, host)
    assert grant.grant().closed is None
    assert [s.outcome for s in grant.starts()] == ["quarantined", "quarantined"]


def test_last_start_is_settled_by_report(delegated, tmp_path):
    host, grant, places, repo_dir, unit_cg, _ = _setup_host_and_grant(delegated, tmp_path, starts=2)
    # First start: unmarked with a leftover run directory
    r1 = "1" * 32
    leftover_dir = places.state / "runs" / r1
    leftover_dir.mkdir(parents=True)
    _record_start(grant, places, unit_cg, "att-1", r1, allocated=False)
    doc1 = delegated.report(grant, host)
    assert doc1["starts_left"] == 1
    assert doc1["starts"][0]["outcome"] == "not-allocated"
    assert doc1["starts"][0]["leftover"] == [str(leftover_dir)]

    # Last start: marked, clean verdict written, settled by report itself
    r2 = "2" * 32
    digest = _write_run_verdict(places, repo_dir, r2, "clean")
    _record_start(grant, places, unit_cg, "att-2", r2, allocated=True)
    doc2 = delegated.report(grant, host)
    assert doc2["starts_left"] == 0
    assert doc2["starts"][1]["outcome"] == "clean"
    assert doc2["starts"][1]["disposition_sha256"] == digest
    filtered = delegated.report(grant, host, attempt="att-2")
    assert [row["attempt"] for row in filtered["starts"]] == ["att-2"]


def test_report_distinguishes_running_and_unfinished(delegated, tmp_path):
    host, grant, places, repo_dir, unit_cg, _ = _setup_host_and_grant(delegated, tmp_path, starts=2)
    run_id = "1" * 32
    with allocate_run(places, repository=repo_dir, base="a" * 40, deadline_seconds=10.0, run_id=run_id):
        pass
    _record_start(grant, places, unit_cg, "att-1", run_id, allocated=True)

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl, sys, time; f = open(sys.argv[1], 'r+b'); "
            "fcntl.flock(f, fcntl.LOCK_EX); sys.stdout.write('held\\n'); sys.stdout.flush(); time.sleep(10)",
            str(grant.lock_path),
        ],
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert holder.stdout.readline() == b"held\n"
        while_held = delegated.report(grant, host)
        assert while_held["starts"][0]["outcome"] == "running"
    finally:
        holder.kill()
        holder.wait(timeout=5)

    when_free = delegated.report(grant, host)
    assert when_free["starts"][0]["outcome"] == "unfinished"


def test_report_of_an_attempt_that_never_started(delegated, tmp_path):
    host, grant, *_ = _setup_host_and_grant(delegated, tmp_path, starts=2)
    doc = delegated.report(grant, host, attempt="never-started")
    assert doc["starts"] == []
    assert doc["starts_left"] == 2


@pytest.mark.parametrize("damage", ["root-removed", "run-truncated", "disposition-unreadable"])
def test_missing_or_damaged_roots_leave_the_start_unfinished(delegated, tmp_path, damage):
    host, grant, places, repo_dir, unit_cg, _ = _setup_host_and_grant(delegated, tmp_path, starts=2)
    run_id = "1" * 32
    _write_run_verdict(places, repo_dir, run_id, "clean")
    _record_start(grant, places, unit_cg, "att-1", run_id, allocated=True)

    run_dir = places.state / "runs" / run_id
    disp = run_dir / "disposition.json"
    try:
        if damage == "root-removed":
            shutil.rmtree(places.state)
        elif damage == "run-truncated":
            (run_dir / "run.json").write_text("{", encoding="utf-8")
        else:
            disp.chmod(0)

        doc = delegated.report(grant, host)
        assert doc["starts"][0]["outcome"] == "unfinished"
    finally:
        if damage == "disposition-unreadable" and disp.exists():
            disp.chmod(0o600)


def test_closure_commits_before_settling(delegated, tmp_path, monkeypatch):
    host, grant, places, _repo_dir, unit_cg, _ = _setup_host_and_grant(delegated, tmp_path, starts=2)
    observed = []
    real_settle = delegated.settle

    def check_during_settle(g, h):
        assert g.grant().closed == "revoked"
        second = Delegation(g.root, g.name)
        with pytest.raises(RunRefused) as caught:
            _record_start(second, places, unit_cg, "att-after-revoke", "9" * 32, allocated=False)
        assert caught.value.code == "delegation-closed"
        observed.append(True)
        return real_settle(g, h)

    monkeypatch.setattr(delegated, "settle", check_during_settle)
    res = delegated.revoke(grant, host)
    assert observed == [True]
    assert res == delegated.Revocation(cause="revoked", first=None, actor="empty", acknowledged=True)


@pytest.mark.parametrize("has_run_dir", [False, True])
def test_revoke_before_the_mark(delegated, tmp_path, has_run_dir):
    host, grant, places, repo_dir, unit_cg, _ = _setup_host_and_grant(delegated, tmp_path, starts=2)
    run_id = "1" * 32
    if has_run_dir:
        with allocate_run(places, repository=repo_dir, base="a" * 40, deadline_seconds=10.0, run_id=run_id):
            pass
    _record_start(grant, places, unit_cg, "att-1", run_id, allocated=False)
    res = delegated.revoke(grant, host)
    assert res == delegated.Revocation(cause="revoked", first=None, actor="empty", acknowledged=True)
    with pytest.raises(RunRefused) as caught:
        grant.mark(run_id)
    assert caught.value.code == "delegation-closed"


def test_stop_wins(delegated, tmp_path):
    host, grant, places, repo_dir, unit_cg, _ = _setup_host_and_grant(delegated, tmp_path, starts=2)
    run_id = "1" * 32
    with allocate_run(places, repository=repo_dir, base="a" * 40, deadline_seconds=10.0, run_id=run_id):
        pass
    _record_start(grant, places, unit_cg, "att-1", run_id, allocated=True)
    res = delegated.revoke(grant, host, stop_wait=0.2, kill_wait=0.2)
    assert res == delegated.Revocation(cause="revoked", first="stop", actor="empty", acknowledged=True)
    assert (places.state / "runs" / run_id / "stop.json").is_file()


def test_verdict_wins(delegated, tmp_path):
    host, grant, places, repo_dir, unit_cg, _ = _setup_host_and_grant(delegated, tmp_path, starts=2)
    run_id = "1" * 32
    _write_run_verdict(places, repo_dir, run_id, "clean")
    _record_start(grant, places, unit_cg, "att-1", run_id, allocated=True)

    # Hold <id>.lock as if the supervisor is in step 10 right after writing disposition.json.
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl, sys, time; f = open(sys.argv[1], 'r+b'); "
            "fcntl.flock(f, fcntl.LOCK_EX); sys.stdout.write('held\\n'); sys.stdout.flush(); time.sleep(10)",
            str(grant.lock_path),
        ],
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert holder.stdout.readline() == b"held\n"
        res = delegated.revoke(grant, host, stop_wait=0.2, kill_wait=0.2)
    finally:
        holder.kill()
        holder.wait(timeout=5)
    assert res == delegated.Revocation(cause="revoked", first="verdict", actor="empty", acknowledged=True)
    assert not (places.state / "runs" / run_id / "stop.json").exists()


def test_revoke_ends_a_stopped_supervisors_actor(delegated, tmp_path):
    host, grant, places, repo_dir, unit_cg, cgroups = _setup_host_and_grant(delegated, tmp_path, starts=2)
    run_id = "1" * 32
    with allocate_run(places, repository=repo_dir, base="a" * 40, deadline_seconds=10.0, run_id=run_id):
        pass
    _record_start(grant, places, unit_cg, "att-1", run_id, allocated=True)
    cg = FakeCgroup(tmp_path / "actor-cg", occupied_polls=10_000)
    cgroups[(unit_cg, run_id)] = cg

    # Hold <id>.lock so initial settle skips (simulating a SIGSTOPped supervisor).
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl, sys, time; f = open(sys.argv[1], 'r+b'); "
            "fcntl.flock(f, fcntl.LOCK_EX); sys.stdout.write('held\\n'); sys.stdout.flush(); time.sleep(10)",
            str(grant.lock_path),
        ],
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert holder.stdout.readline() == b"held\n"
        res = delegated.revoke(grant, host, stop_wait=0.08, kill_wait=0.2)
    finally:
        holder.kill()
        holder.wait(timeout=5)
    assert cg.killed == 1
    assert res == delegated.Revocation(cause="revoked", first="stop", actor="empty", acknowledged=True)


def test_revoke_lets_a_live_supervisor_finish(delegated, tmp_path):
    host, grant, places, repo_dir, unit_cg, cgroups = _setup_host_and_grant(delegated, tmp_path, starts=2)
    run_id = "1" * 32
    with allocate_run(places, repository=repo_dir, base="a" * 40, deadline_seconds=10.0, run_id=run_id):
        pass
    _record_start(grant, places, unit_cg, "att-1", run_id, allocated=True)
    cg = FakeCgroup(tmp_path / "actor-cg", occupied_polls=2)
    cgroups[(unit_cg, run_id)] = cg

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl, sys, time; f = open(sys.argv[1], 'r+b'); "
            "fcntl.flock(f, fcntl.LOCK_EX); sys.stdout.write('held\\n'); sys.stdout.flush(); time.sleep(10)",
            str(grant.lock_path),
        ],
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert holder.stdout.readline() == b"held\n"
        res = delegated.revoke(grant, host, stop_wait=0.5, kill_wait=0.2)
    finally:
        holder.kill()
        holder.wait(timeout=5)
    assert cg.killed == 0
    assert res == delegated.Revocation(cause="revoked", first="stop", actor="empty", acknowledged=True)


@pytest.mark.parametrize("scenario", ["held-publication-lock", "missing-roots", "cgroup-occupied"])
def test_revoke_unacknowledged_cases(delegated, tmp_path, scenario):
    host, grant, places, repo_dir, unit_cg, cgroups = _setup_host_and_grant(delegated, tmp_path, starts=2)
    run_id = "1" * 32
    with allocate_run(places, repository=repo_dir, base="a" * 40, deadline_seconds=10.0, run_id=run_id) as run:
        pass
    _record_start(grant, places, unit_cg, "att-1", run_id, allocated=True)
    cg = FakeCgroup(
        tmp_path / "actor-cg",
        occupied_polls=10_000,
        stays_occupied=(scenario == "cgroup-occupied"),
    )
    cgroups[(unit_cg, run_id)] = cg

    # Hold <id>.lock so initial settle does not run remove() before step 1/2.
    grant_holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl, sys, time; f = open(sys.argv[1], 'r+b'); "
            "fcntl.flock(f, fcntl.LOCK_EX); sys.stdout.write('held\\n'); sys.stdout.flush(); time.sleep(10)",
            str(grant.lock_path),
        ],
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    pub_holder = None
    try:
        assert grant_holder.stdout.readline() == b"held\n"
        if scenario == "held-publication-lock":
            pub_holder = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import fcntl, sys, time; f = open(sys.argv[1], 'rb'); "
                    "fcntl.flock(f, fcntl.LOCK_EX); sys.stdout.write('held\\n'); sys.stdout.flush(); time.sleep(10)",
                    str(run.run_dir / "publication.lock"),
                ],
                env={"PATH": os.defpath, "HOME": str(tmp_path)},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            assert pub_holder.stdout.readline() == b"held\n"
        elif scenario == "missing-roots":
            shutil.rmtree(places.state)

        res = delegated.revoke(grant, host, lock_wait=0.05, stop_wait=0.05, kill_wait=0.05)
    finally:
        if pub_holder is not None:
            pub_holder.kill()
            pub_holder.wait(timeout=5)
        grant_holder.kill()
        grant_holder.wait(timeout=5)

    assert res.acknowledged is False
    assert cg.killed == 1
    assert grant.grant().closed == "revoked"
    if scenario == "cgroup-occupied":
        assert res.actor == "occupied" and res.first == "stop"
    else:
        assert res.actor == "empty" and res.first is None


def test_revoke_is_idempotent(delegated, tmp_path):
    host, grant, places, repo_dir, unit_cg, _ = _setup_host_and_grant(delegated, tmp_path, starts=2)
    run_id = "1" * 32
    with allocate_run(places, repository=repo_dir, base="a" * 40, deadline_seconds=10.0, run_id=run_id) as run:
        pass
    _record_start(grant, places, unit_cg, "att-1", run_id, allocated=True)

    first = delegated.revoke(grant, host, stop_wait=0.1, kill_wait=0.1)
    saved_stop = (run.run_dir / "stop.json").read_bytes()
    second = delegated.revoke(grant, host, stop_wait=0.1, kill_wait=0.1)
    assert first == second == delegated.Revocation(cause="revoked", first="stop", actor="empty", acknowledged=True)
    assert (run.run_dir / "stop.json").read_bytes() == saved_stop
