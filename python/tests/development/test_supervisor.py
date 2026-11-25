import os
import resource
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from autonomy.baseline import append_event
from autonomy.development._records import DevelopmentAborted, allocate_run, development_places, publish_grant, read_journal, read_json
from autonomy.development._workspace import Limits, PreparedWorkspace
from autonomy.run import RunRefused
from autonomy.sandbox.bwrap import launch
from autonomy.sandbox.spec import SandboxSpec
from autonomy.sandbox.static import SandboxUnproven

pytestmark = pytest.mark.bwrap


@pytest.fixture
def supervisor():
    from autonomy.development import _supervisor
    return _supervisor


@pytest.fixture
def paths(tmp_path):
    directories = development_places({
        "XDG_STATE_HOME": str(tmp_path / "state"), "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
    })
    with allocate_run(directories, repository=tmp_path, base="1" * 40, deadline_seconds=3) as run:
        yield run


@pytest.fixture
def stdio():
    fd = os.open(os.devnull, os.O_RDWR | os.O_CLOEXEC)
    try:
        yield (fd, fd, fd)
    finally:
        os.close(fd)


def grant(run):
    return publish_grant(run, base_sha256="1" * 64, walk_sha256="2" * 64, read_only=(), denied=(),
                         stdio=("null", "null", "null"), limits={})


@contextmanager
def invoke(sup, run, fds, script, *, limits=Limits(), deadline=3, launched=None):
    workspace = PreparedWorkspace(SandboxSpec(run.scratch, chdir=run.scratch), "1" * 64, (), "2" * 64)
    outcome = sup.supervise_actor(
        run, workspace, ("/usr/bin/python3", "-I", "-c", script), actor_fds=fds, limits=limits,
        deadline_seconds=deadline, grant_sha256=grant(run), actor_launched=launched,
    )
    try:
        yield outcome, Path(f"/proc/self/fd/{outcome.scratch_fd}")
    finally:
        os.close(outcome.scratch_fd)


def test_cap_applied_before_release_and_inherited(supervisor, paths, stdio, monkeypatch):
    observed = []
    prlimit = resource.prlimit

    def read_limit(pid, limit):
        observed.append(prlimit(pid, limit))
        return observed[-1]

    monkeypatch.setattr(supervisor.resource, "prlimit", read_limit)
    def after_release():
        assert '"event":"releasing"' in (paths.run_dir / "events.jsonl").read_text()

    with invoke(
        supervisor, paths, stdio,
        "import resource; from pathlib import Path; Path('ran').write_text(str(resource.getrlimit(resource.RLIMIT_FSIZE)))",
        limits=replace(Limits(), actor_fsize_bytes=8192), launched=after_release,
    ) as (outcome, scratch):
        assert observed == [(8192, 8192)]
        assert (scratch / "ran").read_text() == "(8192, 8192)"
        assert outcome.actor_exit == 0 and outcome.containment_proven and not outcome.findings


@pytest.mark.parametrize("handles_limit", [True, False])
def test_limit_refusal_is_handled_or_signalled_by_the_actor(supervisor, paths, stdio, handles_limit):
    script = f"""
import errno, os, signal
signal.signal(signal.SIGXFSZ, signal.SIG_IGN if {handles_limit!r} else signal.SIG_DFL)
with open('bounded', 'wb', buffering=0) as stream:
    assert stream.write(b'x' * 4096) == 4096
    try:
        stream.write(b'x')
    except OSError as error:
        assert error.errno == errno.EFBIG
    else:
        raise AssertionError('file limit did not apply')
"""
    with invoke(supervisor, paths, stdio, script, limits=replace(Limits(), actor_fsize_bytes=4096)) as (outcome, scratch):
        assert (scratch / "bounded").stat().st_size == 4096
        assert outcome.containment_proven
        assert [f.code for f in outcome.findings] == ([] if handles_limit else ["development-actor-failed"])


SMALL = replace(Limits(), actor_storage_bytes=1 << 20, actor_storage_inodes=64)
_EXHAUST = """
def fill(path):
    with open(path, 'wb', buffering=0) as stream:
        while True:
            stream.write(bytes(4096))
def spawn(directory):
    for n in range(1000):
        open(f'{directory}/n{n}', 'x').close()
"""


@pytest.mark.parametrize("attack", ["fill('x')", "fill('/tmp/x')", "fill('/dev/shm/x')", "spawn('.')", "spawn('/tmp')"])
def test_exhausting_the_storage_bound_is_a_stated_verdict(supervisor, paths, stdio, attack):
    with invoke(supervisor, paths, stdio, _EXHAUST + attack, limits=SMALL) as (outcome, scratch):
        usage = os.statvfs(scratch)
        assert (usage.f_blocks * usage.f_frsize, usage.f_files) == (1 << 20, 64)
    assert outcome.containment_proven and outcome.actor_exit == 1
    assert [f.code for f in outcome.findings] == ["development-actor-failed", "development-storage-exhausted"]
    ended = read_journal(paths)[-1]
    assert ended["event"] == "actor-ended"
    assert ended["storage_bytes"] == 1 << 20 if "fill" in attack else ended["storage_inodes"] == 64
    assert list(paths.scratch.iterdir()) == []


def test_an_actor_that_recovers_from_exhaustion_is_not_faulted(supervisor, paths, stdio):
    script = _EXHAUST + """
import os
try:
    fill('x')
except OSError:
    pass
"""
    with invoke(supervisor, paths, stdio, script, limits=SMALL) as (outcome, _):
        assert outcome.actor_exit == 0 and not outcome.findings


def test_seed_moves_into_the_bound_before_release(supervisor, paths, stdio):
    (paths.scratch / "repo").mkdir()
    (paths.scratch / "repo/file").write_text("seed")
    (paths.scratch / "repo/link").symlink_to("file")
    (paths.scratch / "repo/file").chmod(0o755)
    script = """
import os
assert open('repo/link').read() == 'seed' and os.stat('repo/file').st_mode & 0o777 == 0o755
os.unlink('repo/link')
open('repo/file', 'w').write('work')
"""
    with invoke(supervisor, paths, stdio, script) as (outcome, scratch):
        assert outcome.actor_exit == 0
        assert list(paths.scratch.iterdir()) == []
        assert [(p.name, p.read_text()) for p in (scratch / "repo").iterdir()] == [("file", "work")]


def test_seed_that_exceeds_the_bound_keeps_the_gate_closed(supervisor, paths, stdio):
    (paths.scratch / "repo").mkdir()
    (paths.scratch / "repo/big").write_bytes(bytes(2 << 20))
    with pytest.raises(DevelopmentAborted, match="development-workspace-unproven.*No space left"):
        with invoke(supervisor, paths, stdio, "raise SystemExit", limits=SMALL):
            pass
    assert [record["event"] for record in read_journal(paths)] == ["allocated"]
    assert (paths.scratch / "repo/big").exists()


def test_storage_proof_failure_keeps_actor_held(supervisor, paths, stdio, monkeypatch):
    def unproven(*args):
        raise SandboxUnproven("storage-unproven", "/run", "fixture")

    monkeypatch.setattr(supervisor, "hold_storage", unproven)
    with pytest.raises(DevelopmentAborted, match="development-sandbox-unproven.*storage-unproven"):
        with invoke(supervisor, paths, stdio, "raise SystemExit"):
            pass
    assert [record["event"] for record in read_journal(paths)] == ["allocated"]


def test_preflight_refuses_nested_development_launch(supervisor, paths, stdio):
    supervisor.prove_development_host()
    script = """
import errno, os
try:
    os.unshare(os.CLONE_NEWUSER)
except OSError as error:
    assert error.errno in (errno.EPERM, errno.ENOSPC)
else:
    raise AssertionError('nested namespace unexpectedly created')
"""
    with invoke(supervisor, paths, stdio, script) as (outcome, _):
        assert outcome.actor_exit == 0


def test_file_limit_proof_failure_keeps_actor_held(supervisor, paths, stdio, monkeypatch):
    monkeypatch.setattr(supervisor.resource, "prlimit", lambda pid, limit: (1, 1))
    with pytest.raises(DevelopmentAborted, match="development-sandbox-unproven"):
        with invoke(supervisor, paths, stdio, "raise SystemExit"):
            pass
    assert "launched" not in [record["event"] for record in read_journal(paths)]


def test_fsync_failure_keeps_the_gate_closed(supervisor, paths, stdio, monkeypatch):
    def fail_releasing(directory, event, **fields):
        assert event == "releasing"

        def fail_sync(fd):
            raise OSError("fixture fsync failure")

        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", fail_sync)
            append_event(directory, event, **fields)

    monkeypatch.setattr(supervisor, "append_event", fail_releasing)
    with pytest.raises(DevelopmentAborted, match="development-gate-unproven"):
        with invoke(supervisor, paths, stdio, "raise SystemExit"):
            pass
    assert "launched" not in [record["event"] for record in read_journal(paths)]


def test_stop_before_arming_prevents_actor_execution(supervisor, paths, stdio, monkeypatch):
    def stop_after_namespace_proof(*args, **kwargs):
        def request_while_held(child_pid, pidfd):
            assert supervisor.request_stop(paths) == 0

        return launch(*args, before_release=request_while_held, **kwargs)

    monkeypatch.setattr(supervisor, "launch", stop_after_namespace_proof)
    with pytest.raises(DevelopmentAborted, match="development-stop-before-release"):
        with invoke(supervisor, paths, stdio, "raise SystemExit"):
            pass
    assert "launched" not in [record["event"] for record in read_journal(paths)]
    assert '"event":"releasing"' not in (paths.run_dir / "events.jsonl").read_text()
    stop = (paths.run_dir / "stop.json").read_bytes()
    assert supervisor.request_stop(paths) == 0
    assert (paths.run_dir / "stop.json").read_bytes() == stop


def test_valid_output_at_deadline_is_ineligible(supervisor, paths, stdio):
    with invoke(supervisor, paths, stdio, "import time; from pathlib import Path; Path('present').touch(); time.sleep(8)",
                deadline=0.4) as (outcome, scratch):
        assert (scratch / "present").is_file()
    assert outcome.cause == "deadline" and outcome.containment_proven
    assert [f.code for f in outcome.findings] == ["development-deadline"]


def test_live_supervisor_refuses_recovery_during_preparation(supervisor, paths):
    with pytest.raises(RunRefused, match="development-supervisor-live"):
        supervisor.recover_run(paths)
    assert not (paths.run_dir / "disposition.json").exists()


@pytest.mark.parametrize("journal,code,status", [
    ("unarmed", "orchestrator-lost", 4),
    ("armed", "development-close-unproven", 3),
    ("torn", "development-close-unproven", 3),
])
def test_recovery_distinguishes_unarmed_armed_and_torn_journals(supervisor, tmp_path, journal, code, status, monkeypatch):
    where = development_places({"XDG_STATE_HOME": str(tmp_path / "state"), "XDG_CACHE_HOME": str(tmp_path / "cache")})
    with allocate_run(where, repository=tmp_path, base="1" * 40, deadline_seconds=3) as run:
        digest = grant(run)
        if journal == "armed":
            append_event(run.run_dir, "releasing", child_pid=12, start_time=1,
                         boot_id=supervisor.boot_id(), grant_sha256=digest)
        elif journal == "torn":
            with (run.run_dir / "events.jsonl").open("a") as stream:
                stream.write('{"event":')
    recovered = []
    monkeypatch.setattr(supervisor, "_recover_namespace", lambda identity: recovered.append(identity) or True)
    assert supervisor.recover_run(run) == status
    assert len(recovered) == (journal == "armed")
    assert read_json(run.run_dir / "disposition.json")["findings"][0]["code"] == code
    assert supervisor.request_stop(run) == supervisor.recover_run(run) == status


def test_recovery_never_signals_a_reused_or_unverified_pid(supervisor, monkeypatch):
    calls = []
    monkeypatch.setattr(supervisor.signal, "pidfd_send_signal", lambda *args: calls.append(args))
    identity = supervisor._Identity(os.getpid(), 0, supervisor.boot_id())
    monkeypatch.setattr(supervisor, "_start_time", lambda pid: 1)
    assert supervisor._recover_namespace(identity)
    assert not supervisor._recover_namespace(replace(identity, boot_id="00000000-0000-0000-0000-000000000000"))
    assert calls == []


OTHER_BOOT = "00000000-0000-0000-0000-000000000001"


@pytest.mark.parametrize(
    ("case", "expected_proven", "expected_code", "expected_exit"),
    [
        ("no_release", True, "orchestrator-lost", 4),
        ("confirmed_exit", True, "development-close-unproven", 3),
        ("pid_reused", True, "development-close-unproven", 3),
        ("unconfirmed_same_boot", False, "development-close-unproven", 3),
        ("torn_same_boot", False, "development-close-unproven", 3),
        ("torn_after_reboot", True, "development-close-unproven", 3),
        ("releasing_changed_boot", True, "development-close-unproven", 3),
    ],
)
def test_recovery_containment(supervisor, tmp_path, monkeypatch, case, expected_proven, expected_code, expected_exit):
    from autonomy.development import _records

    where = development_places({"XDG_STATE_HOME": str(tmp_path / "state"), "XDG_CACHE_HOME": str(tmp_path / "cache")})
    live_boot = _records.boot_id()
    assert live_boot != OTHER_BOOT
    with allocate_run(where, repository=tmp_path, base="1" * 40, deadline_seconds=3) as run:
        digest = grant(run)
        if case in ("confirmed_exit", "pid_reused", "unconfirmed_same_boot", "releasing_changed_boot"):
            pid = os.getpid() if case in ("pid_reused", "unconfirmed_same_boot") else 2_000_000_000
            append_event(
                run.run_dir, "releasing", child_pid=pid, start_time=0, boot_id=live_boot, grant_sha256=digest,
            )
        elif case in ("torn_same_boot", "torn_after_reboot"):
            with (run.run_dir / "events.jsonl").open("a") as stream:
                stream.write('{"event":"releasing"')

    if case == "pid_reused":
        monkeypatch.setattr(supervisor, "_start_time", lambda pid: 999_999_999)
    elif case == "unconfirmed_same_boot":
        monkeypatch.setattr(supervisor, "_start_time", lambda pid: 0)
        monkeypatch.setattr(supervisor, "_terminate", lambda fd: False)
    elif case in ("torn_after_reboot", "releasing_changed_boot"):
        monkeypatch.setattr(supervisor, "boot_id", lambda: OTHER_BOOT)
        events_order: list[str] = []
        real_boot = supervisor.boot_id
        real_journal = supervisor.read_journal
        monkeypatch.setattr(supervisor, "boot_id", lambda: events_order.append("boot") or real_boot())
        monkeypatch.setattr(supervisor, "read_journal", lambda target: events_order.append("journal") or real_journal(target))

    assert supervisor.recover_run(run) == expected_exit
    if case in ("torn_after_reboot", "releasing_changed_boot"):
        assert events_order[0] == "boot"
    verdict = read_json(run.run_dir / "disposition.json")
    assert verdict["containment_proven"] is expected_proven
    assert verdict["findings"][0]["code"] == expected_code
    terminal = _records.read_terminal(run)
    assert terminal is not None and terminal.containment_proven is expected_proven


def test_live_unconfirmed_shutdown_is_not_proven(supervisor, tmp_path, stdio, monkeypatch):
    from autonomy.development import _run
    from autonomy.run import DevelopmentProgress
    from development.test_workspace import make_source

    repo = tmp_path / "repo"
    base, _ = make_source(repo)
    env = {
        "HOME": str(tmp_path), "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"), "XDG_CONFIG_HOME": str(tmp_path / "config"),
    }
    monkeypatch.setattr(supervisor, "_await_actor", lambda actor, run, until: (0, "exit", False))
    progress = DevelopmentProgress()
    status = _run.execute(
        _run.DevelopmentRequest(repo, base, 5.0, ("/usr/bin/true",), None),
        env, diag=lambda _: None, progress=progress, actor_fds=stdio,
    )
    assert status == 3
    assert progress.run_dir is not None
    verdict = read_json(progress.run_dir / "disposition.json")
    assert verdict["disposition"] == "quarantined"
    assert verdict["containment_proven"] is False
    assert [f["code"] for f in verdict["findings"]] == ["development-close-unproven"]


def test_a_gate_that_breaks_after_releasing_is_unproven(supervisor, tmp_path, stdio, monkeypatch):
    from autonomy.development import _run
    from autonomy.run import DevelopmentProgress
    from autonomy.sandbox import bwrap
    from development.test_workspace import make_source

    repo = tmp_path / "repo"
    base, _ = make_source(repo)
    env = {
        "HOME": str(tmp_path), "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"), "XDG_CONFIG_HOME": str(tmp_path / "config"),
    }
    real_write = bwrap.os.write

    def broken_gate(fd, data):
        if data == bwrap.RELEASE:
            raise BrokenPipeError("gate pipe closed")
        return real_write(fd, data)

    monkeypatch.setattr(bwrap.os, "write", broken_gate)
    progress = DevelopmentProgress()
    status = _run.execute(
        _run.DevelopmentRequest(repo, base, 5.0, ("/usr/bin/true",), None),
        env, diag=lambda _: None, progress=progress, actor_fds=stdio,
    )
    assert status == 3
    assert progress.run_dir is not None
    events = [row["event"] for row in read_journal(_records_run(env, progress.run_dir.name))]
    assert "releasing" in events and "launched" not in events
    verdict = read_json(progress.run_dir / "disposition.json")
    assert verdict["disposition"] == "quarantined"
    assert verdict["containment_proven"] is False
    assert [f["code"] for f in verdict["findings"]] == ["development-close-unproven"]


def _records_run(env, run_id):
    from autonomy.development._records import lookup_run

    return lookup_run(development_places(env), run_id)


def test_actor_exit_waits_for_its_namespace_pidfd(tmp_path):
    from subprocess import DEVNULL, Popen
    import sys
    import time
    from types import SimpleNamespace

    from autonomy.development._supervisor import _await_actor

    with Popen([sys.executable, "-c", "import time; time.sleep(0.3)"],
               env={"PATH": "/usr/bin", "HOME": str(tmp_path)},
               stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL) as namespace:
        pidfd = os.pidfd_open(namespace.pid)
        try:
            # The bwrap wrapper can be reaped before the namespace init is readable.
            actor = SimpleNamespace(wait=lambda *, timeout: 0, pidfd=pidfd)
            assert _await_actor(actor, SimpleNamespace(run_dir=tmp_path), time.monotonic() + 2) == (0, "exit", True)
        finally:
            os.close(pidfd)
            namespace.wait(timeout=3)
