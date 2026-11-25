import json
import os
import select
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

import autonomy

from autonomy.development._records import file_digest, read_json
from development.test_workspace import fixture_git, make_source, snapshot

pytestmark = pytest.mark.bwrap
REF = "refs/heads/development"
ACTOR = """
set -eu
export GIT_AUTHOR_NAME=Fixture GIT_AUTHOR_EMAIL=fixture@example.invalid
export GIT_COMMITTER_NAME=Fixture GIT_COMMITTER_EMAIL=fixture@example.invalid
printf 'first\n' > sample
git commit -am first >&2
printf 'second\n' > sample
git commit -am second >&2
git bundle create "$VERIFIABLY_DEVELOPMENT_BUNDLE" "$VERIFIABLY_DEVELOPMENT_BASE..$VERIFIABLY_DEVELOPMENT_REF"
git rev-parse HEAD
"""


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source"
    base, other = make_source(path)
    return path, base, other


@pytest.fixture
def env(tmp_path):
    return {
        "PATH": "/usr/bin", "HOME": str(tmp_path), "LC_ALL": "C",
        "XDG_CACHE_HOME": str(tmp_path / "cache"), "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
    }


def options(repo, base, deadline="10"):
    return ["run", "--development", "--repository", str(repo), "--base", base, "--deadline", deadline]


def run_store(env):
    return Path(env["XDG_STATE_HOME"]) / "verifiably-autonomy/runs"


@contextmanager
def attempt(env, args, actor=("/usr/bin/sh", "-c", ACTOR), *, program=None, stdout=subprocess.PIPE):
    read, send = os.pipe()
    command = [sys.executable, "-m", "autonomy"] if program is None else [sys.executable, "-c", program]
    with os.fdopen(read, "rb", buffering=0) as reports:
        try:
            process = subprocess.Popen(
                [*command, *args, "--report-fd", str(send), "--", *actor],
                env=env, pass_fds=(send,), stdin=subprocess.DEVNULL, stdout=stdout, stderr=subprocess.PIPE,
            )
        finally:
            os.close(send)
        try:
            yield process, reports
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=15)


def finish(process, reports):
    output, errors = process.communicate(timeout=45)
    lines = [json.loads(line) for line in reports]
    return output, errors, lines


def line(stream, timeout=30):
    # The sender publishes a complete line in a single write.
    assert select.select([stream], [], [], timeout)[0], "no status received"
    return stream.readline()


def control(env, action, run):
    return subprocess.run(
        [sys.executable, "-m", "autonomy", "run", action, run],
        env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=20,
    )


def assert_finding(record, code):
    assert code in {finding["code"] for finding in record["findings"]}


def test_supervised_offline_run_reconstructs_candidate_after_source_moves(tmp_path, env, source):
    repo, base, unrelated = source
    before = snapshot(repo)
    with attempt(env, options(repo, base)) as (process, reports):
        output, errors, (opened, closed) = finish(process, reports)
        assert process.returncode == 0, errors
    assert snapshot(repo) == before
    assert fixture_git(repo, "rev-parse", "refs/heads/unrelated") == unrelated
    assert opened == {
        "run": opened["run"], "mode": "development", "run_dir": str(run_store(env) / opened["run"]),
        "scratch": str(Path(env["XDG_CACHE_HOME"]) / "verifiably-autonomy/scratch" / opened["run"]),
        "base": base, "ref": REF, "bundle_path": "/run/va/outputs/candidate.bundle",
    }
    assert closed == {"run": opened["run"], "mode": "development", "disposition": "clean", "exit": 0}
    directory = Path(opened["run_dir"])
    assert {entry.name for entry in directory.iterdir()} == {
        "supervisor.lock", "publication.lock", "run.json", "events.jsonl", "walk.json",
        "base.bundle", "grant.json", "candidate.bundle", "candidate.json", "disposition.json",
    }
    header, grant, candidate, verdict = (
        read_json(directory / name) for name in ("run.json", "grant.json", "candidate.json", "disposition.json")
    )
    assert set(header) == {"version", "run", "mode", "created_at", "repository", "base", "ref", "deadline_seconds", "scratch"}
    assert set(grant) == {"version", "run", "mode", "issued_at", "run_sha256", "approval", "operation",
                          "base_sha256", "route", "allowance", "scope", "stdio", "limits"}
    assert set(candidate) == {"version", "run", "mode", "base", "ref", "tip", "base_sha256", "bundle_sha256",
                              "grant_sha256", "actor_exit", "closed_at"}
    assert set(verdict) == {"version", "run", "mode", "disposition", "findings", "closed_at", "grant_sha256", "candidate_sha256"}
    assert grant["approval"] == "supervised-invocation" and grant["route"] is None and grant["allowance"] is None
    assert (grant["limits"]["actor_storage_bytes"], grant["limits"]["actor_storage_inodes"]) == (1 << 30, 1 << 17)
    assert list(Path(opened["scratch"]).iterdir()) == []
    assert grant["run_sha256"] == file_digest(directory / "run.json")
    assert grant["scope"]["walk_sha256"] == file_digest(directory / "walk.json")
    assert candidate["base_sha256"] == grant["base_sha256"] == file_digest(directory / "base.bundle")
    assert candidate["bundle_sha256"] == file_digest(directory / "candidate.bundle")
    assert candidate["grant_sha256"] == verdict["grant_sha256"] == file_digest(directory / "grant.json")
    assert verdict["candidate_sha256"] == file_digest(directory / "candidate.json")
    assert control(env, "close", opened["run"]).returncode == 0
    assert control(env, "stop", opened["run"]).returncode == 0
    assert not (directory / "stop.json").exists()

    fixture_git(repo, "update-ref", "refs/heads/main", unrelated)
    assert fixture_git(repo, "rev-parse", "refs/heads/main") != base
    receiver = tmp_path / "receiver"
    receiver.mkdir()
    fixture_git(receiver, "init", "--template=", "--bare")
    assert Path(fixture_git(receiver, "rev-parse", "--absolute-git-dir")) == receiver
    for filename, ref in (("base.bundle", "refs/heads/base"), ("candidate.bundle", REF)):
        fixture_git(receiver, "-c", "fetch.fsckObjects=true", "fetch", str(directory / filename), f"{ref}:{ref}")
    fixture_git(receiver, "fsck", "--strict", "--full")
    tip = fixture_git(receiver, "rev-parse", REF)
    assert tip == output.decode().strip() == candidate["tip"]
    assert fixture_git(receiver, "rev-list", "--count", f"{base}..{tip}") == "2"


def test_clean_candidate_may_be_declined_by_consumer(env, source):
    repo, base, _ = source
    before = snapshot(repo)
    with attempt(env, options(repo, base)) as (process, reports):
        _, errors, (opened, closed) = finish(process, reports)
        assert process.returncode == closed["exit"] == 0, errors
    # Declining means leaving the clean evidence in custody without an acceptance write.
    assert (Path(opened["run_dir"]) / "candidate.bundle").exists()
    assert snapshot(repo) == before


@pytest.mark.parametrize(("flags", "code"), [
    (["--lease", "60"], "development-mode-conflict"),
    (["--lease"], "development-mode-conflict"),
    (["--tier", "report-only"], "development-mode-conflict"),
    (["--route", "a=b"], "development-mode-conflict"),
    (["--model-route", "fixture"], "development-model-route-refused"),
    (["--model-route"], "development-model-route-refused"),
    (["--repository="], "development-repository-invalid"),
    (["--repository"], "development-repository-invalid"),
    (["--base="], "development-base-invalid"),
    (["--base"], "development-base-invalid"),
    (["--deadline="], "deadline-invalid"),
    (["--deadline"], "deadline-invalid"),
    (["--deadline", "0"], "deadline-invalid"),
    (["--deadline", "-1"], "deadline-invalid"),
    (["--deadline", "nan"], "deadline-invalid"),
    (["--deadline", "inf"], "deadline-invalid"),
    (["--deadline", "-inf"], "deadline-invalid"),
    (["--deadline", "a"], "deadline-invalid"),
])
def test_development_start_refusals_precede_allocation(env, source, flags, code):
    repo, base, _ = source
    with attempt(env, [*options(repo, base), *flags], actor=("/usr/bin/true",)) as (process, reports):
        output, errors, lines = finish(process, reports)
        assert process.returncode == 2
    assert code.encode() in errors
    assert not output and not lines and not run_store(env).exists()


@pytest.mark.parametrize(("omit", "code"), [
    ("--repository", "development-repository-invalid"), ("--base", "development-base-invalid"),
    ("--deadline", "deadline-invalid"),
])
def test_omitted_development_inputs_have_normative_codes(env, source, omit, code):
    repo, base, _ = source
    args = options(repo, base)
    index = args.index(omit)
    del args[index:index + 2]
    with attempt(env, args) as (process, reports):
        _, errors, lines = finish(process, reports)
        assert process.returncode == 2
    assert code.encode() in errors and not lines and not run_store(env).exists()


def test_development_stdio_refusal_has_no_retained_run(tmp_path, env, source):
    repo, base, _ = source
    with (tmp_path / "regular-stdout").open("wb") as destination:
        with attempt(env, options(repo, base), stdout=destination) as (process, reports):
            _, errors, lines = finish(process, reports)
            assert process.returncode == 2
    assert b"stdio-refused" in errors and not lines and not run_store(env).exists()


def test_development_refuses_unavailable_host_and_allocation_failure(tmp_path, env, source):
    repo, base, _ = source
    unavailable = """
from autonomy.cli import main
from autonomy.development import _run
from autonomy.sandbox.static import SandboxUnproven
def refuse():
    raise SandboxUnproven('userns-unavailable', 'fixture', 'namespace unavailable')
_run.prove_development_host = refuse
raise SystemExit(main())
"""
    with attempt(env, options(repo, base), program=unavailable) as (process, reports):
        _, errors, lines = finish(process, reports)
        assert process.returncode == 2
    assert b"development-launch-unavailable" in errors and not lines and not run_store(env).exists()
    Path(env["XDG_STATE_HOME"]).write_text("blocks allocation")
    with attempt(env, options(repo, base)) as (process, reports):
        _, errors, lines = finish(process, reports)
        assert process.returncode == 2
    assert b"allocation-failed" in errors and not lines and not run_store(env).exists()


def test_nested_development_cli_is_refused_by_preflight(env, source):
    repo, base, _ = source
    fixture_git(repo, "switch", "-c", "nested-fixture", base)
    shutil.copytree(Path(autonomy.__file__).parent, repo / "tool/autonomy",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    fixture_git(repo, "add", "tool")
    fixture_git(repo, "commit", "-m", "add offline fixture CLI")
    base = fixture_git(repo, "rev-parse", "HEAD")
    actor = """
import os, subprocess
from pathlib import Path
env = {"PATH": "/usr/bin", "HOME": os.environ["HOME"], "PYTHONPATH": str(Path.cwd() / "tool")}
cmd = ["/usr/bin/python3", "-m", "autonomy", "run", "--development", "--repository", str(Path.cwd()),
       "--base", os.environ["VERIFIABLY_DEVELOPMENT_BASE"], "--deadline", "5", "--", "/usr/bin/true"]
result = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=10)
assert result.returncode == 2 and b"development-launch-unavailable" in result.stderr, result
assert not (Path(env["HOME"]) / ".local/state/verifiably-autonomy/runs").exists()
print("nested run refused")
"""
    with attempt(env, options(repo, base), ("/usr/bin/python3", "-I", "-c", actor)) as (process, reports):
        output, errors, (opened, _) = finish(process, reports)
        assert process.returncode == 3, errors
    assert output == b"nested run refused\n"
    assert_finding(read_json(Path(opened["run_dir"]) / "disposition.json"), "development-bundle-missing")


def test_stop_and_close_refuse_unknown_run(env):
    for action in ("stop", "close"):
        result = control(env, action, "1" * 32)
        assert result.returncode == 2 and b"development-run-invalid" in result.stderr
    assert not run_store(env).exists()


def test_stopped_run_with_complete_bundle_never_promotes(env, source):
    repo, base, _ = source
    with attempt(env, options(repo, base), ("/usr/bin/sh", "-c", ACTOR + "\nexec /usr/bin/sleep 18")) as (process, reports):
        opened = json.loads(line(reports))
        assert len(line(process.stdout).strip()) == len(base)
        assert control(env, "close", opened["run"]).returncode == 2
        assert control(env, "stop", opened["run"]).returncode == 0
        _, errors, (closed,) = finish(process, reports)
        assert process.returncode == closed["exit"] == 3, errors
    directory = Path(opened["run_dir"])
    assert_finding(read_json(directory / "disposition.json"), "development-stopped")
    assert not (directory / "candidate.bundle").exists()
    assert (Path(opened["scratch"]) / "outputs/candidate.bundle").is_file()


def test_expired_run_with_complete_bundle_never_promotes(env, source):
    repo, base, _ = source
    with attempt(env, options(repo, base, "1.5"), ("/usr/bin/sh", "-c", ACTOR + "\nexec /usr/bin/sleep 18")) as (process, reports):
        _, errors, (opened, closed) = finish(process, reports)
        assert process.returncode == closed["exit"] == 3, errors
    directory = Path(opened["run_dir"])
    assert_finding(read_json(directory / "disposition.json"), "development-deadline")
    assert not (directory / "candidate.bundle").exists()
    assert (Path(opened["scratch"]) / "outputs/candidate.bundle").is_file()


def test_exhausted_run_is_quarantined_with_its_work_retained(env, source):
    repo, base, _ = source
    actor = ACTOR + """
i=0
while head -c 60M /dev/zero > "$HOME/fill$i"; do i=$((i+1)); done
exit 7
"""
    with attempt(env, options(repo, base, "60"), ("/usr/bin/sh", "-c", actor)) as (process, reports):
        _, errors, (opened, closed) = finish(process, reports)
        assert process.returncode == closed["exit"] == 3, errors
    directory, scratch = Path(opened["run_dir"]), Path(opened["scratch"])
    verdict = read_json(directory / "disposition.json")
    assert [finding["code"] for finding in verdict["findings"]] == ["development-actor-failed", "development-storage-exhausted"]
    grant = read_json(directory / "grant.json")
    journal = [json.loads(record) for record in (directory / "events.jsonl").read_text().splitlines()]
    retained = journal[-1]
    assert retained["event"] == "scratch-retained" and journal[-2]["storage_bytes"] == grant["limits"]["actor_storage_bytes"]
    assert (scratch / "outputs/candidate.bundle").is_file() and (scratch / "repo/sample").read_text() == "second\n"
    copied = [path.stat().st_size for path in scratch.rglob("*") if path.is_file()]
    assert (len(copied), sum(copied)) == (retained["files"], retained["bytes"])
    assert sum(copied) <= grant["limits"]["actor_storage_bytes"]


def test_lost_supervisor_leaves_no_actor_scratch(env, source):
    repo, base, _ = source
    with attempt(env, options(repo, base), ("/usr/bin/sh", "-c", ACTOR + "\nexec /usr/bin/sleep 18")) as (process, reports):
        opened = json.loads(line(reports))
        assert len(line(process.stdout).strip()) == len(base)
        process.kill()
        process.wait(timeout=10)
        assert control(env, "close", opened["run"]).returncode == 3
    directory = Path(opened["run_dir"])
    assert_finding(read_json(directory / "disposition.json"), "development-close-unproven")
    assert list(Path(opened["scratch"]).iterdir()) == []
    assert (directory / "base.bundle").is_file() and (directory / "grant.json").is_file()


def test_retention_failure_keeps_the_published_verdict(env, source):
    repo, base, _ = source
    program = """
from autonomy.cli import main
from autonomy.development import _run
def refuse(*args, **kwargs):
    raise OSError('fixture retention failure')
_run.retain = refuse
raise SystemExit(main())
"""
    with attempt(env, options(repo, base), actor=("/usr/bin/false",), program=program) as (process, reports):
        _, errors, (opened, closed) = finish(process, reports)
        assert process.returncode == closed["exit"] == 3, errors
    journal = [json.loads(record) for record in (Path(opened["run_dir"]) / "events.jsonl").read_text().splitlines()]
    assert journal[-1]["event"] == "scratch-unretained" and journal[-1]["detail"] == "fixture retention failure"


def blocker(tmp_path, name):
    started = tmp_path / "validator-started"
    release = tmp_path / "resume-validator"
    program = f"""
from pathlib import Path
from time import monotonic, sleep
from autonomy.cli import main
from autonomy.development import _run
real = _run.{name}
def wait(*args, **kwargs):
    Path({str(started)!r}).touch()
    limit = monotonic() + 30
    while not Path({str(release)!r}).exists():
        if monotonic() >= limit:
            raise RuntimeError("fixture did not release validator")
        sleep(0.015)
    return real(*args, **kwargs)
_run.{name} = wait
raise SystemExit(main())
"""
    return program, started, release


def wait_for(path, process):
    until = time.monotonic() + 30
    while not path.exists() and process.poll() is None and time.monotonic() < until:
        time.sleep(0.02)
    assert path.exists(), process.communicate(timeout=10) if process.poll() is not None else "supervisor did not reach fixture barrier"


def test_stop_during_validation_wins_before_terminal_commit(tmp_path, env, source):
    repo, base, _ = source
    program, started, resume = blocker(tmp_path, "validate_candidate")
    with attempt(env, options(repo, base), program=program) as (process, reports):
        opened = json.loads(line(reports))
        wait_for(started, process)
        directory = Path(opened["run_dir"])
        assert not (directory / "disposition.json").exists()
        assert control(env, "stop", opened["run"]).returncode == 0
        resume.touch()
        _, errors, (closed,) = finish(process, reports)
        assert closed["exit"] == process.returncode == 3, errors
    record = read_json(directory / "disposition.json")
    assert_finding(record, "development-stopped")
    assert record["candidate_sha256"] is None
    assert not (directory / "candidate.json").exists()


def test_actor_channels_reach_eof_before_candidate_validation_finishes(tmp_path, env, source):
    repo, base, _ = source
    program, started, resume = blocker(tmp_path, "validate_candidate")
    with attempt(env, options(repo, base), program=program) as (process, reports):
        json.loads(line(reports))
        wait_for(started, process)
        for stream in (process.stdout, process.stderr):
            assert select.select([stream], [], [], 3)[0]
            # With at most a few lines produced, a nonblocking read to EOF
            # drains all actor bytes while the validator is still held.
            os.set_blocking(stream.fileno(), False)
            while os.read(stream.fileno(), 4096):
                pass
        assert process.poll() is None
        resume.touch()
        _, errors, (closed,) = finish(process, reports)
        assert process.returncode == closed["exit"] == 0, errors


def fault(name):
    return f"""
from autonomy.cli import main
from autonomy.development import _run
def interrupt(*args, **kwargs):
    raise KeyboardInterrupt('fixture interruption')
_run.{name} = interrupt
raise SystemExit(main())
"""


def test_terminal_write_interruption_keeps_candidate_ineligible(env, source):
    repo, base, _ = source
    with attempt(env, options(repo, base), program=fault("publish_terminal")) as (process, reports):
        _, _, (opened,) = finish(process, reports)
        assert process.returncode == 4
    directory = Path(opened["run_dir"])
    assert (directory / "candidate.json").is_file()
    assert not (directory / "disposition.json").exists()
    assert control(env, "close", opened["run"]).returncode == 3
    result = read_json(directory / "disposition.json")
    assert_finding(result, "development-close-unproven")
    assert result["candidate_sha256"] is None


@pytest.mark.parametrize(("where", "status"), [("admit_source", 2), ("prepare_workspace", 4), ("validate_candidate", 4)])
def test_unexpected_development_exit_uses_allocation_and_durable_status(env, source, where, status):
    repo, base, _ = source
    with attempt(env, options(repo, base), program=fault(where)) as (process, reports):
        _, _, lines = finish(process, reports)
        assert process.returncode == status
    if status == 2:
        assert not lines and not run_store(env).exists()
    else:
        (opened,) = lines
        assert not (Path(opened["run_dir"]) / "disposition.json").exists()
        recovered = 4 if where == "prepare_workspace" else 3
        assert control(env, "close", opened["run"]).returncode == recovered


@pytest.mark.parametrize("disposition,expected", [("clean", 0), ("quarantined", 3), ("unwired", 4)])
@pytest.mark.parametrize("failure", ["report", "append"])
def test_reporting_failure_preserves_durable_development_verdict(tmp_path, env, source, disposition, expected, failure):
    repo, base, _ = source
    copy = tmp_path / "first-verdict"
    program = f"""
from pathlib import Path
from autonomy.cli import main
from autonomy.development import _run
from autonomy.development._records import DevelopmentAborted
from autonomy.membership import Finding
real_write = _run.LineChannel.write_line
real_append = _run.append_event
run_dir = None
def write(self, text):
    global run_dir
    import json
    if text.startswith('{{'):
        record = json.loads(text)
        if 'run_dir' in record:
            run_dir = Path(record['run_dir'])
        if 'disposition' in record:
            Path({str(copy)!r}).write_bytes((run_dir / 'disposition.json').read_bytes())
            if {failure!r} == 'report':
                raise OSError('fixture report failure')
            return False
    return real_write(self, text)
def append(path, event, **fields):
    if event == 'report-unwritten' and fields.get('line') == 'closing':
        raise OSError('fixture event append failure')
    return real_append(path, event, **fields)
def no_workspace(*args, **kwargs):
    raise DevelopmentAborted(Finding('development-workspace-unproven', 'fixture', 'injected'))
_run.LineChannel.write_line = write
_run.append_event = append
if {disposition!r} == 'unwired':
    _run.prepare_workspace = no_workspace
raise SystemExit(main())
"""
    actor = ("/usr/bin/false",) if disposition == "quarantined" else ("/usr/bin/sh", "-c", ACTOR)
    with attempt(env, options(repo, base), actor=actor, program=program) as (process, reports):
        _, errors, (opened,) = finish(process, reports)
        assert process.returncode == expected, errors
    stored = Path(opened["run_dir"]) / "disposition.json"
    assert stored.read_bytes() == copy.read_bytes()
    assert read_json(stored)["disposition"] == disposition


def test_existing_science_syntax_and_records_are_preserved(tmp_path, env):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    env["XDG_RUNTIME_DIR"] = str(runtime)
    with attempt(env, ["run", "--tier", "report-only", "--lease", "60"], ("/usr/bin/true", "--development")) as (process, reports):
        _, errors, (opened, closed) = finish(process, reports)
        assert process.returncode == 4, errors
    assert set(opened) == {"run", "run_dir", "scratch"}
    assert closed == {"run": opened["run"], "disposition": "unwired", "exit": 4}
    record = read_json(Path(opened["run_dir"]) / "disposition.json")
    assert record["members"] == {} and record["closing_heads"] is None and "mode" not in record
