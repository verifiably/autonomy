import os
import resource
from dataclasses import replace
from pathlib import Path

import pytest

from autonomy.baseline import append_event
from autonomy.development._records import DevelopmentAborted, allocate_run, development_places, publish_grant, read_json
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


def invoke(sup, run, fds, script, *, limits=Limits(), deadline=3, launched=None):
    workspace = PreparedWorkspace(SandboxSpec(run.scratch, chdir=run.scratch), "1" * 64, (), "2" * 64)
    return sup.supervise_actor(
        run, workspace, ("/usr/bin/python3", "-I", "-c", script), actor_fds=fds, limits=limits,
        deadline_seconds=deadline, grant_sha256=grant(run), actor_launched=launched,
    )


def test_cap_applied_before_release_and_inherited(supervisor, paths, stdio, monkeypatch):
    observed = []
    prlimit = resource.prlimit

    def read_limit(pid, limit):
        assert not (paths.scratch / "ran").exists()
        observed.append(prlimit(pid, limit))
        return observed[-1]

    monkeypatch.setattr(supervisor.resource, "prlimit", read_limit)
    def after_release():
        assert '"event":"releasing"' in (paths.run_dir / "events.jsonl").read_text()

    outcome = invoke(
        supervisor, paths, stdio,
        "import resource; from pathlib import Path; Path('ran').write_text(str(resource.getrlimit(resource.RLIMIT_FSIZE)))",
        limits=replace(Limits(), actor_fsize_bytes=8192), launched=after_release,
    )
    assert observed == [(8192, 8192)]
    assert (paths.scratch / "ran").read_text() == "(8192, 8192)"
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
    outcome = invoke(supervisor, paths, stdio, script, limits=replace(Limits(), actor_fsize_bytes=4096))
    assert (paths.scratch / "bounded").stat().st_size == 4096
    assert outcome.containment_proven
    assert [f.code for f in outcome.findings] == ([] if handles_limit else ["development-actor-failed"])


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
    assert invoke(supervisor, paths, stdio, script).actor_exit == 0


def test_file_limit_proof_failure_keeps_actor_held(supervisor, paths, stdio, monkeypatch):
    monkeypatch.setattr(supervisor.resource, "prlimit", lambda pid, limit: (1, 1))
    with pytest.raises(DevelopmentAborted, match="development-sandbox-unproven"):
        invoke(supervisor, paths, stdio, "from pathlib import Path; Path('ran').touch()")
    assert not (paths.scratch / "ran").exists()


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
        invoke(supervisor, paths, stdio, "from pathlib import Path; Path('ran').touch()")
    assert not (paths.scratch / "ran").exists()


def test_stop_before_arming_prevents_actor_execution(supervisor, paths, stdio, monkeypatch):
    def stop_after_namespace_proof(*args, **kwargs):
        def request_while_held(child_pid, pidfd):
            assert supervisor.request_stop(paths) == 0

        return launch(*args, before_release=request_while_held, **kwargs)

    monkeypatch.setattr(supervisor, "launch", stop_after_namespace_proof)
    with pytest.raises(DevelopmentAborted, match="development-stop-before-release"):
        invoke(supervisor, paths, stdio, "from pathlib import Path; Path('ran').touch()")
    assert not (paths.scratch / "ran").exists()
    assert '"event":"releasing"' not in (paths.run_dir / "events.jsonl").read_text()
    stop = (paths.run_dir / "stop.json").read_bytes()
    assert supervisor.request_stop(paths) == 0
    assert (paths.run_dir / "stop.json").read_bytes() == stop


def test_valid_output_at_deadline_is_ineligible(supervisor, paths, stdio):
    outcome = invoke(supervisor, paths, stdio, "import time; from pathlib import Path; Path('present').touch(); time.sleep(8)",
                     deadline=0.4)
    assert (paths.scratch / "present").is_file()
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
                         boot_id=supervisor._boot_id(), grant_sha256=digest)
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
    identity = supervisor._Identity(os.getpid(), 0, supervisor._boot_id())
    monkeypatch.setattr(supervisor, "_start_time", lambda pid: 1)
    assert supervisor._recover_namespace(identity)
    assert not supervisor._recover_namespace(replace(identity, boot_id="00000000-0000-0000-0000-000000000000"))
    assert calls == []


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
