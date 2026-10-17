import json
import os
import pwd
import stat
from pathlib import Path

import pytest

import autonomy.channel as channel
from autonomy.baseline import append_event
from autonomy.membership import Finding
from autonomy.run import (
    Progress, RunRefused, RunRequest, allocate, endpoint_side_unbuilt, execute, places, write_disposition,
)
from autonomy.tiers import REPORT_ONLY
from channels import drain, fill, one_page_pipe, read_all
from egress_fixtures import pi_route, write_credential, write_route


@pytest.fixture(autouse=True)
def short_poll(monkeypatch):
    monkeypatch.setattr(channel, "POLL_WAIT", 0.2)


@pytest.fixture
def env(tmp_path):
    for name in ("state", "cache", "runtime", "home", "config"):
        (tmp_path / name).mkdir()
    return {
        "HOME": str(tmp_path / "home"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_RUNTIME_DIR": str(tmp_path / "runtime"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
    }


@pytest.fixture
def actor():
    fds = tuple(os.open(os.devnull, os.O_RDWR) for _ in range(3))
    yield fds
    for fd in fds:
        os.close(fd)


def request(report_fd=None, lease=60.0) -> RunRequest:
    return RunRequest(REPORT_ONLY, lease, report_fd, ("/usr/bin/true",))


def runs(tmp_path) -> list[Path]:
    root = tmp_path / "state" / "verifiably-autonomy" / "runs"
    return sorted(root.iterdir()) if root.exists() else []


def events(run_dir: Path) -> list[dict]:
    path = run_dir / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_a_run_closes_with_its_disposition_and_both_report_lines(tmp_path, env, actor):
    read_end, write_end = os.pipe()
    said: list[str] = []
    try:
        code = execute(request(write_end), env, endpoint_side_unbuilt, diag=said.append, actor_fds=actor, progress=Progress())
        lines = read_all(read_end).decode().splitlines()  # EOF: execute closed the report fd
    finally:
        os.close(read_end)
    assert code == 4
    first, closing = (json.loads(line) for line in lines)
    run_dir = Path(first["run_dir"])
    assert run_dir == tmp_path / "state" / "verifiably-autonomy" / "runs" / first["run"]
    assert Path(first["scratch"]) == (tmp_path / "cache" / "verifiably-autonomy" / "scratch" / first["run"]).resolve()
    assert closing == {"run": first["run"], "disposition": "unwired", "exit": 4}
    record = json.loads((run_dir / "disposition.json").read_text())
    assert record["version"] == 1 and record["run"] == first["run"] and record["disposition"] == "unwired"
    assert [finding["code"] for finding in record["findings"]] == ["baseline-unavailable"]
    assert record["members"] == {} and record["closing_heads"] is None
    assert events(run_dir) == []
    assert any(first["run"] in line for line in said)


def test_the_closing_line_follows_a_durable_disposition(tmp_path, env, actor, monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr(
        channel, "_before_write",
        lambda fd: seen.append([p.name for p in tmp_path.glob("state/verifiably-autonomy/runs/*/disposition.json")]),
    )
    read_end, write_end = os.pipe()
    try:
        execute(request(write_end), env, endpoint_side_unbuilt, diag=lambda _: None, actor_fds=actor, progress=Progress())
    finally:
        os.close(read_end)
    assert seen == [[], ["disposition.json"]]


def test_without_a_report_fd_only_the_exit_code_tells(tmp_path, env, actor):
    assert execute(request(), env, endpoint_side_unbuilt, diag=lambda _: None, actor_fds=actor, progress=Progress()) == 4
    assert len(runs(tmp_path)) == 1


def test_a_full_report_pipe_never_holds_the_run(tmp_path, env, actor):
    read_end, write_end = one_page_pipe()
    fill(write_end)  # never read
    try:
        code = execute(request(write_end), env, endpoint_side_unbuilt, diag=lambda _: None, actor_fds=actor, progress=Progress())
    finally:
        os.close(read_end)
    assert code == 4
    (run_dir,) = runs(tmp_path)
    assert (run_dir / "disposition.json").exists()
    assert [(e["event"], e["line"]) for e in events(run_dir)] == [("report-unwritten", "run"), ("report-unwritten", "closing")]


def test_a_lease_below_the_floor_is_refused_before_anything_exists(tmp_path, env, actor):
    with pytest.raises(RunRefused) as caught:
        execute(request(lease=5.0), env, endpoint_side_unbuilt, diag=lambda _: None, actor_fds=actor, progress=Progress())
    assert caught.value.code == "lease-below-floor"
    assert not (tmp_path / "state" / "verifiably-autonomy").exists()


def test_refused_stdio_allocates_nothing_and_writes_nothing_on_the_report_fd(tmp_path, env, actor):
    regular = os.open(tmp_path / "file", os.O_WRONLY | os.O_CREAT, 0o600)
    read_end, write_end = os.pipe()
    try:
        with pytest.raises(RunRefused) as caught:
            execute(request(write_end), env, endpoint_side_unbuilt, diag=lambda _: None,
                    actor_fds=(actor[0], actor[1], regular), progress=Progress())
        assert drain(read_end) == b""
    finally:
        for fd in (regular, read_end, write_end):
            os.close(fd)
    assert (caught.value.code, caught.value.message) == ("stdio-refused", f"fd {regular} is a regular file")
    assert runs(tmp_path) == []


def test_a_report_fd_on_the_actors_channel_is_refused(tmp_path, env, actor):
    read_end, write_end = os.pipe()
    duplicate = os.dup(write_end)
    try:
        with pytest.raises(RunRefused) as caught:
            execute(request(duplicate), env, endpoint_side_unbuilt, diag=lambda _: None,
                    actor_fds=(actor[0], write_end, actor[2]), progress=Progress())
    finally:
        for fd in (read_end, write_end, duplicate):
            os.close(fd)
    assert caught.value.code == "stdio-refused"


def test_an_unset_runtime_dir_is_refused(tmp_path, env, actor):  # Review Focus 5
    del env["XDG_RUNTIME_DIR"]
    with pytest.raises(RunRefused) as caught:
        execute(request(), env, endpoint_side_unbuilt, diag=lambda _: None, actor_fds=actor, progress=Progress())
    assert caught.value.code == "runtime-dir-unset"
    assert runs(tmp_path) == []


@pytest.mark.parametrize("value", ["", "relative/state"])
def test_an_empty_or_relative_xdg_directory_is_ignored(tmp_path, env, value):  # Review Focus 5
    env["XDG_STATE_HOME"] = value
    env["XDG_CACHE_HOME"] = value
    where = places(env)
    assert where.state == tmp_path / "home" / ".local" / "state" / "verifiably-autonomy"
    assert where.cache == tmp_path / "home" / ".cache" / "verifiably-autonomy"


@pytest.mark.parametrize("value", ["", "relative/runtime"])
def test_an_empty_or_relative_runtime_dir_is_refused_as_unset(env, value):
    env["XDG_RUNTIME_DIR"] = value
    with pytest.raises(RunRefused) as caught:
        places(env)
    assert caught.value.code == "runtime-dir-unset"


def passwd_home(monkeypatch, home: Path | None) -> None:
    """Stand in for the passwd entry: `home`, or no entry for this uid."""
    def getpwuid(uid):
        if home is None:
            raise KeyError(f"getpwuid(): uid not found: {uid}")
        return pwd.struct_passwd(("u", "x", uid, uid, "", str(home), "/bin/sh"))
    monkeypatch.setattr(pwd, "getpwuid", getpwuid)


@pytest.mark.parametrize("value", [None, "", "relative/home"])
def test_an_unset_empty_or_relative_home_falls_back_to_the_passwd_entry(tmp_path, env, monkeypatch, value):  # M4
    del env["XDG_STATE_HOME"], env["XDG_CACHE_HOME"]
    if value is None:
        del env["HOME"]
    else:
        env["HOME"] = value
    passwd_home(monkeypatch, tmp_path / "passwd-home")
    where = places(env)
    assert where.state == tmp_path / "passwd-home" / ".local" / "state" / "verifiably-autonomy"
    assert where.cache == tmp_path / "passwd-home" / ".cache" / "verifiably-autonomy"


@pytest.mark.parametrize("entry", [None, Path("relative")])
def test_no_usable_home_is_refused_when_a_default_needs_it(env, monkeypatch, entry):
    del env["HOME"], env["XDG_STATE_HOME"]
    passwd_home(monkeypatch, entry)
    with pytest.raises(RunRefused) as caught:
        places(env)
    assert caught.value.code == "home-unknown"


def test_no_home_is_needed_when_the_xdg_directories_are_set(tmp_path, env, monkeypatch):
    del env["HOME"]
    passwd_home(monkeypatch, None)
    assert places(env).state == tmp_path / "state" / "verifiably-autonomy"


def unusable_runtime(tmp_path, env) -> None:
    """An absolute XDG_RUNTIME_DIR that cannot be created: its parent is a file."""
    (tmp_path / "not-a-directory").write_text("")
    env["XDG_RUNTIME_DIR"] = str(tmp_path / "not-a-directory" / "runtime")


def scratches(tmp_path) -> list[Path]:
    root = tmp_path / "cache" / "verifiably-autonomy" / "scratch"
    return sorted(root.iterdir()) if root.exists() else []


def test_a_failed_allocation_is_refused_and_keeps_nothing(tmp_path, env):  # I1 (a)
    unusable_runtime(tmp_path, env)
    with pytest.raises(RunRefused) as caught:
        allocate(places(env))
    assert caught.value.code == "allocation-failed"
    assert str(tmp_path / "not-a-directory") in caught.value.message
    assert runs(tmp_path) == [] and scratches(tmp_path) == []


def test_a_failed_allocation_writes_nothing_on_the_report_fd_and_closes_it(tmp_path, env, actor):  # I1 (a)
    unusable_runtime(tmp_path, env)
    progress = Progress()
    read_end, write_end = os.pipe()
    try:
        with pytest.raises(RunRefused) as caught:
            execute(request(write_end), env, endpoint_side_unbuilt, diag=lambda _: None, actor_fds=actor, progress=progress)
        assert read_all(read_end) == b""  # EOF, and no line
    finally:
        os.close(read_end)
    assert caught.value.code == "allocation-failed"
    assert progress.dirs is None
    assert runs(tmp_path) == [] and scratches(tmp_path) == []


def _steps_fail(opened):
    raise RuntimeError("steps failed")


def test_steps_that_raise_leave_the_run_recorded_and_the_report_fd_closed(tmp_path, env, actor):  # I1 (c), (e)
    progress = Progress()
    read_end, write_end = os.pipe()
    try:
        with pytest.raises(RuntimeError):
            execute(request(write_end), env, _steps_fail, diag=lambda _: None, actor_fds=actor, progress=progress)
        lines = read_all(read_end).decode().splitlines()  # EOF: closed on the way out
    finally:
        os.close(read_end)
    (run_dir,) = runs(tmp_path)
    assert progress.dirs is not None and progress.dirs.run_dir == run_dir
    assert [json.loads(line)["run"] for line in lines] == [progress.dirs.run_id]  # the first line only
    assert not (run_dir / "disposition.json").exists()


def test_allocate_makes_three_private_directories(tmp_path, env):
    dirs = allocate(places(env))
    assert len(dirs.run_id) == 32 and int(dirs.run_id, 16) >= 0
    assert dirs.socket_dir == tmp_path / "runtime" / "va" / dirs.run_id[:12]
    for path in (dirs.run_dir, dirs.scratch, dirs.socket_dir):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert dirs.scratch == dirs.scratch.resolve()
    assert allocate(places(env)).run_id != dirs.run_id


FINDING = Finding("baseline-unavailable", "science", "unavailable")


def test_disposition_json_is_published_once_and_never_replaced(tmp_path):
    write_disposition(tmp_path, "r1", "unwired", [FINDING])
    first = (tmp_path / "disposition.json").read_bytes()
    with pytest.raises(FileExistsError):
        write_disposition(tmp_path, "r1", "clean", [])
    assert (tmp_path / "disposition.json").read_bytes() == first
    assert stat.S_IMODE((tmp_path / "disposition.json").stat().st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["disposition.json"]  # no temporary left


def _half_then_interrupted(fd, data):
    os.write(fd, data[: len(data) // 2])
    raise KeyboardInterrupt  # an interruption mid-record, not an error


def _interrupted(*args, **kwargs):
    raise KeyboardInterrupt


@pytest.mark.parametrize(
    ("module", "name", "replacement"),
    [("autonomy.run", "write_all", _half_then_interrupted), ("os", "fsync", _interrupted), ("os", "link", _interrupted)],
)
def test_an_interrupted_disposition_publishes_nothing_and_a_retry_succeeds(tmp_path, monkeypatch, module, name, replacement):
    with monkeypatch.context() as patch:
        patch.setattr(f"{module}.{name}", replacement)
        with pytest.raises(KeyboardInterrupt):
            write_disposition(tmp_path, "r1", "unwired", [FINDING])
    assert not (tmp_path / "disposition.json").exists()
    write_disposition(tmp_path, "r1", "unwired", [FINDING])
    assert json.loads((tmp_path / "disposition.json").read_text())["disposition"] == "unwired"


def test_an_interruption_at_the_directory_fsync_leaves_a_complete_record_and_a_retry_is_refused(tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr("autonomy.run.fsync_dir", _interrupted)
        with pytest.raises(KeyboardInterrupt):
            write_disposition(tmp_path, "r1", "unwired", [FINDING])
    assert json.loads((tmp_path / "disposition.json").read_text())["disposition"] == "unwired"
    assert [p.name for p in tmp_path.iterdir()] == ["disposition.json"]  # no temporary left
    with pytest.raises(FileExistsError):
        write_disposition(tmp_path, "r1", "unwired", [FINDING])


def test_a_temporary_left_by_a_killed_writer_does_not_block_the_retry(tmp_path):
    (tmp_path / ".disposition.json.0123456789abcdef.tmp").write_text('{"version": 1, "run"')  # torn
    write_disposition(tmp_path, "r1", "unwired", [FINDING])
    assert json.loads((tmp_path / "disposition.json").read_text())["run"] == "r1"


def long_dir(root: Path, name: str) -> Path:
    """A valid directory path of about 2,300 bytes: nine 250-byte components."""
    path = root / name
    for digit in range(9):
        path = path / (str(digit) * 250)
    path.mkdir(parents=True)
    return path


def test_a_report_line_too_long_for_one_write_is_unwritten_and_the_run_closes(tmp_path, env, actor):  # Review Focus 4
    env["XDG_STATE_HOME"] = str(long_dir(tmp_path, "state-long"))
    env["XDG_CACHE_HOME"] = str(long_dir(tmp_path, "cache-long"))
    read_end, write_end = os.pipe()
    try:
        code = execute(request(write_end), env, endpoint_side_unbuilt, diag=lambda _: None, actor_fds=actor, progress=Progress())
        assert read_all(read_end) == b""  # dropped whole, nothing after it, and the fd closed
    finally:
        os.close(read_end)
    assert code == 4
    (run_dir,) = (Path(env["XDG_STATE_HOME"]) / "verifiably-autonomy" / "runs").iterdir()
    assert json.loads((run_dir / "disposition.json").read_text())["disposition"] == "unwired"
    assert [(e["event"], e["line"]) for e in events(run_dir)] == [("report-unwritten", "run"), ("report-unwritten", "closing")]


def test_events_are_appended_one_line_each(tmp_path):
    append_event(tmp_path, "report-unwritten", line="run")
    append_event(tmp_path, "report-unwritten", line="closing")
    recorded = events(tmp_path)
    assert [e["line"] for e in recorded] == ["run", "closing"]
    assert all(e["at"].endswith("Z") for e in recorded)


def request_with_route(name: str) -> RunRequest:
    return RunRequest(REPORT_ONLY, 60.0, None, ("/usr/bin/true",), model_route=name)


def config_of(tmp_path) -> Path:
    return tmp_path / "config" / "verifiably-autonomy"


def test_places_has_the_config_directory(tmp_path, env):
    assert places(env).config == config_of(tmp_path)


def test_a_relative_config_home_falls_back_to_the_home_default(tmp_path, env):
    env["XDG_CONFIG_HOME"] = "relative/config"
    assert places(env).config == tmp_path / "home" / ".config" / "verifiably-autonomy"


def test_a_model_route_reaches_the_steps(tmp_path, env, actor):
    config = config_of(tmp_path)
    credential = write_credential(config / "credentials" / "anthropic")
    path = write_route(config, "anthropic", pi_route(credential=credential))
    seen = {}

    def steps(opened):
        seen["route"] = opened.route
        seen["config"] = opened.places.config
        return endpoint_side_unbuilt(opened)

    code = execute(request_with_route("anthropic"), env, steps, diag=lambda _: None, progress=Progress(), actor_fds=actor)
    assert code == 4
    assert seen["route"].name == "anthropic"
    assert seen["route"].data == path.read_bytes()
    assert seen["config"] == config


def test_without_a_route_the_steps_get_none(tmp_path, env, actor):
    seen = {}

    def steps(opened):
        seen["route"] = opened.route
        return endpoint_side_unbuilt(opened)

    execute(request(), env, steps, diag=lambda _: None, progress=Progress(), actor_fds=actor)
    assert seen == {"route": None}


@pytest.mark.parametrize("case", ["route-unknown", "route-invalid", "credential-unavailable"])
def test_a_route_refusal_keeps_nothing_and_writes_no_report_line(tmp_path, env, actor, case):
    config = config_of(tmp_path)
    credential = write_credential(config / "credentials" / "anthropic")
    doc = pi_route(credential=credential)
    if case == "route-invalid":
        doc["api"] = "openai-chat"
    if case == "credential-unavailable":
        os.chmod(credential, 0o644)
    if case != "route-unknown":
        write_route(config, "anthropic", doc)
    read_end, write_end = os.pipe()
    try:
        with pytest.raises(RunRefused) as caught:
            execute(
                RunRequest(REPORT_ONLY, 60.0, write_end, ("/usr/bin/true",), model_route="anthropic"),
                env, endpoint_side_unbuilt, diag=lambda _: None, progress=Progress(), actor_fds=actor,
            )
        assert caught.value.code == case
        assert runs(tmp_path) == []
        os.close(write_end)
        write_end = -1
        assert read_all(read_end) == b""
    finally:
        os.close(read_end)
        if write_end >= 0:
            os.close(write_end)
