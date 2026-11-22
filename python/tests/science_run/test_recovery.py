"""Protected control lookup and classification after supervisor death."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path

import pytest

from autonomy.baseline import append_event
from autonomy.endpoint import SessionOpen
from autonomy.ledger import Ledger
from autonomy.process import ProcessIdentity
from autonomy.run import RunRefused, allocate, places
from autonomy.tiers import REPORT_ONLY
from test_run import _opened, _opening, _science_world


@pytest.fixture
def env(tmp_path):
    for name in ("state", "cache", "runtime", "home", "config"):
        (tmp_path / name).mkdir()
    return {
        "HOME": str(tmp_path / "home"), "PATH": "/usr/bin",
        "XDG_STATE_HOME": str(tmp_path / "state"), "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_RUNTIME_DIR": str(tmp_path / "runtime"), "XDG_CONFIG_HOME": str(tmp_path / "config"),
    }


def control(action, run_id, env):
    from autonomy.science_run import control as command

    output = []
    code = command(action, run_id, env, diag=lambda _: None, emit=output.append)
    return code, output


def test_pre_baseline_orphan_closes_from_state_alone(env):
    dirs = allocate(places(env))
    del env["XDG_RUNTIME_DIR"]
    code, (first,) = control("close", dirs.run_id, env)
    assert code == 4
    record = json.loads(first)
    assert record["members"] == {} and record["closing_heads"] is None
    assert {finding["code"] for finding in record["findings"]} == {"baseline-unavailable", "orchestrator-lost"}
    assert control("close", dirs.run_id, env) == (4, [first])
    assert first.encode() == (dirs.run_dir / "disposition.json").read_bytes()


def test_two_concurrent_closes_emit_identical_terminal_bytes(env):
    dirs = allocate(places(env))
    with ThreadPoolExecutor(2) as workers:
        first = workers.submit(control, "close", dirs.run_id, env)
        second = workers.submit(control, "close", dirs.run_id, env)
        assert first.result(timeout=5) == second.result(timeout=5)


def test_invalid_ids_and_symlink_run_paths_are_refused(env):
    dirs = allocate(places(env))
    link = dirs.run_dir.parent / ("2" * 32)
    link.symlink_to(dirs.run_dir, target_is_directory=True)
    for run_id in ("../run", link.name):
        with pytest.raises(RunRefused):
            control("close", run_id, env)
    assert not (dirs.run_dir / "disposition.json").exists()


def test_damaged_development_header_cannot_be_used_as_science(env):
    from autonomy.baseline import publish_json

    dirs = allocate(places(env))
    publish_json(dirs.run_dir / "run.json", {"version": 1, "mode": "development", "run": dirs.run_id})
    with pytest.raises(RunRefused):
        control("close", dirs.run_id, env)
    assert not (dirs.run_dir / "disposition.json").exists()


def _prepared(tmp_path, env, monkeypatch, *, endpoint_pid=None):
    running = ProcessIdentity.capture(os.getpid())
    survivor = ProcessIdentity(running.pid, running.start_time + 1, running.boot_id)
    monkeypatch.setattr(ProcessIdentity, "capture", classmethod(lambda cls, pid: survivor))
    configured, calls = _science_world(tmp_path / "world", env)
    where = places(configured)
    admission = _opening(configured)
    with admission.open(where, None) as dirs:
        opening = admission.capture(_opened(admission, dirs, where))
    endpoint = ProcessIdentity(endpoint_pid, survivor.start_time, survivor.boot_id) if endpoint_pid else survivor
    append_event(dirs.run_dir, "endpoint-starting", **endpoint.fields())
    return dirs, opening, configured, calls


def test_unconfirmed_endpoint_prevents_chain_reads_and_terminal_publication(tmp_path, env, monkeypatch):
    dirs, _, configured, calls = _prepared(tmp_path, env, monkeypatch, endpoint_pid=1)

    def pin(self):
        if self.pid == 1:
            raise PermissionError("cannot verify endpoint")
        return None

    monkeypatch.setattr(ProcessIdentity, "pin", pin)
    with pytest.raises(RunRefused, match="confirm"):
        control("close", dirs.run_id, configured)
    assert calls.read_text() == "resolve\n"
    assert not (dirs.run_dir / "disposition.json").exists()


@pytest.mark.parametrize("change", ["config-edit", "retarget", "corrupt-baseline"])
def test_changed_inputs_settle_after_the_endpoint_is_dead(tmp_path, env, monkeypatch, change):
    dirs, opening, configured, calls = _prepared(tmp_path, env, monkeypatch)
    config = Path(configured["SCIENCE_CONFIG"])
    if change == "config-edit":
        config.write_text(config.read_text() + "# operator comment\n")
    elif change == "retarget":
        config.write_text(config.read_text().replace('operations_root = "operations"', 'operations_root = "replacement"'))
    else:
        (dirs.run_dir / "baseline.json").write_text("{conflicting")
        with pytest.raises(RunRefused, match=dirs.run_id):
            with _opening(configured).open(places(env), None):
                pytest.fail("corrupt baseline ignored before recovery")
    code, (out,) = control("close", dirs.run_id, configured)
    record = json.loads(out)
    assert code == 4
    codes = {finding["code"] for finding in record["findings"]}
    assert "orchestrator-lost" in codes
    assert ("baseline-unavailable" if change == "corrupt-baseline" else "read-unavailable") in codes
    if change == "config-edit":
        assert "detached" in calls.read_text()
    else:
        assert calls.read_text() == "resolve\n"
        assert record["closing_heads"] is None
    assert control("close", dirs.run_id, configured) == (code, [out])


def test_file_only_seal_needs_matching_session_close_and_no_failure(tmp_path, env, monkeypatch):
    from autonomy.baseline import publish_json
    from autonomy.science_run._recovery import trusted_seal

    dirs, opening, _, _ = _prepared(tmp_path, env, monkeypatch)
    published = {"cause": "eof", "basis_seal": None, "sealed_tips": [
        {"role": chain.role, "id": chain.chain_id, "genesis": chain.genesis, "tip": chain.tip}
        for chain in opening.written
    ]}
    publish_json(dirs.run_dir / "seal.json", published)
    sid = "d" * 32
    session = SessionOpen(sid, opening.config.operations / "sessions" / sid / "ledger.v1", "a" * 64)
    closed = Ledger(sid, f"session:{sid}", REPORT_ONLY.permit, (), (), True, False,
                    world=opening.config.world_id)
    events = [{"event": "session-open"}]
    from dataclasses import replace

    assert trusted_seal(dirs.run_dir, opening.written, session, closed, events) == published
    assert trusted_seal(dirs.run_dir, opening.written, session, replace(closed, closed=False), events) is None
    assert trusted_seal(dirs.run_dir, opening.written, None, closed, events) is None
    assert trusted_seal(dirs.run_dir, opening.written, session, closed, [*events, {"event": "seal-timeout"}]) is None


def test_recovery_reuses_a_recorded_egress_settlement(tmp_path, env, monkeypatch):
    from autonomy.science_run import _recovery

    dirs, _, configured, _ = _prepared(tmp_path, env, monkeypatch)
    append_event(dirs.run_dir, "egress-proxy", **ProcessIdentity.capture(os.getpid()).fields())
    append_event(dirs.run_dir, "egress-close-timeout")

    def must_not_settle(_path):
        pytest.fail("recovery attempted a second proxy settlement")

    monkeypatch.setattr(_recovery, "kill_orphan", must_not_settle)
    code, (receipt,) = control("close", dirs.run_id, configured)
    assert code == 4
    assert "egress-close-timeout" in {f["code"] for f in json.loads(receipt)["findings"]}


def test_run_stop_refuses_a_reused_supervisor_pid(tmp_path, env, monkeypatch):
    dirs, _, configured, _ = _prepared(tmp_path, env, monkeypatch)
    with pytest.raises(RunRefused, match="use run close"):
        control("stop", dirs.run_id, configured)
    assert not (dirs.run_dir / "disposition.json").exists()
