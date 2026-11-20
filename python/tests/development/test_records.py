import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from autonomy.membership import Finding
from autonomy.run import RunRefused
from builders import INCOMPLETE  # nested test modules see the shared test helpers


BASE = "a" * 40
LIMITS = {
    "deadline_seconds": 10.0, "base_bytes": 100, "candidate_bytes": 50,
    "actor_fsize_bytes": 100, "prepare_seconds": 10, "receiver_seconds": 5,
    "receiver_memory_bytes": 1024, "receiver_storage_bytes": 512,
}


@pytest.fixture
def records():
    from autonomy.development import _records
    return _records


@pytest.fixture
def places(records, tmp_path):
    return records.development_places({
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
    })


@pytest.fixture
def run(records, places, tmp_path):
    with records.allocate_run(places, repository=tmp_path / "repo", base=BASE, deadline_seconds=10.0) as opened:
        yield opened


def test_allocates_development_without_runtime_dir(places, run):
    assert run.run_dir == places.state / "runs" / run.run_id
    assert run.scratch == places.cache / "scratch" / run.run_id
    assert {p.name for p in run.run_dir.iterdir()} == {
        "run.json", "events.jsonl", "supervisor.lock", "publication.lock",
    }
    assert run.run_dir.stat().st_mode & 0o777 == 0o700
    assert run.scratch.stat().st_mode & 0o777 == 0o700


def test_closed_allocation_removes_both_empty_directories_on_failure(records, places, tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("staging failed")

    monkeypatch.setattr(records, "append_event", refuse)
    with pytest.raises(RunRefused, match="allocation-failed"):
        with records.allocate_run(places, repository=tmp_path, base=BASE, deadline_seconds=10.0):
            pytest.fail("allocated")
    assert not any((places.state / "runs").iterdir())
    assert not any((places.cache / "scratch").iterdir())


def probe_lock(path, tmp_path):
    return subprocess.run(
        [sys.executable, "-c",
         "import fcntl,sys; f=open(sys.argv[1], 'rb'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)",
         str(path)],
        env={"PATH": os.defpath, "HOME": str(tmp_path)}, capture_output=True, timeout=5, check=False,
    )


def test_ownership_is_held_before_run_identity_is_visible(records, places, tmp_path, monkeypatch):
    real = records.publish_json

    def publish(path, value):
        if path.name == "run.json":
            assert not path.exists()
            assert probe_lock(path.parent / "supervisor.lock", tmp_path).returncode != 0
        return real(path, value)

    monkeypatch.setattr(records, "publish_json", publish)
    with records.allocate_run(places, repository=tmp_path, base=BASE, deadline_seconds=10.0) as run:
        with pytest.raises(RunRefused, match="development-supervisor-live"):
            with records.supervisor_lock(run):
                pytest.fail("a live run was claimed")


def test_publication_lock_is_independent_of_supervisor_ownership(records, run, tmp_path):
    with records.publication_lock(run):
        assert probe_lock(run.run_dir / "publication.lock", tmp_path).returncode != 0
    assert probe_lock(run.run_dir / "publication.lock", tmp_path).returncode == 0
    assert probe_lock(run.run_dir / "supervisor.lock", tmp_path).returncode != 0


def test_development_records_match_the_approved_schema(records, places, run, tmp_path):
    header = records.read_json(run.run_dir / "run.json")
    assert set(header) == {
        "version", "run", "mode", "created_at", "repository", "base", "ref", "deadline_seconds", "scratch",
    }
    assert (header["run"], header["mode"], header["base"], header["repository"]) == (
        run.run_id, "development", BASE, str(tmp_path / "repo"),
    )
    assert records.lookup_run(places, run.run_id) == run
    assert records.read_json(run.run_dir / "events.jsonl")["event"] == "allocated"
    for invalid in ("../outside", "b" * 32, str(INCOMPLETE)):
        with pytest.raises(RunRefused, match="development-run-invalid"):
            records.lookup_run(places, invalid)
    for field, value in (("mode", "science"), ("scratch", str(tmp_path))):
        invalid_header = {**header, field: value}
        (run.run_dir / "run.json").write_text(json.dumps(invalid_header))
        with pytest.raises(RunRefused, match="development-run-invalid"):
            records.lookup_run(places, run.run_id)


def grant(records, run, *, base_digest="1" * 64, walk_digest="2" * 64):
    return records.publish_grant(
        run, base_sha256=base_digest, walk_sha256=walk_digest,
        read_only=(Path("/usr"), Path("/etc")), denied=(Path("/secret"),),
        stdio=("pipe", "socket", "null"), limits=LIMITS,
    )


def test_grant_binds_exact_run_header_and_effective_scope(records, run):
    digest = grant(records, run)
    path = run.run_dir / "grant.json"
    saved = records.read_json(path)
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert saved["run_sha256"] == hashlib.sha256((run.run_dir / "run.json").read_bytes()).hexdigest()
    assert saved["scope"] == {"read_only": ["/usr", "/etc"], "denied": ["/secret"], "walk_sha256": "2" * 64}
    assert saved["stdio"] == {"stdin": "pipe", "stdout": "socket", "stderr": "null"}
    assert saved["limits"] == LIMITS
    assert saved["route"] is None and saved["allowance"] is None


def test_failed_grant_publication_leaves_no_confirmed_digest(records, run, monkeypatch):
    def no_write(*args, **kwargs):
        raise OSError("storage unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(records, "publish_json", no_write)
        with pytest.raises(records.DevelopmentAborted) as aborted:
            grant(records, run)
    assert aborted.value.finding.code == "development-gate-unproven"
    assert not (run.run_dir / "grant.json").exists()
    with records.publication_lock(run):
        assert records.publish_terminal(run, [aborted.value.finding], grant_sha256=None, candidate_sha256=None) == 4
    assert records.read_json(run.run_dir / "disposition.json")["grant_sha256"] is None


def test_terminal_publication_is_immutable_and_requires_durable_inputs(records, run, monkeypatch):
    assert records.terminal_exit(run) is None
    bundle_path = run.run_dir / "candidate.bundle"
    bundle_path.write_bytes(b"validated fixture bytes")
    base_path = run.run_dir / "base.bundle"
    base_path.write_bytes(b"pinned fixture bytes")
    base_digest = hashlib.sha256(base_path.read_bytes()).hexdigest()
    walk_digest = records.publish_json(run.run_dir / "walk.json", {"fixture": True})
    grant_digest = grant(records, run, base_digest=base_digest, walk_digest=walk_digest)
    candidate = {
        "version": 1, "run": run.run_id, "mode": "development", "base": BASE,
        "ref": "refs/heads/development", "tip": "b" * 40,
        "base_sha256": base_digest, "grant_sha256": grant_digest, "actor_exit": 0,
        "closed_at": "2026-11-20T00:00:00Z", "bundle_sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
    }
    digest = records.publish_json(run.run_dir / "candidate.json", candidate)
    path = run.run_dir / "disposition.json"
    with records.publication_lock(run):
        with pytest.raises((ValueError, OSError)):
            records.publish_terminal(run, [], grant_sha256=grant_digest, candidate_sha256="3" * 64)
        assert not path.exists()

        def fail_publish(*args, **kwargs):
            raise OSError("terminal publication failed")

        with monkeypatch.context() as patch:
            patch.setattr(records, "publish_json", fail_publish)
            with pytest.raises(OSError):
                records.publish_terminal(run, [], grant_sha256=grant_digest, candidate_sha256=digest)
        assert records.terminal_exit(run) is None
        assert records.publish_terminal(run, [], grant_sha256=grant_digest, candidate_sha256=digest) == 0
        saved = path.read_bytes()
        with pytest.raises(FileExistsError):
            records.publish_terminal(run, [Finding("development-stopped", "stop.json", "stopped")],
                                     grant_sha256=grant_digest, candidate_sha256=None)
    assert path.read_bytes() == saved
    assert records.terminal_exit(run) == 0
    bundle_path.write_bytes(b"changed")
    with pytest.raises(RunRefused, match="development-run-invalid"):
        records.terminal_exit(run)


def test_first_use_syncs_ancestry_before_publishing_run(records, places, tmp_path, monkeypatch):
    synced = []
    publish = records.publish_json

    def observe(directory):
        synced.append(directory)

    def verify_publish(path, value):
        for chain in ((tmp_path, places.state.parent, places.state, places.state / "runs"),
                      (tmp_path, places.cache.parent, places.cache, places.cache / "scratch")):
            assert [synced.index(part) for part in chain] == sorted(synced.index(part) for part in chain)
        return publish(path, value)

    monkeypatch.setattr(records, "fsync_dir", observe)
    monkeypatch.setattr(records, "publish_json", verify_publish)
    with records.allocate_run(places, repository=tmp_path / "source", base=BASE, deadline_seconds=10.0):
        pass


def test_first_use_ancestor_sync_failure_refuses_before_record(records, places, tmp_path, monkeypatch):
    sync = records.fsync_dir

    def refuse(directory):
        if directory == places.state.parent:
            raise OSError("fixture ancestor sync failure")
        sync(directory)

    monkeypatch.setattr(records, "fsync_dir", refuse)
    with pytest.raises(RunRefused, match="allocation-failed.*ancestor sync failure"):
        with records.allocate_run(places, repository=tmp_path / "source", base=BASE, deadline_seconds=10.0):
            pytest.fail("allocated after an unsynced new ancestor")
    assert not (places.state / "runs").exists()
    assert not (places.cache / "scratch").exists()
