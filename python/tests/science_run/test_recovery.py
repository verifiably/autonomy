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


def test_close_uses_a_published_receipt_with_its_known_temporary_hardlink(env):
    from autonomy.run import write_disposition

    dirs = allocate(places(env))
    terminal = dirs.run_dir / "disposition.json"
    write_disposition(dirs.run_dir, dirs.run_id, "clean", ())
    os.link(terminal, dirs.run_dir / ".disposition.json.0123456789abcdef.tmp")
    assert control("close", dirs.run_id, env) == (0, [terminal.read_text()])
    assert control("close", dirs.run_id, env) == (0, [terminal.read_text()])
    (dirs.run_dir / ".disposition.json.0123456789abcdef.tmp").rename(dirs.run_dir / "unrelated-link")
    with pytest.raises(RunRefused, match="private regular file"):
        control("close", dirs.run_id, env)


@pytest.mark.parametrize("prior", [False, True])
def test_close_preserves_durable_exit_when_the_output_sink_is_closed(env, prior):
    from autonomy.run import write_disposition
    from autonomy.science_run import control as command

    dirs = allocate(places(env))
    if prior:
        write_disposition(dirs.run_dir, dirs.run_id, "clean", ())

    def closed(_):
        raise BrokenPipeError("receipt consumer closed")

    code = command("close", dirs.run_id, env, diag=lambda _: None, emit=closed)
    assert code == (0 if prior else 4)
    assert (dirs.run_dir / "disposition.json").is_file()


@pytest.mark.parametrize("prior", [False, True])
def test_close_cli_preserves_durable_exit_with_a_broken_stdout(env, prior):
    import subprocess
    import sys

    from autonomy.run import write_disposition

    dirs = allocate(places(env))
    if prior:
        write_disposition(dirs.run_dir, dirs.run_id, "clean", ())
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    try:
        closed = subprocess.run(
            [sys.executable, "-m", "autonomy", "run", "close", dirs.run_id],
            env=env, stdin=subprocess.DEVNULL, stdout=write_fd, stderr=subprocess.PIPE, timeout=5,
        )
    finally:
        os.close(write_fd)
    assert closed.returncode == (0 if prior else 4), closed.stderr.decode()
    assert (dirs.run_dir / "disposition.json").is_file()


def test_publication_staging_followed_by_supervisor_loss_is_recoverable(tmp_path, env, monkeypatch):
    from autonomy.baseline import publish_json

    current = ProcessIdentity.capture(os.getpid())
    dead = ProcessIdentity(current.pid, current.start_time + 1, current.boot_id)
    monkeypatch.setattr(ProcessIdentity, "capture", classmethod(lambda cls, pid: dead))
    configured, _ = _science_world(tmp_path / "world", env)
    where = places(configured)
    admission = _opening(configured)
    with admission.open(where, None) as dirs:
        admission.capture(_opened(admission, dirs, where))
        publish_json(dirs.run_dir / "launch.json", {"version": "launch.v1"})
        (dirs.run_dir / "endpoint.log").touch()
    status, (receipt,) = control("close", dirs.run_id, configured)
    assert status == 4
    assert "orchestrator-lost" in {f["code"] for f in json.loads(receipt)["findings"]}


def test_late_torn_journal_does_not_hide_the_endpoint_identity(tmp_path, env, monkeypatch):
    dirs, _, configured, calls = _prepared(tmp_path, env, monkeypatch)
    with (dirs.run_dir / "events.jsonl").open("ab") as output:
        output.write(b'{"event":"actor-ex')
    code, (receipt,) = control("close", dirs.run_id, configured)
    assert code == 4
    assert "detached" in calls.read_text()
    assert {f["code"] for f in json.loads(receipt)["findings"]} >= {"orchestrator-lost", "read-unavailable"}
    assert (dirs.run_dir / "events.jsonl").read_bytes().endswith(b'{"event":"actor-ex')


def test_torn_first_event_leaves_supervisor_unconfirmed(env):
    from autonomy.baseline import publish_json

    dirs = allocate(places(env))
    publish_json(dirs.run_dir / "run.json", {"version": 1, "mode": "science", "run": dirs.run_id})
    journal = dirs.run_dir / "events.jsonl"
    journal.write_bytes(b'{"event":"alloc')
    journal.chmod(0o600)
    with pytest.raises(RunRefused):
        control("close", dirs.run_id, env)
    assert not (dirs.run_dir / "disposition.json").exists()


def test_admission_and_close_reject_the_same_inconsistent_receipt(tmp_path, env, monkeypatch):
    from autonomy.run import write_disposition

    dirs, _, configured, calls = _prepared(tmp_path, env, monkeypatch)
    write_disposition(dirs.run_dir, dirs.run_id, "clean", ())
    terminal = dirs.run_dir / "disposition.json"
    raw = json.loads(terminal.read_bytes())
    raw["findings"] = [{"code": "entry-foreign", "ref": "entry", "message": "foreign"}]
    terminal.write_text(json.dumps(raw))
    with pytest.raises(RunRefused, match=dirs.run_id):
        with _opening(configured).open(places(configured), None):
            pytest.fail("an inconsistent receipt retired a chain")
    with pytest.raises(RunRefused):
        control("close", dirs.run_id, configured)
    assert calls.read_text() == "resolve\n"


def test_proxy_recovery_never_opens_a_pidfd_for_an_old_boot(tmp_path, env, monkeypatch):
    import uuid

    owner = ProcessIdentity.capture(os.getpid())
    previous = ProcessIdentity(owner.pid, owner.start_time, str(uuid.uuid4()))
    monkeypatch.setattr(ProcessIdentity, "capture", classmethod(lambda cls, pid: previous))
    configured, _ = _science_world(tmp_path / "world", env)
    where = places(configured)
    admission = _opening(configured)
    with admission.open(where, None) as dirs:
        admission.capture(_opened(admission, dirs, where))
    append_event(dirs.run_dir, "endpoint-starting", **previous.fields())
    append_event(dirs.run_dir, "egress-proxy", pid=owner.pid, start_time=owner.start_time)
    monkeypatch.setattr(ProcessIdentity, "capture", classmethod(lambda cls, pid: owner))

    def opened_wrong_pid(_pid):
        pytest.fail("recovery opened a proxy pidfd from a previous boot")

    monkeypatch.setattr(os, "pidfd_open", opened_wrong_pid)
    code, (receipt,) = control("close", dirs.run_id, configured)
    assert code == 4
    assert "egress-lost" in {f["code"] for f in json.loads(receipt)["findings"]}


def test_development_initialization_and_science_mode_lookup_share_publication_lock(tmp_path, env, monkeypatch):
    import queue
    import threading

    from autonomy.development._records import allocate_run, development_places

    visible = queue.Queue()
    release = threading.Event()
    initialized = threading.Event()
    finalize = threading.Event()
    mkdir = Path.mkdir
    where = development_places(env)

    def held(path, *args, **kwargs):
        mkdir(path, *args, **kwargs)
        if path.parent == where.state / "runs":
            visible.put(path)
            assert release.wait(3)

    monkeypatch.setattr(Path, "mkdir", held)

    def open_development():
        with allocate_run(where, repository=tmp_path, base="1" * 40, deadline_seconds=10):
            initialized.set()
            assert finalize.wait(3)

    with ThreadPoolExecutor(2) as workers:
        allocation = workers.submit(open_development)
        run_dir = visible.get(timeout=3)
        try:
            closer = workers.submit(control, "close", run_dir.name, env)
            from concurrent.futures import TimeoutError as FutureTimeout

            with pytest.raises(FutureTimeout):
                closer.result(timeout=0.2)
            release.set()
            assert initialized.wait(3)
            with pytest.raises(RunRefused, match="development-supervisor-live"):
                closer.result(timeout=3)
        finally:
            release.set()
            finalize.set()
        allocation.result(timeout=3)
    assert not (run_dir / "disposition.json").exists()
