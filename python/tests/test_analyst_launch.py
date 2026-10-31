import dataclasses
import json
import os
import time
from pathlib import Path

import pytest

from autonomy.analyst.launch import AnalystRequest, Progress, actor_env, execute, pi_argv, refuse
from autonomy.analyst.toolchain import ANALYST_TOOLS, AnalystRefused, check_pi
from egress_fixtures import MODEL, FakeUpstream, pi_route, tls, write_credential, write_route  # noqa: F401
from test_analyst_toolchain import node_tree, pi_tree


@pytest.fixture
def world(tmp_path, tls):
    """A temporary XDG layout with a pi route, a placeholder credential, a pinned pi tree,
    a node tree, an input, a denied directory and a release directory."""
    config = tmp_path / "config/verifiably-autonomy"
    credential = write_credential(config / "credentials/anthropic", "placeholder-not-a-key")
    write_route(config, "pi", pi_route(credential=credential, upstream="https://localhost:1", ca_file=tls.cert))
    env = {"HOME": str(tmp_path / "home"), "XDG_CONFIG_HOME": str(tmp_path / "config"),
           "XDG_STATE_HOME": str(tmp_path / "state"), "XDG_CACHE_HOME": str(tmp_path / "cache"), "PATH": "/usr/bin"}
    for name in ("home", "bundle", "release", "key"):
        (tmp_path / name).mkdir()
    (tmp_path / "key/k.json").write_text("{}")
    return {"env": env, "tmp": tmp_path, "pi": pi_tree(tmp_path / "pi"), "node": node_tree(tmp_path / "node"),
            "request": AnalystRequest("pi", MODEL, (tmp_path / "bundle",), (tmp_path / "key",), tmp_path / "release",
                                      pi_dir=tmp_path / "pi", node_dir=tmp_path / "node")}


@pytest.fixture
def null_fds():
    fds = tuple(os.open(os.devnull, os.O_RDWR) for _ in range(3))
    yield fds
    for fd in fds:
        os.close(fd)


def test_a_complete_request_is_prepared(world, null_fds):
    prepared = refuse(world["request"], world["env"], actor_fds=null_fds)
    assert prepared.inputs == ((world["tmp"] / "bundle").resolve(),)
    assert (world["tmp"] / "key").resolve() in prepared.denied and prepared.release_dir in prepared.denied
    assert prepared.places.state in prepared.denied
    assert prepared.route.name == "pi" and prepared.pi.version == "1.1.0"


def test_relative_and_trailing_slash_paths_resolve(world, null_fds, monkeypatch):  # Review Focus 1
    monkeypatch.chdir(world["tmp"])
    request = dataclasses.replace(world["request"], inputs=(Path("./bundle/"),), denied=(Path("key/../key"),))
    prepared = refuse(request, world["env"], actor_fds=null_fds)
    assert prepared.inputs == ((world["tmp"] / "bundle").resolve(),)
    assert (world["tmp"] / "key").resolve() in prepared.denied


@pytest.mark.parametrize(("change", "code"), [
    (lambda w: {"lease": 1.0}, "lease-below-floor"),
    (lambda w: {"model_route": "nope"}, "route-unknown"),
    (lambda w: {"model": "claude-nope"}, "model-unrouted"),
    (lambda w: {"inputs": (w["tmp"] / "absent",)}, "input-missing"),
    (lambda w: {"inputs": (w["tmp"] / "bundle", w["tmp"] / "bundle" / "sub")}, "input-nested"),
    (lambda w: {"inputs": (w["tmp"] / "pi",)}, "input-nested"),
    (lambda w: {"inputs": (w["tmp"] / "key",)}, "bind-overlaps-denied"),
    (lambda w: {"release_dir": w["tmp"] / "bundle"}, "release-unusable"),
    (lambda w: {"release_dir": w["tmp"] / "absent"}, "release-unusable"),
    (lambda w: {"pi_dir": w["tmp"] / "absent"}, "pi-mismatch"),
    (lambda w: {"node_dir": w["tmp"] / "absent"}, "node-missing"),
])
def test_each_configuration_refusal_is_typed_and_keeps_nothing(world, null_fds, change, code):
    (world["tmp"] / "bundle/sub").mkdir(exist_ok=True)
    request = dataclasses.replace(world["request"], **change(world))
    with pytest.raises(AnalystRefused) as caught:
        refuse(request, world["env"], actor_fds=null_fds)
    assert caught.value.code == code
    assert not (world["tmp"] / "state").exists() and not (world["tmp"] / "cache").exists()


def test_a_terminal_or_file_on_stdio_is_refused(world, tmp_path):
    fd = os.open(tmp_path / "log", os.O_RDWR | os.O_CREAT)
    try:
        with pytest.raises(AnalystRefused) as caught:
            refuse(world["request"], world["env"], actor_fds=(fd, fd, fd))
        assert caught.value.code == "stdio-refused"
    finally:
        os.close(fd)


def test_an_input_given_as_a_symlink_is_bound_at_its_real_path(world, null_fds):
    link = world["tmp"] / "bundle-link"
    link.symlink_to(world["tmp"] / "bundle")
    prepared = refuse(dataclasses.replace(world["request"], inputs=(link,)), world["env"], actor_fds=null_fds)
    assert prepared.inputs == ((world["tmp"] / "bundle").resolve(),)


@pytest.mark.skipif(os.getuid() == 0, reason="root ignores directory modes")
def test_a_denied_path_that_cannot_be_stat_ed_is_refused(world, null_fds):
    locked = world["tmp"] / "locked"
    locked.mkdir()
    (locked / "k").write_text("")
    locked.chmod(0o000)
    try:
        with pytest.raises(AnalystRefused) as caught:
            refuse(dataclasses.replace(world["request"], denied=(locked / "k",)), world["env"], actor_fds=null_fds)
        assert caught.value.code == "denied-unreadable"
    finally:
        locked.chmod(0o700)


def test_the_runtime_dir_is_not_required(world, null_fds):
    assert "XDG_RUNTIME_DIR" not in world["env"]
    refuse(world["request"], world["env"], actor_fds=null_fds)


def test_pi_argv_and_env_are_the_contract(world):
    scratch = world["tmp"] / "scratch"
    argv = pi_argv(check_pi(world["pi"]), MODEL, scratch)
    assert argv[0] == str(world["pi"] / "node_modules/.bin/pi")
    assert argv[1:] == ["--mode", "rpc", "--provider", "anthropic", "--model", MODEL, "--thinking", "off",
                        "--session-dir", str(scratch / "sessions"), "--no-approve", "--no-extensions", "--no-skills",
                        "--no-prompt-templates", "--no-mcp", "--no-context-files", "--tools", ",".join(ANALYST_TOOLS)]
    env = actor_env(world["node"], scratch)
    assert env == {"PATH": f"{world['node']}/bin:/usr/bin", "HOME": str(scratch / "home"),
                   "PI_CODING_AGENT_DIR": str(scratch / "agent"), "PI_OFFLINE": "1", "PI_TELEMETRY": "0",
                   "LANG": "C.UTF-8", "VERIFIABLY_MODEL_URL": "http://127.0.0.1:4780"}


# The launch itself, under real bwrap: the fake upstream stands in for the provider so
# the proxy starts, and a shell script stands in for pi through the actor_argv hook.
bwrap = pytest.mark.bwrap


@pytest.fixture
def served_world(world, tls):
    upstream = FakeUpstream(tls, mode="script")
    config = world["tmp"] / "config/verifiably-autonomy"
    credential = config / "credentials/anthropic"
    write_route(config, "pi", pi_route(credential=credential, upstream=upstream.origin, ca_file=tls.cert))
    yield {**world, "upstream": upstream}
    upstream.stop()


def shell_actor(script: str):
    def argv(pi, model, scratch):
        return ["/usr/bin/sh", "-c", script.replace("SCRATCH", str(scratch))]

    return argv


def run_execute(served, *, script, report=False, request=None):
    to_actor_r, to_actor_w = os.pipe()
    from_actor_r, from_actor_w = os.pipe()
    err_r, err_w = os.pipe()
    report_r, report_w = os.pipe() if report else (None, None)
    request = dataclasses.replace(request or served["request"], report_fd=report_w)
    diags, progress = [], Progress()
    code = execute(request, served["env"], diag=diags.append, progress=progress, actor_fds=(to_actor_r, from_actor_w, err_w),
                   actor_argv=shell_actor(script))
    for fd in (to_actor_r, to_actor_w, from_actor_w, err_w):
        os.close(fd)
    out = b""
    while chunk := os.read(from_actor_r, 65536):
        out += chunk
    err = b""
    while chunk := os.read(err_r, 65536):
        err += chunk
    lines = []
    if report:
        data = b""
        while chunk := os.read(report_r, 65536):
            data += chunk
        lines = [json.loads(line) for line in data.decode().splitlines()]
        os.close(report_r)
    os.close(from_actor_r)
    os.close(err_r)
    return code, progress, out, err, lines, diags


@bwrap
def test_a_clean_run_releases_and_reports(served_world):
    code, progress, out, err, lines, _ = run_execute(
        served_world, report=True,
        script="echo hello; echo 'result' > SCRATCH/outputs/result.txt; mkdir SCRATCH/outputs/figs; echo x > SCRATCH/outputs/figs/a; exit 0")
    assert code == 0 and out == b"hello\n"
    run_dir = progress.run_dir
    assert lines[0]["run_dir"] == str(run_dir) and lines[1]["exit"] == 0 and lines[1]["released"] == 2
    assert lines[1]["egress"] == "close"
    assert (served_world["tmp"] / "release/result.txt").read_text() == "result\n"
    assert (served_world["tmp"] / "release/figs/a").exists()
    events = [json.loads(line)["event"] for line in (run_dir / "events.jsonl").read_text().splitlines()]
    assert events[0] == "allocated" and "proved" in events and "launched" in events
    assert events[-1] == "closed"
    for name in ("walk.json", "release.json", "epoch.json", "launcher.log", "egress.jsonl"):
        assert (run_dir / name).exists(), name
    assert json.loads((run_dir / "epoch.json").read_text())["pi"]["version"] == "1.1.0"
    models = served_world["tmp"] / "cache/verifiably-autonomy/analyst" / run_dir.name / "scratch/agent/models.json"
    assert json.loads(models.read_text()) == {"providers": {"anthropic": {"baseUrl": "http://127.0.0.1:4780", "apiKey": "placeholder"}}}


@bwrap
def test_a_planted_symlink_is_refused_at_release_and_exits_3(served_world):
    secret = served_world["tmp"] / "key/k.json"
    code, progress, _, _, lines, _ = run_execute(
        served_world, report=True, script=f"ln -s {secret} SCRATCH/outputs/link; echo ok > SCRATCH/outputs/ok; exit 0")
    assert code == 3 and lines[1]["refused"] == 1 and lines[1]["released"] == 1
    report = json.loads((progress.run_dir / "release.json").read_text())
    assert report["refused"] == [{"path": "link", "reason": "symlink"}]
    assert not (served_world["tmp"] / "release/link").exists()


@bwrap
def test_a_non_zero_actor_exits_3(served_world):
    code, _, _, _, lines, _ = run_execute(served_world, report=True, script="exit 7")
    assert code == 3 and lines[1]["pi_exit"] == 7


@bwrap
def test_an_actor_that_exits_at_once_still_closes_and_releases(served_world):  # Review Focus 4
    code, progress, _, _, _, _ = run_execute(served_world, script="exit 0")
    assert code == 0 and (progress.run_dir / "release.json").exists() and progress.scratch.is_dir()
    assert json.loads((progress.run_dir / "events.jsonl").read_text().splitlines()[-1])["event"] == "closed"


@bwrap
def test_the_actor_cannot_see_the_denied_or_run_directories(served_world):
    key = served_world["tmp"] / "key/k.json"
    state = served_world["tmp"] / "state"
    code, progress, out, _, _, _ = run_execute(
        served_world, script=f"ls {key} 2>&1; ls {state} 2>&1; ls {served_world['tmp']}/bundle && echo bundle-ok")
    assert code == 0 and b"bundle-ok" in out and out.count(b"No such file") == 2


@bwrap
def test_the_deadline_kills_the_actor(served_world):
    request = dataclasses.replace(served_world["request"], deadline=2.0)
    start = time.monotonic()
    code, progress, _, _, _, _ = run_execute(served_world, script="sleep 60", request=request)
    assert time.monotonic() - start < 90 and code == 3  # walk + launch + 2 s deadline + the 10 s SIGTERM grace + close
    assert json.loads((progress.run_dir / "events.jsonl").read_text().splitlines()[-1])["pi_exit"] not in (0, None)


@bwrap
def test_a_failed_walk_exits_4_with_its_code_recorded(served_world):
    bundle = served_world["tmp"] / "bundle"
    key = served_world["tmp"] / "key/k.json"
    os.link(key, bundle / "alias")
    code, progress, _, _, lines, _ = run_execute(served_world, report=True, script="exit 0")
    assert code == 4 and progress.run_dir is not None and len(lines) == 1
    events = [json.loads(line) for line in (progress.run_dir / "events.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "unproven" and events[-1]["code"] == "walk-hardlink"
    assert not (progress.run_dir / "release.json").exists()


@bwrap
def test_an_actor_that_replaces_outputs_still_closes_with_exit_3(served_world):
    key_dir = served_world["tmp"] / "key"
    code, progress, _, _, lines, _ = run_execute(
        served_world, report=True, script=f"rmdir SCRATCH/outputs; ln -s {key_dir} SCRATCH/outputs; exit 0")
    assert code == 3 and lines[1]["exit"] == 3 and lines[1]["refused"] == 1 and lines[1]["released"] == 0
    report = json.loads((progress.run_dir / "release.json").read_text())
    assert report["refused"][0]["reason"] == "outputs-unusable"
    assert json.loads((progress.run_dir / "events.jsonl").read_text().splitlines()[-1])["event"] == "closed"
    assert not (served_world["tmp"] / "release/k.json").exists()


@bwrap
def test_a_start_time_that_cannot_be_read_is_recorded_as_null(served_world, monkeypatch):
    """A fast-exiting actor's init can be gone before /proc/<pid>/stat is read (Review Focus 4)."""
    import autonomy.analyst.launch as launch_module

    def gone(pid):
        raise FileNotFoundError(f"/proc/{pid}/stat")

    monkeypatch.setattr(launch_module, "_start_time", gone)
    code, progress, _, _, _, _ = run_execute(served_world, script="exit 0")
    events = [json.loads(line) for line in (progress.run_dir / "events.jsonl").read_text().splitlines()]
    launched = next(e for e in events if e["event"] == "launched")
    assert code == 0 and launched["start_time"] is None and events[-1]["event"] == "closed"


@bwrap
def test_a_failure_during_supervision_still_kills_the_proxy_and_the_actor(served_world, monkeypatch):
    import autonomy.analyst.launch as launch_module

    def boom(actor, session, request, log):
        raise RuntimeError("supervision failed")

    monkeypatch.setattr(launch_module, "_supervise", boom)
    to_actor_r, to_actor_w = os.pipe()
    from_actor_r, from_actor_w = os.pipe()
    err_r, err_w = os.pipe()
    progress = Progress()
    try:
        with pytest.raises(RuntimeError, match="supervision failed"):
            execute(served_world["request"], served_world["env"], diag=lambda line: None, progress=progress,
                    actor_fds=(to_actor_r, from_actor_w, err_w), actor_argv=shell_actor("sleep 60"))
    finally:
        for fd in (to_actor_r, to_actor_w, from_actor_r, from_actor_w, err_r, err_w):
            os.close(fd)
    events = [json.loads(line) for line in (progress.run_dir / "events.jsonl").read_text().splitlines()]
    proxy = next(e for e in events if e["event"] == "egress-proxy")
    actor = next(e for e in events if e["event"] == "launched")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and any(_alive(e["pid"] if "pid" in e else e["child_pid"], e["start_time"]) for e in (proxy, actor)):
        time.sleep(0.1)
    assert not _alive(proxy["pid"], proxy["start_time"]), "the proxy namespace survived"
    assert not _alive(actor["child_pid"], actor["start_time"]), "the actor namespace survived"


def _alive(pid: int, start_time: int | None) -> bool:
    """True when `pid` is a live process with that start time (a reused pid is not it)."""
    try:
        stat_ = Path(f"/proc/{pid}/stat").read_bytes()
    except FileNotFoundError:
        return False
    return start_time is None or int(stat_.rsplit(b")", 1)[1].split()[19]) == start_time
