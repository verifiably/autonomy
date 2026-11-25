"""CLI qualification against the installed science endpoint and real bubblewrap."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
import runpy
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time

import pytest

from egress_fixtures import (
    MODEL, FakeUpstream, TextTurn, governed_route, message, pi_route, raw_request, tls, to_toml, write_credential, write_route,
)

from test_analyst_check import PI_1_1_0_BETAS, toolchain

pytestmark = [pytest.mark.science_endpoint, pytest.mark.bwrap]

_STAGE = """
from pathlib import Path
import science
import sys
sys.path.insert(0, str(Path(science.__file__).resolve().parents[2] / "tests"))
from helpers.world import write_cli_config
print(write_cli_config(Path(sys.argv[1])))
"""


@dataclass
class World:
    root: Path
    env: dict[str, str]
    science: Path

    @property
    def runs(self) -> Path:
        return Path(self.env["XDG_STATE_HOME"]) / "verifiably-autonomy" / "runs"

    def control(self, action: str, run_id: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "autonomy", "run", action, run_id],
                              env=self.env if env is None else env, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=50)


@pytest.fixture
def world(tmp_path) -> Iterator[World]:
    executable = os.environ.get("SCIENCE_BIN")
    if not executable:
        pytest.skip("set SCIENCE_BIN to the qualified science executable")
    science = Path(executable)
    assert science.is_absolute() and science.name == "science" and science.is_file()
    interpreter = science.with_name("python")
    assert interpreter.is_file(), "use the qualified science bin directory with its interpreter"
    certified = os.environ.get("SCIENCE_TEST_ROOT")
    if not certified:
        pytest.fail("SCIENCE_TEST_ROOT must name writable storage certified for the pinned atoms tuple")
    with tempfile.TemporaryDirectory(prefix="va-", dir="/tmp") as runtime, \
            tempfile.TemporaryDirectory(prefix="va-world-", dir=certified) as work:
        root = Path(work).resolve()
        home = tmp_path / "home"
        home.mkdir()
        env = {
            "PATH": f"{science.parent}:/usr/bin", "HOME": str(home), "LANG": "C.UTF-8",
            "XDG_RUNTIME_DIR": runtime, "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "XDG_STATE_HOME": str(tmp_path / "state"), "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
        }
        staged = subprocess.run([str(interpreter), "-c", _STAGE, str(root)], env=env,
                                cwd=root, stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        assert staged.returncode == 0, staged.stderr.decode()
        env["SCIENCE_CONFIG"] = os.fsdecode(staged.stdout.strip())
        yield World(root, env, science)


def _line(fd: int, timeout: float = 30) -> dict:
    poll = select.poll()
    poll.register(fd, select.POLLIN)
    stop = time.monotonic() + timeout
    data = bytearray()
    while time.monotonic() < stop:
        if not poll.poll(max(1, int((stop - time.monotonic()) * 1000))):
            break
        value = os.read(fd, 1)
        if value == b"\n":
            return json.loads(data)
        if not value:
            break
        data.extend(value)
    raise AssertionError(f"incomplete run report {bytes(data)!r}")


@contextmanager
def _run(world: World, actor: list[str], *, options=(), high_report=False, tier="report-only", prelude=None):
    read_fd, write_fd = os.pipe()
    if high_report:
        high = fcntl.fcntl(write_fd, fcntl.F_DUPFD_CLOEXEC, 2048)
        os.close(write_fd)
        write_fd = high
    module = ["-m", "autonomy"] if prelude is None else [
        "-c", prelude + "\nfrom autonomy.cli import main\nraise SystemExit(main())",
    ]
    command = [sys.executable, *module, "run", "--tier", tier, "--report-fd", str(write_fd),
               "--deadline", "25", *options, "--", *actor]
    child = None
    try:
        try:
            child = subprocess.Popen(command, env=world.env, cwd=world.root, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(write_fd,),
                                     start_new_session=True)
        finally:
            os.close(write_fd)
        yield child, read_fd
    finally:
        if child is not None:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()
        os.close(read_fd)


def _disposition(directory: Path) -> dict:
    return json.loads((directory / "disposition.json").read_bytes())


def _events(directory: Path) -> list[dict]:
    return [json.loads(line) for line in (directory / "events.jsonl").read_bytes().splitlines()]


def test_real_report_only_run_closes_clean_with_byte_stdio_and_high_report_fd(world):
    actor = ["/usr/bin/python3", "-I", "-c", r"""
import os
import sys
fds = []
for name in os.listdir("/proc/self/fd"):
    try:
        os.fstat(int(name))
    except OSError:
        continue
    fds.append(int(name))
assert sorted(fds) == [0, 1, 2], fds
sys.stdout.buffer.write(sys.stdin.buffer.read())
sys.stderr.write("actor stderr\n")
"""]
    high_pipes = r"""
import fcntl, os
from autonomy.sandbox import bwrap
pipe = bwrap._pipe_above_stdio
def high_pipe():
    low = pipe()
    try:
        return tuple(fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 2048) for fd in low)
    finally:
        for fd in low:
            os.close(fd)
bwrap._pipe_above_stdio = high_pipe
"""
    with _run(world, actor, high_report=True, prelude=high_pipes) as (child, report):
        opened = _line(report)
        message = b"opaque bytes\x00\xff\n"
        out, err = child.communicate(message, timeout=55)
        directory = Path(opened["run_dir"])
        assert child.returncode == 0, (out, err, _disposition(directory), _events(directory))
        assert out == message and b"actor stderr\n" in err
        closed = _line(report)
        assert closed == {"run": opened["run"], "disposition": "clean", "exit": 0}
        assert os.read(report, 1) == b""
    verdict = _disposition(directory)
    assert verdict["disposition"] == "clean"
    assert verdict["closing_heads"]["world"]
    recovered = world.control("close", opened["run"], env={k: v for k, v in world.env.items() if k != "XDG_RUNTIME_DIR"})
    assert recovered.returncode == 0 and recovered.stdout == (directory / "disposition.json").read_bytes()


_IDLE = ["/usr/bin/python3", "-I", "-c", "import sys; print('ready', flush=True); sys.stdin.read()"]
_ATTENDED_WRITE = """
from pathlib import Path
import science
import sys
sys.path.insert(0, str(Path(science.__file__).resolve().parents[2] / "tests"))
from helpers.world import add_one_more_record
from science.config import load_config
add_one_more_record(load_config(Path(sys.argv[1])))
"""


def _attended_write(world: World):
    result = subprocess.run([str(world.science.with_name("python")), "-c", _ATTENDED_WRITE, world.env["SCIENCE_CONFIG"]],
                            env=world.env, cwd=world.root, stdin=subprocess.DEVNULL, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode()


def _eventually(check, timeout=20):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if check():
            return
        time.sleep(0.05)
    pytest.fail("timed out waiting for an integration barrier")


def _actor_ready(child):
    poll = select.poll()
    poll.register(child.stdout, select.POLLIN)
    assert poll.poll(20000), "actor did not start"
    assert child.stdout.readline() == b"ready\n"


def test_unrelated_attended_write_in_the_interval_is_quarantined(world):
    with _run(world, _IDLE) as (child, report):
        opened = _line(report)
        _actor_ready(child)
        _attended_write(world)
        child.communicate(timeout=50)
        assert child.returncode == 3
        assert _line(report)["disposition"] == "quarantined"
    findings = _disposition(Path(opened["run_dir"]))["findings"]
    assert "entry-foreign" in {f["code"] for f in findings}


def test_write_after_seal_is_excluded_from_the_interval(world):
    hold_actor = r"""
from pathlib import Path
import time
from autonomy.science_run import _supervisor
stop_actor = _supervisor._stop_actor
def wait_then_stop(actor, run_dir):
    Path(run_dir / "sealed-barrier").touch()
    until = time.monotonic() + 10
    while not (run_dir / "after-seal-written").exists() and time.monotonic() < until:
        time.sleep(0.05)
    stop_actor(actor, run_dir)
_supervisor._stop_actor = wait_then_stop
"""
    with _run(world, _IDLE, prelude=hold_actor) as (child, report):
        opened = _line(report)
        directory = Path(opened["run_dir"])
        _actor_ready(child)
        stop = world.control("stop", opened["run"])
        assert stop.returncode == 0, stop.stderr.decode()
        _eventually((directory / "sealed-barrier").exists)
        _attended_write(world)
        (directory / "after-seal-written").touch()
        child.communicate(timeout=50)
        assert child.returncode == 0, _disposition(directory)
        assert _line(report)["disposition"] == "clean"
    assert _disposition(directory)["findings"] == []


def test_supervisor_stop_cannot_extend_either_lease(world, idle_route):
    with _run(world, _IDLE, options=("--lease", "10", "--deadline", "40", "--model-route", idle_route)) as (child, report):
        opened = _line(report)
        _actor_ready(child)
        directory = Path(opened["run_dir"])
        child.send_signal(signal.SIGSTOP)
        try:
            _eventually((directory / "seal.json").is_file, timeout=18)
            assert json.loads((directory / "seal.json").read_bytes())["cause"] == "lease"
            from autonomy.egress.session import closing_line

            _eventually(lambda: (closing_line(directory / "egress.jsonl") or {}).get("closed") == "lease")
        finally:
            child.send_signal(signal.SIGCONT)
        child.communicate(timeout=50)
        assert child.returncode == 0
        assert _line(report)["disposition"] == "clean"


def test_dead_supervisor_leaves_an_orphan_until_state_only_close(world, idle_route):
    with _run(world, _IDLE, options=("--model-route", idle_route)) as (child, report):
        opened = _line(report)
        directory = Path(opened["run_dir"])
        _actor_ready(child)
        child.kill()
        child.wait(timeout=5)
        _eventually((directory / "seal.json").is_file)
    assert not (directory / "disposition.json").exists()
    assert json.loads((directory / "seal.json").read_bytes())["cause"] == "eof"
    with _run(world, ["/usr/bin/true"]) as (successor, _):
        _, stderr = successor.communicate(timeout=20)
        assert successor.returncode == 2
        assert b"orphaned-run" in stderr and opened["run"].encode() in stderr
    env = {k: v for k, v in world.env.items() if k != "XDG_RUNTIME_DIR"}
    recovered = world.control("close", opened["run"], env=env)
    assert recovered.returncode == 4, recovered.stderr.decode()
    from autonomy.allowance._configuration import resolve
    receipt = json.loads((directory / "allowance.json").read_bytes())
    config = Path(world.env["XDG_CONFIG_HOME"]) / "verifiably-autonomy"
    pool, member = resolve(config, receipt["campaign_id"] + "/" + receipt["member_id"])
    assert pool.snapshot(member)["envelopes"][0]["closed"] == 1
    assert [f["code"] for f in json.loads(recovered.stdout)["findings"]] == ["orchestrator-lost"]
    assert any(row.get("event") == "egress-closed" and row.get("cause") == "eof" for row in _events(directory))
    with _run(world, ["/usr/bin/true"]) as (successor, report):
        assert _line(report)["run"] != opened["run"]
        successor.communicate(timeout=45)
        assert successor.returncode == 0


@contextmanager
def _upstream(tls, mode="json"):
    upstream = FakeUpstream(tls, mode=mode)
    try:
        yield upstream
    finally:
        upstream.listener.shutdown(socket.SHUT_RDWR)
        upstream.stop()


def _route(world, tls, upstream, name="fixture", canary="disposable-route-canary", actor=_IDLE):
    config = Path(world.env["XDG_CONFIG_HOME"]) / "verifiably-autonomy"
    credential = write_credential(config / "credentials" / name, canary)
    route = pi_route(credential=credential, upstream=upstream.origin, ca_file=tls.cert)
    return governed_route(config, name, route, target={"actor_argv": list(actor), "model": MODEL}), credential


@pytest.fixture
def idle_route(world, tls):
    with _upstream(tls) as upstream:
        _route(world, tls, upstream)
        yield "fixture"
        assert upstream.seen == []


def test_routed_run_adds_only_its_credential_and_cuts_the_stream_on_stop(world, tls):
    canary = "disposable-route-canary"
    request = raw_request(headers=(("x-api-key", "actor-placeholder"),), body=message())
    actor = ["/usr/bin/python3", "-I", "-c", f"""
import os, socket
assert not any('KEY' in key for key in os.environ)
with socket.create_connection(("127.0.0.1", 4780), timeout=20) as stream:
    stream.sendall({request!r})
    reply = stream.recv(4096)
    assert reply.startswith(b"HTTP/1.1 200")
    print("ready", flush=True)
    while stream.recv(4096):
        pass
"""]
    with _upstream(tls, "silent") as upstream, _upstream(tls) as replacement:
        route_path, credential = _route(world, tls, upstream, canary=canary, actor=actor)
        original_digest = hashlib.sha256(route_path.read_bytes()).hexdigest()
        with _run(world, actor, options=("--model-route", "fixture")) as (child, report):
            opened = _line(report)
            alternate = write_credential(credential.with_name("replacement"), "unused-replacement-key")
            write_route(credential.parent.parent, "fixture",
                        pi_route(credential=alternate, upstream=replacement.origin, ca_file=tls.cert))
            _actor_ready(child)
            directory = Path(opened["run_dir"])
            receipt = (directory / "baseline.json").read_text()
            assert canary not in receipt and str(credential) not in receipt
            assert json.loads(receipt)["egress"]["digest"] == original_digest
            assert replacement.seen == []
            assert len(upstream.seen) == 1 and upstream.seen[0].headers["x-api-key"] == [canary]
            stopped = world.control("stop", opened["run"])
            assert stopped.returncode == 0, stopped.stderr.decode()
            child.communicate(timeout=50)
            assert child.returncode == 0, (_disposition(directory), _events(directory))
            assert _line(report)["disposition"] == "clean"
            assert upstream.peer_closed.wait(2)
    records = [json.loads(line) for line in (directory / "egress.jsonl").read_text().splitlines()]
    assert records[0]["ended"] == "route-closed"
    assert records[-1]["closed"] == "close"


@pytest.mark.pi
def test_pinned_pi_routed_through_the_production_cli(world, tls, toolchain):
    from autonomy.egress.session import EgressClosed

    pi, node = toolchain
    boot = r"""
import json, os, sys
from pathlib import Path
scratch = Path(os.environ["VERIFIABLY_SCRATCH"])
agent = scratch / "agent"
agent.mkdir()
(agent / "models.json").write_text(json.dumps({"providers": {"anthropic": {
    "baseUrl": os.environ["VERIFIABLY_MODEL_URL"], "apiKey": "actor-placeholder",
    "modelOverrides": {sys.argv[sys.argv.index("--model")+1]: {"maxTokens": 2048}},
}}}))
os.environ["PI_CODING_AGENT_DIR"] = str(agent)
os.environ["PI_OFFLINE"] = "1"
os.environ["PI_TELEMETRY"] = "0"
os.environ["PATH"] = sys.argv[1] + "/bin:/usr/bin"
os.execv(sys.argv[2], sys.argv[2:])
"""
    actor = ["/usr/bin/python3", "-I", "-c", boot, str(node), str(pi.executable), "--mode", "rpc",
             "--provider", "anthropic", "--model", MODEL, "--thinking", "off", "--no-approve", "--no-extensions",
             "--no-skills", "--no-prompt-templates", "--no-mcp"]
    with _upstream(tls, "script") as upstream:
        upstream.script = [TextTurn("local fixture response")]
        config = Path(world.env["XDG_CONFIG_HOME"]) / "verifiably-autonomy"
        credential = write_credential(config / "credentials" / "fixture", "disposable-pi-canary")
        doc = pi_route(credential=credential, upstream=upstream.origin, ca_file=tls.cert)
        doc["header_tokens"]["anthropic-beta"].extend(PI_1_1_0_BETAS)
        governed_route(config, "fixture", doc, caller="e21", target={"actor_argv": actor, "model": MODEL})
        options = ("--model-route", "fixture", "--toolchain", str(pi.dir), "--toolchain", str(node), "--deadline", "40")
        with _run(world, actor, options=options) as (child, report):
            opened = _line(report)
            directory = Path(opened["run_dir"])
            child.stdin.write(b'{"id":"p1","type":"prompt","message":"Reply with the local fixture response."}\n')
            child.stdin.flush()
            records = []
            until = time.monotonic() + 30
            while time.monotonic() < until:
                event = _line(child.stdout.fileno(), timeout=max(0, until - time.monotonic()))
                records.append(event)
                if event.get("type") == "agent_settled":
                    break
            _, err = child.communicate(timeout=50)
            assert child.returncode == 0, (err, _disposition(directory), _events(directory))
            assert _line(report)["disposition"] == "clean"
        assert len(upstream.seen) == 1
        assert upstream.seen[0].headers["x-api-key"] == ["disposable-pi-canary"]
        sent = json.loads(upstream.seen[0].body)
        assert sent["stream"] is True and sent["max_tokens"] == 2048
    rows = [json.loads(line) for line in (directory / "egress.jsonl").read_text().splitlines()]
    closed = EgressClosed(rows[-1]["closed"], rows[-1]["last_seq"], False)
    actor_exit = next(row["status"] for row in _events(directory) if row["event"] == "actor-exit")
    judge = runpy.run_path(str(Path(__file__).parents[2] / "scripts/egress_live.py"))["verdict"]
    assert not judge(rows, records, actor_exit, closed), records
    assert any("local fixture response" in json.dumps(row) for row in records)


def test_nested_handle_calls_never_open_an_endpoint_or_proxy(world):
    import autonomy

    app = str(Path(autonomy.__file__).parent.parent.resolve())
    # The actor writes each config in scratch and can see the real producer executable.
    producer = world.science.parents[4]
    python = world.science.with_name("python").resolve()
    interpreter = python.parents[1]
    site_packages = subprocess.run(
        [str(world.science.with_name("python")), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        env=world.env, stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=10,
    ).stdout.decode().strip()
    world.env["XDG_CACHE_HOME"] = str(world.root / "certified-cache")
    routing = to_toml(pi_route(credential=Path("/CREDENTIAL"), upstream="https://127.0.0.1:9"))
    boot = r"""
import json, os, pathlib, subprocess, sys
scratch = pathlib.Path(os.environ["VERIFIABLY_SCRATCH"])
sys.stdin.readline()  # fixture staging occurs after the outer gate opens
bin_dir = scratch / "bin"
bin_dir.mkdir()
science = bin_dir / "science"
science.write_text("#!" + sys.argv[2] + "\nimport site\nsite.addsitedir(" + repr(sys.argv[4]) +
                   ")\nfrom science.cli import main\nraise SystemExit(main())\n")
science.chmod(0o700)
env = {"PATH": str(bin_dir) + ":/usr/bin", "HOME": os.environ["HOME"]}
handles = {name: os.environ[name] for name in ("VERIFIABLY_ENDPOINT", "VERIFIABLY_TOKEN_FILE")}
assert not any(name.startswith("XDG_") for name in os.environ)
can_reach = subprocess.run([str(science), "--help"], env=env, capture_output=True,
                           stdin=subprocess.DEVNULL, timeout=10)
assert can_reach.returncode == 0, can_reach.stderr.decode()
run = """ + repr("import sys; sys.path.insert(0, sys.argv.pop(1)); from autonomy.cli import main; raise SystemExit(main())") + r"""
configured = {}
for name, root in (("XDG_RUNTIME_DIR", "run"), ("XDG_STATE_HOME", "state"),
                   ("XDG_CACHE_HOME", "cache"), ("XDG_CONFIG_HOME", "config")):
    p = scratch / root
    p.mkdir()
    configured[name] = str(p)
credential = scratch / "private-key"
credential.write_text("inner-fake-key\n")
credential.chmod(0o600)
route = pathlib.Path(configured["XDG_CONFIG_HOME"]) / "verifiably-autonomy/routes/fixture.toml"
route.parent.mkdir(parents=True)
route.write_text(sys.argv[3].replace("/CREDENTIAL", str(credential)))
config = scratch / "actor-science.toml"
config.write_text((scratch / "fixture-world/science.toml").read_text() + "# actor-authored\n")
cases = [
    ({}, [], "runtime-dir-unset", 2),
    ({}, ["--model-route", "fixture"], "runtime-dir-unset", 2),
    ({"XDG_RUNTIME_DIR": configured["XDG_RUNTIME_DIR"]}, ["--model-route", "missing"], "route-unknown", 2),
    (configured, [], "baseline-unavailable", 4),
    (configured, ["--model-route", "fixture"], "baseline-unavailable", 4),
]
for name in (None, *handles):
    selection = handles if name is None else {name: handles[name]}
    cases.append(({**configured, **selection, "SCIENCE_CONFIG": str(config)},
                  ["--model-route", "fixture"], "baseline-unavailable", 4))
for extra, flags, reason, wanted in cases:
    selected = {**env, **(handles if "SCIENCE_CONFIG" not in extra else {}), **extra}
    marker = scratch / "unexpected-actor"
    args = ["/usr/bin/python3", "-I", "-c", run, sys.argv[1], "run", "--tier", "coordination",
            *flags, "--", "/usr/bin/touch", str(marker)]
    result = subprocess.run(args, env=selected, stdin=subprocess.DEVNULL, capture_output=True, timeout=10)
    assert result.returncode == wanted, (reason, result.returncode, result.stderr)
    assert reason.encode() in result.stderr, result.stderr
    assert not marker.exists()
nested = pathlib.Path(configured["XDG_STATE_HOME"]) / "verifiably-autonomy/runs"
assert len(list(nested.iterdir())) == 5
assert not list(nested.glob("*/launch.json")) and not list(nested.glob("*/proxy.log"))
print(json.dumps({"cases": len(cases)}))
"""
    actor = ["/usr/bin/python3", "-I", "-c", boot, app, str(python), routing, site_packages]
    options = ("--toolchain", app, "--toolchain", str(producer), "--toolchain", str(interpreter), "--deadline", "45")
    with _run(world, actor, options=options) as (child, report):
        opened = _line(report)
        directory = Path(opened["run_dir"])
        _eventually(lambda: any(row["event"] == "actor-launched" for row in _events(directory)))
        scratch = Path(opened["scratch"])
        fixture_world = scratch / "fixture-world"
        fixture_world.mkdir()
        staged = subprocess.run([str(world.science.with_name("python")), "-c", _STAGE, str(fixture_world)],
                                env=world.env, stdin=subprocess.DEVNULL, capture_output=True, timeout=20)
        assert staged.returncode == 0, staged.stderr.decode()
        out, err = child.communicate(b"fixture staged\n", timeout=55)
        assert child.returncode == 0, (err, _disposition(directory), _events(directory))
        if not out:
            pytest.fail(err.decode())
        assert json.loads(out) == {"cases": 8}, err
        assert _line(report)["disposition"] == "clean"
    assert list(world.runs.iterdir()) == [directory]
    assert not list((fixture_world / "ops").glob("sessions/*"))


@pytest.mark.parametrize("mismatch", ["permit-mismatch", "actor-mismatch"])
def test_opening_mismatch_keeps_the_actual_actor_gate_closed(world, mismatch):
    prelude = r"""
import dataclasses
from autonomy import endpoint
from autonomy.tiers import COORDINATION
"""
    if mismatch == "permit-mismatch":
        prelude += r"""
publish = endpoint.publish_json
def widened(path, value):
    if path.name == "launch.json":
        value = {**value, "permit": COORDINATION.permit.to_json()}
    return publish(path, value)
endpoint.publish_json = widened
"""
    else:
        prelude += r"""
load = endpoint.load_ledger
def wrong_actor(*args):
    ledger = load(*args)
    return dataclasses.replace(ledger, actor="session:" + "0" * 32)
endpoint.load_ledger = wrong_actor
"""
    with _run(world, ["/usr/bin/echo", "actor marker"], prelude=prelude) as (child, report):
        opened = _line(report)
        out, err = child.communicate(timeout=50)
        directory = Path(opened["run_dir"])
        assert child.returncode == 4, (_disposition(directory), err)
        assert out == b""
        assert mismatch in {row["code"] for row in _disposition(directory)["findings"]}
        assert "actor-releasing" not in {row["event"] for row in _events(directory)}
        assert _line(report)["disposition"] == "unwired"


@pytest.mark.parametrize("detached_available", [True, False])
def test_preclaim_corpus_movement_refuses_gate_release(world, detached_available):
    prelude = f"""
from autonomy.endpoint import Endpoint
from autonomy.science_reads import ReadUnavailable, ScienceReader
import subprocess
start = Endpoint.start.__func__
heads = ScienceReader.heads
def fail_once(self, **kwargs):
    ScienceReader.heads = heads
    assert kwargs["resolve"] is False
    raise ReadUnavailable("fixture detached read failed")
def write_before_claim(cls, launch, env, *, timeout):
    result = subprocess.run([{str(world.science.with_name("python"))!r}, "-c",
                             {_ATTENDED_WRITE!r}, {world.env["SCIENCE_CONFIG"]!r}],
                            env={world.env!r}, stdin=subprocess.DEVNULL, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode()
    endpoint = start(cls, launch, env, timeout=timeout)
    if not {detached_available!r}:
        ScienceReader.heads = fail_once
    return endpoint
Endpoint.start = classmethod(write_before_claim)
"""
    with _run(world, ["/usr/bin/echo", "actor marker"], prelude=prelude) as (child, report):
        opened = _line(report)
        out, _ = child.communicate(timeout=50)
        directory = Path(opened["run_dir"])
        assert child.returncode == (4 if detached_available else 3), _disposition(directory)
        assert out == b""
        findings = {f["code"] for f in _disposition(directory)["findings"]}
        if detached_available:
            assert "baseline-raced" in findings and "entry-foreign" not in findings
            (race,) = [row for row in _events(directory) if row["event"] == "baseline-raced"]
            assert len(race["tips"]) == 1
        else:
            assert {"read-unavailable", "entry-foreign"} <= findings and "baseline-raced" not in findings
        assert "actor-releasing" not in {row["event"] for row in _events(directory)}


_WORLD_MOVE = """
from pathlib import Path
import sys
import science
sys.path.insert(0, str(Path(science.__file__).resolve().parents[2] / "tests"))
from helpers.world import FIXTURE_AUTHORITY
from science.config import corpus_id_at, load_config
from beliefs.root import open_world
cfg = load_config(Path(sys.argv[1]))
open_world(cfg.world, authority=FIXTURE_AUTHORITY).retire(corpus_id_at(cfg.write_root))
"""


@pytest.mark.parametrize("move", ["world-moved", "basis-moved"])
def test_changed_world_or_binding_quarantines_the_completed_run(world, move):
    with _run(world, _IDLE) as (child, report):
        opened = _line(report)
        directory = Path(opened["run_dir"])
        _actor_ready(child)
        if move == "world-moved":
            result = subprocess.run(
                [str(world.science.with_name("python")), "-c", _WORLD_MOVE, world.env["SCIENCE_CONFIG"]],
                env=world.env, stdin=subprocess.DEVNULL, capture_output=True, timeout=20,
            )
            assert result.returncode == 0, result.stderr.decode()
        else:
            config = Path(world.env["SCIENCE_CONFIG"])
            text = config.read_text()
            assert "coordination = 2" in text
            config.write_text(text.replace("coordination = 2", "coordination = 3"))
        child.communicate(timeout=50)
        assert child.returncode == 3, _disposition(directory)
        assert move in {row["code"] for row in _disposition(directory)["findings"]}
        assert _line(report)["disposition"] == "quarantined"


_HELD_WRITER_ACTOR = r"""
import json, os, socket
from pathlib import Path
item = Path(os.environ["VERIFIABLY_SCRATCH"]) / "measurement.txt"
item.write_text("synthetic measurement\n")
payload = {"version": "actor.v1", "token": Path(os.environ["VERIFIABLY_TOKEN_FILE"]).read_text(),
           "request": {"command": "dataset", "invocation_id": "held-fixture",
                       "inputs": {"path": str(item), "title": "Held fixture"}}}
with socket.socket(socket.AF_UNIX) as stream:
    stream.settimeout(30)
    stream.connect(os.environ["VERIFIABLY_ENDPOINT"])
    stream.sendall(json.dumps(payload).encode() + b"\n")
    stream.makefile("rb").readline()
"""

_HELD_WRITER_ENDPOINT = r"""
import dataclasses, json, os, sys, time
from pathlib import Path
from beliefs.holdings import boundary
from science.cli import main
from science.run_endpoint import service
barrier = Path(os.environ["TEST_WRITER_BARRIER"])
if sys.argv[1:3] == ["serve", "--run"]:
    original_publish = boundary._publish_record
    def hold_publication(*args, **kwargs):
        barrier.write_text(str(os.getpid()))
        until = time.monotonic() + 15
        while not barrier.with_suffix(".release").exists() and time.monotonic() < until:
            time.sleep(0.025)
        return original_publish(*args, **kwargs)
    boundary._publish_record = hold_publication
    original_serve = service.serve_run
    def shorter_bound(launch):
        def marked_seal(*args, **kwargs):
            barrier.with_suffix(".sealing").touch()
            return real_seal(*args, **kwargs)
        real_seal = service._seal_session
        service._seal_session = marked_seal
        return original_serve(dataclasses.replace(launch, seal_timeout_seconds=float(os.environ["TEST_DRAIN_BOUND"])))
    service.serve_run = shorter_bound
elif sys.argv[1] in ("heads", "log") and barrier.exists():
    pid = barrier.read_text()
    try:
        state = (Path("/proc") / pid / "stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        state = "absent"
    with barrier.with_suffix(".reads").open("a") as stream:
        print(json.dumps({"command": sys.argv[1], "endpoint_state": state}), file=stream)
raise SystemExit(main())
"""


@pytest.mark.parametrize("drained", [True, False])
def test_orphan_waits_for_a_held_writer_before_reading_its_interval(world, tmp_path, drained):
    bin_dir = tmp_path / "gate-bin"
    bin_dir.mkdir()
    shim = bin_dir / "science"
    shim.write_text(f"#!{world.science.with_name('python')}\n" + _HELD_WRITER_ENDPOINT)
    shim.chmod(0o700)
    barrier = tmp_path / "held"
    world.env["TEST_WRITER_BARRIER"] = str(barrier)
    world.env["TEST_DRAIN_BOUND"] = "6" if drained else "2"
    world.env["PATH"] = f"{bin_dir}:{world.env['PATH']}"
    actor = ["/usr/bin/python3", "-I", "-c", _HELD_WRITER_ACTOR]
    options = ("--route", "dataset=corpus-write", "--route", "holdings-observation=holdings")
    with _run(world, actor, options=options, tier="mints") as (child, report):
        opened = _line(report)
        directory = Path(opened["run_dir"])
        _eventually(barrier.exists)
        child.kill()
        child.wait(timeout=5)
        with subprocess.Popen(
            [sys.executable, "-m", "autonomy", "run", "close", opened["run"]],
            env=world.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ) as closing:
            try:
                if drained:
                    time.sleep(0.3)
                    assert closing.poll() is None
                    assert not barrier.with_suffix(".reads").exists()
                    barrier.with_suffix(".release").touch()
                verdict, err = closing.communicate(timeout=50)
            finally:
                if closing.poll() is None:
                    closing.kill()
                    closing.wait(timeout=5)
        assert closing.returncode == 4, (verdict, err, (directory / "endpoint.log").read_bytes())
    reads = [json.loads(row) for row in barrier.with_suffix(".reads").read_text().splitlines()]
    assert any(row["command"] == "log" for row in reads)
    assert all(row["endpoint_state"] in {"Z", "X", "absent"} for row in reads)
    codes = {f["code"] for f in json.loads(verdict)["findings"]}
    assert "orchestrator-lost" in codes
    if drained:
        assert (directory / "seal.json").is_file()
        assert "seal-missing" not in codes
    else:
        assert not (directory / "seal.json").exists()
        assert {"seal-missing", "session-unclosed"} <= codes


@pytest.mark.parametrize("sent, finding, proxy_end", [
    (signal.SIGTERM, None, "term"),
    (signal.SIGKILL, "egress-lost", None),
    (signal.SIGSTOP, "egress-close-timeout", None),
])
def test_proxy_death_or_stop_runs_the_endpoint_close(world, tls, sent, finding, proxy_end):
    from autonomy.process import ProcessIdentity

    with _upstream(tls) as upstream:
        _route(world, tls, upstream)
        with _run(world, _IDLE, options=("--model-route", "fixture")) as (child, report):
            opened = _line(report)
            directory = Path(opened["run_dir"])
            _actor_ready(child)
            proxy = next(row for row in _events(directory) if row["event"] == "egress-proxy")
            identity = ProcessIdentity.capture(proxy["pid"])
            assert identity.start_time == proxy["start_time"]
            if sent == signal.SIGTERM:
                # bwrap's PID 1 owns the namespace. The Python proxy is its child.
                children = Path(f"/proc/{identity.pid}/task/{identity.pid}/children").read_text().split()
                assert len(children) == 1
                identity = ProcessIdentity.capture(int(children[0]))
            fd = identity.pin()
            assert fd is not None
            try:
                signal.pidfd_send_signal(fd, sent)
                if sent == signal.SIGSTOP:
                    result = world.control("stop", opened["run"])
                    assert result.returncode == 0, result.stderr.decode()
                # Keep stdin open so an actor EOF cannot win the close race.
                child.wait(timeout=45)
            finally:
                if sent == signal.SIGSTOP and child.poll() is None:
                    signal.pidfd_send_signal(fd, signal.SIGCONT)
                os.close(fd)
            assert child.returncode == 0, _disposition(directory)
            assert _line(report)["disposition"] == "clean"
            assert (directory / "seal.json").is_file()
            causes = {row["code"] for row in _disposition(directory)["findings"]}
            assert causes == ({finding} if finding else set())
            if proxy_end is not None:
                assert proxy_end in {row.get("cause") for row in _events(directory) if row["event"] == "egress-closed"}
            assert upstream.seen == []


@contextmanager
def _another_world(world: World):
    with tempfile.TemporaryDirectory(prefix="va-world-", dir=world.root.parent) as path:
        root = Path(path)
        env = dict(world.env)  # all keys in World.env were set explicitly above
        staged = subprocess.run([str(world.science.with_name("python")), "-c", _STAGE, str(root)],
                                env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=20)
        assert staged.returncode == 0, staged.stderr.decode()
        env["SCIENCE_CONFIG"] = os.fsdecode(staged.stdout.strip())
        yield World(root, env, world.science)


def test_concurrent_routed_actors_use_separate_listeners_and_canaries(world, tls):
    request = raw_request(body=message())
    actor = ["/usr/bin/python3", "-I", "-c", f"""
import socket, sys
with socket.create_connection(("127.0.0.1", 4780), timeout=15) as stream:
    stream.sendall({request!r})
    assert stream.recv(4096).startswith(b"HTTP/1.1 200")
print("ready", flush=True)
sys.stdin.read()
"""]
    with _another_world(world) as other, _upstream(tls, "sse") as a, _upstream(tls, "sse") as b:
        a.events = b.events = 1
        _route(world, tls, a, name="first", canary="first-fake-credential", actor=actor)
        _route(other, tls, b, name="second", canary="second-fake-credential", actor=actor)
        with _run(world, actor, options=("--model-route", "first", "--deadline", "45")) as (first, first_report), \
                _run(other, actor, options=("--model-route", "second", "--deadline", "45")) as (second, second_report):
            assert _line(first_report)["run"] != _line(second_report)["run"]
            _actor_ready(first)
            _actor_ready(second)
            assert first.poll() is None and second.poll() is None
            assert [request.headers["x-api-key"] for request in a.seen] == [["first-fake-credential"]]
            assert [request.headers["x-api-key"] for request in b.seen] == [["second-fake-credential"]]
            for child, report in ((first, first_report), (second, second_report)):
                child.communicate(timeout=45)
                assert child.returncode == 0 and _line(report)["disposition"] == "clean"


@pytest.mark.parametrize("cause", ["stop", "lease"])
def test_second_act_is_refused_by_the_real_endpoint_during_seal(world, tmp_path, cause):
    bin_dir = tmp_path / "hold-bin"
    bin_dir.mkdir()
    shim = bin_dir / "science"
    shim.write_text(f"#!{world.science.with_name('python')}\n" + _HELD_WRITER_ENDPOINT)
    shim.chmod(0o700)
    barrier = tmp_path / "writing"
    world.env["TEST_WRITER_BARRIER"] = str(barrier)
    world.env["TEST_DRAIN_BOUND"] = "8"
    world.env["PATH"] = f"{bin_dir}:{world.env['PATH']}"
    boot = _HELD_WRITER_ACTOR.removesuffix('    stream.makefile("rb").readline()\n') + r"""
    import sys
    print("ready", flush=True)
    sys.stdin.readline()
    payload["request"]["invocation_id"] = "after-seal"
    with socket.socket(socket.AF_UNIX) as later:
        later.settimeout(5)
        later.connect(os.environ["VERIFIABLY_ENDPOINT"])
        later.sendall(json.dumps(payload).encode() + b"\n")
        sys.stdout.buffer.write(later.makefile("rb").readline())
        sys.stdout.flush()
    stream.makefile("rb").readline()
"""
    actor = ["/usr/bin/python3", "-I", "-c", boot]
    options = ("--route", "dataset=corpus-write", "--route", "holdings-observation=holdings",
               "--lease", "10", "--deadline", "45")
    with _run(world, actor, options=options, tier="mints") as (child, report):
        opened = _line(report)
        directory = Path(opened["run_dir"])
        _actor_ready(child)
        _eventually(barrier.exists)
        stopped = cause == "lease"
        if stopped:
            child.send_signal(signal.SIGSTOP)
        else:
            assert world.control("stop", opened["run"]).returncode == 0
        try:
            _eventually(barrier.with_suffix(".sealing").exists, timeout=17)
            child.stdin.write(b"try again\n")
            child.stdin.flush()
            refusal = _line(child.stdout.fileno(), timeout=5)
            assert refusal["refusal"]["code"] == "run-sealed"
        finally:
            barrier.with_suffix(".release").touch()
            if stopped:
                child.send_signal(signal.SIGCONT)
        _, stderr = child.communicate(timeout=50)
        assert child.returncode == 4, (stderr, _disposition(directory), _events(directory))
        assert _line(report)["disposition"] == "unwired"
        assert {f["code"] for f in _disposition(directory)["findings"]} == {"intent-unfulfilled"}
        seal = json.loads((directory / "seal.json").read_bytes())
        assert seal["cause"] == cause
        session = next(row for row in _events(directory) if row["event"] == "session-open")
        assert "after-seal" not in Path(session["ledger_path"]).read_text()


def test_process_group_signal_seals_before_the_actor_is_reaped(world):
    with _run(world, _IDLE) as (child, report):
        opened = _line(report)
        directory = Path(opened["run_dir"])
        _actor_ready(child)
        os.killpg(child.pid, signal.SIGHUP)
        child.wait(timeout=45)  # keep the actor's stdin open until containment
        assert child.returncode == 0 and _line(report)["disposition"] == "clean"
        rows = _events(directory)
        assert next(row for row in rows if row["event"] == "close-start")["cause"] == "sighup"
        names = [row["event"] for row in rows]
        assert names.index("sealed") < names.index("actor-exit")


def test_real_endpoint_lease_expiry_during_probe_keeps_actor_held(world):
    prelude = """
import time
from autonomy.science_run import _supervisor

prove = _supervisor._prove

def wait_past_lease(opened, opening, endpoint, stop):
    spec = prove(opened, opening, endpoint, stop)
    seal = opened.dirs.run_dir / "seal.json"
    until = time.monotonic() + 15
    while time.monotonic() < until and not seal.exists():
        time.sleep(0.025)
    assert seal.exists(), "endpoint did not seal while the probe held the gate"
    return spec

_supervisor._prove = wait_past_lease
_supervisor.Heartbeat._run = lambda self: None
"""
    with _run(world, ["/usr/bin/echo", "actor marker"], options=("--lease", "10"), prelude=prelude) as (child, report):
        opened = _line(report)
        out, err = child.communicate(timeout=38)
        directory = Path(opened["run_dir"])
        assert child.returncode == 4, err.decode()
        assert out == b""
        assert json.loads((directory / "seal.json").read_bytes())["cause"] == "lease"
        assert "actor-releasing" not in {row["event"] for row in _events(directory)}
        assert "endpoint-unavailable" in {row["code"] for row in _disposition(directory)["findings"]}
        assert _line(report)["disposition"] == "unwired"


_FAIL_SEAL_SYNC = r"""
import os, sys
from pathlib import Path
from science.cli import main
from science.run_endpoint import service

if sys.argv[1:3] == ["serve", "--run"]:
    persist = service.persist_seal

    def fail_seal_directory_sync(run_dir, document):
        fsync = os.fsync

        def injected(fd):
            if (run_dir / "seal.json").is_file() and os.path.samestat(os.fstat(fd), run_dir.stat()):
                raise OSError("fixture: directory sync failed after publishing the seal")
            return fsync(fd)

        os.fsync = injected
        try:
            return persist(run_dir, document)
        finally:
            os.fsync = fsync

    service.persist_seal = fail_seal_directory_sync
raise SystemExit(main())
"""


def test_visible_seal_with_failed_directory_sync_keeps_later_foreign_evidence(world, tmp_path):
    from autonomy.process import ProcessIdentity, exited

    bin_dir = tmp_path / "seal-bin"
    bin_dir.mkdir()
    shim = bin_dir / "science"
    shim.write_text(f"#!{world.science.with_name('python')}\n" + _FAIL_SEAL_SYNC)
    shim.chmod(0o700)
    world.env["PATH"] = f"{bin_dir}:{world.env['PATH']}"
    with _run(world, _IDLE) as (child, report):
        opened = _line(report)
        directory = Path(opened["run_dir"])
        _actor_ready(child)
        identity = next(row for row in _events(directory) if row["event"] == "endpoint-starting")
        endpoint = ProcessIdentity(identity["pid"], identity["start_time"], identity["boot_id"]).pin()
        assert endpoint is not None
        try:
            child.kill()
            child.wait(timeout=5)
            assert exited(endpoint, 10), "endpoint did not finish its failed seal"
        finally:
            os.close(endpoint)
    seal = json.loads((directory / "seal.json").read_bytes())
    assert b'"error":"OSError"' in (directory / "endpoint.log").read_bytes()
    assert "sealed" not in {row["event"] for row in _events(directory)}

    _attended_write(world)
    recovered = world.control("close", opened["run"])
    assert recovered.returncode == 3, (recovered.stdout, recovered.stderr)
    receipt = json.loads(recovered.stdout)
    corpus = next(row for row in seal["sealed_tips"] if row["role"] == "corpus")
    assert receipt["closing_heads"]["written"][corpus["id"]] != corpus["tip"]
    assert {row["code"] for row in receipt["findings"]} >= {"session-unclosed", "seal-missing", "entry-foreign"}
