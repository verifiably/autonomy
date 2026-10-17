import dataclasses
import json
import os
import select
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import autonomy
from egress_fixtures import (  # noqa: F401  (tls is a fixture)
    CANARY, MODEL, FakeUpstream, Tls, message, pi_route, raw_request, tls, write_credential, write_route,
)
from autonomy.egress import session as session_module
from autonomy.egress.errors import EgressUnproven
from autonomy.egress.helper import MODEL_URL
from autonomy.egress.route import egress_denied, load_route
from autonomy.egress.session import (
    EgressSession, check_proxy, closing_line, kill_orphan, proxy_argv, proxy_binds,
)
from autonomy.sandbox.bwrap import build_argv, launch, prove
from autonomy.sandbox.spec import SandboxSpec

pytestmark = pytest.mark.bwrap


@dataclass
class World:
    config: Path
    credential: Path
    run_dir: Path
    scratch: Path
    upstream: FakeUpstream
    other: FakeUpstream
    canary: str
    sessions: list = field(default_factory=list)

    def loaded(self):
        return load_route(self.config, "anthropic")

    def denied(self, loaded):
        return egress_denied(self.config, loaded)

    def start(self, *, lease: float = 30.0) -> EgressSession:
        loaded = self.loaded()
        session = EgressSession.start(loaded, self.run_dir, lease=lease, denied=self.denied(loaded))
        self.sessions.append(session)
        return session

    def clean(self) -> None:
        """A failing test must not leave a proxy behind: it has no --die-with-parent, and
        a SIGSTOPped one would wait forever. Killing a namespace's init kills it."""
        for session in self.sessions:
            if session.pidfd >= 0:
                session.kill()
        if (self.run_dir / "events.jsonl").exists():
            kill_orphan(self.run_dir, timeout=0)
        self.upstream.stop()
        self.other.stop()

    def records(self) -> list[dict]:
        path = self.run_dir / "egress.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def events(self) -> list[str]:
        path = self.run_dir / "events.jsonl"
        return [json.loads(line)["event"] for line in path.read_text().splitlines()] if path.exists() else []


def make_world(root: Path, tls: Tls, *, canary: str = CANARY, mode: str = "sse", credential_text: str | None = None) -> World:
    config = root / "config"
    credential = write_credential(config / "credentials" / "anthropic", canary)
    if credential_text is not None:
        credential.write_text(credential_text)
    upstream, other = FakeUpstream(tls, mode=mode), FakeUpstream(tls)
    write_route(config, "anthropic", pi_route(credential=credential, upstream=upstream.origin, ca_file=tls.cert))
    run_dir, scratch = root / "run", root / "scratch"
    run_dir.mkdir()
    scratch.mkdir()
    return World(config, credential, run_dir, scratch, upstream, other, canary)


@pytest.fixture
def world(tmp_path, tls):
    w = make_world(tmp_path, tls)
    yield w
    w.clean()


ACTOR = textwrap.dedent(r'''
    import errno, json, os, socket, sys, time
    port = int(os.environ["VERIFIABLY_MODEL_URL"].rsplit(":", 1)[1])
    task = json.loads(sys.argv[1])
    scratch = os.environ["SCRATCH"]
    report = {}
    received = []

    def ask(data, *, until_eof=True, mark=None):
        with socket.create_connection(("127.0.0.1", port), timeout=20) as s:
            s.sendall(data.encode("latin-1") if isinstance(data, str) else data)
            got, first = b"", None
            while True:
                try:
                    chunk = s.recv(65536)
                except OSError:
                    break
                if not chunk:
                    break
                got += chunk
                if first is None and b"event: message" in got:
                    first = time.monotonic()
                    if mark:
                        open(os.path.join(scratch, mark), "w").close()
        received.append(got)
        return got, first

    def attempt(family, address):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(3)
                s.connect(address)
            return "CONNECTED"
        except OSError as caught:
            return errno.errorcode.get(caught.errno) if caught.errno else type(caught).__name__

    def wait_for(name, seconds=30):
        deadline = time.monotonic() + seconds
        while not os.path.exists(os.path.join(scratch, name)) and time.monotonic() < deadline:
            time.sleep(0.05)

    for step in task:
        kind = step["kind"]
        if kind == "ask":
            got, first = ask(step["data"], mark=step.get("mark"))
            report[step["name"]] = {"first": first, "events": got.count(b"event: message"),
                                    "status": got.split(b" ", 2)[1].decode() if got.startswith(b"HTTP/1.1") else None,
                                    "body": got.partition(b"\r\n\r\n")[2].decode("utf-8", "replace")[:400]}
        elif kind == "connect":
            report[step["name"]] = attempt(socket.AF_INET6 if ":" in step["host"] else socket.AF_INET,
                                           (step["host"], step["port"]))
        elif kind == "resolve":
            try:
                socket.getaddrinfo(step["host"], 443)
                report[step["name"]] = "RESOLVED"
            except socket.gaierror as caught:
                report[step["name"]] = "gaierror"
        elif kind == "abstract":
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                try:
                    s.connect("\0" + step["name_"])
                    report[step["name"]] = "CONNECTED"
                except OSError as caught:
                    report[step["name"]] = errno.errorcode.get(caught.errno)
        elif kind == "wait":
            wait_for(step["file"])
        elif kind == "timed-connect":
            started = time.monotonic()
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=3) as s:
                    s.sendall(b"POST /v1/messages?beta=true HTTP/1.1\r\ncontent-length: 0\r\n\r\n")
                    s.settimeout(2)
                    outcome = "ANSWERED" if s.recv(16) else "EOF"
            except OSError as caught:
                outcome = errno.errorcode.get(caught.errno) if caught.errno else type(caught).__name__
            report[step["name"]] = {"outcome": outcome, "seconds": time.monotonic() - started}
        elif kind == "sweep":
            needle = bytes.fromhex(step["needle"])  # hex, so the needle is not itself in this argv
            found = []
            for top, dirs, files in os.walk("/"):
                if top in ("/proc", "/sys", "/dev", "/usr"):
                    dirs[:] = []
                    continue
                for name in files:
                    path = os.path.join(top, name)
                    try:
                        with open(path, "rb") as f:
                            if needle in f.read(4 << 20):
                                found.append(path)
                    except OSError:
                        pass
            for pid in os.listdir("/proc"):
                if pid.isdigit():
                    for part in ("environ", "cmdline"):
                        try:
                            if needle in open(f"/proc/{pid}/{part}", "rb").read():
                                found.append(f"/proc/{pid}/{part}")
                        except OSError:
                            pass
            if any(needle in value.encode() for value in os.environ.values()):
                found.append("environ")
            if any(needle in got for got in received):
                found.append("proxy-replies")
            report[step["name"]] = found
    print(json.dumps(report), flush=True)
''')


def run_actor(world: World, session: EgressSession, task: list[dict], *, make=None) -> tuple[dict, int]:
    spec = SandboxSpec(scratch=world.scratch, env={"VERIFIABLY_MODEL_URL": MODEL_URL, "SCRATCH": str(world.scratch)})
    out = world.scratch.parent / "actor.out"
    with open(out, "wb") as stdout, open(os.devnull, "rb") as null:
        hook = session.attach if make is None else (lambda c, p: session.attach(c, p, make=make))
        actor = launch(spec, ["/usr/bin/python3", "-I", "-c", ACTOR, json.dumps(task)],
                       stdin=null.fileno(), stdout=stdout.fileno(), stderr=stdout.fileno(), before_release=hook)
        try:
            actor.wait(timeout=120)
        finally:
            actor.close()
    lines = out.read_bytes().decode().strip().splitlines()
    return json.loads(lines[-1]), actor.child_pid


def ask(name: str, body: dict | bytes | None = None, **kw) -> dict:
    data = raw_request(body=message() if body is None else body, **kw).decode("latin-1")
    return {"kind": "ask", "name": name, "data": data}


def proxy_pid(session: EgressSession) -> int:
    children = Path(f"/proc/{session.init_pid}/task/{session.init_pid}/children").read_text().split()
    return int(children[0])


# -- the proxy's sandbox ---------------------------------------------------------------

def test_the_proxys_argv(world):
    route = world.loaded().route
    binds = proxy_binds(route)
    argv = proxy_argv(binds, control_fd=5, records_fd=6, info_fd=7)
    assert argv[:6] == ["bwrap", "--unshare-all", "--share-net", "--new-session", "--clearenv", "--proc"]
    assert "--die-with-parent" not in argv
    at = argv.index(str(world.credential))
    assert argv[at - 1 : at + 2] == ["--ro-bind", str(world.credential), "/run/va/credential"]
    assert argv[argv.index("--info-fd") + 1] == "7"


def test_a_resolver_outside_etc_is_bound(world, tmp_path):
    stub = tmp_path / "stub-resolv.conf"
    stub.write_text("nameserver 127.0.0.53\n")
    link = tmp_path / "resolv.conf"
    link.symlink_to(stub)
    binds = proxy_binds(world.loaded().route, resolv=link)
    assert (stub, str(stub)) in binds.ro


def test_the_proxys_binds_are_checked_with_only_its_files_exempt(world):
    loaded = world.loaded()
    check_proxy(proxy_binds(loaded.route), world.denied(loaded))  # the credential sits under denied <config>
    package = Path(autonomy.__file__).resolve().parent
    with pytest.raises(EgressUnproven) as caught:
        check_proxy(proxy_binds(loaded.route), [*world.denied(loaded), package.parent])
    assert caught.value.code == "proxy-bind-refused"


def test_the_proxy_gets_stdin_from_dev_null(world, monkeypatch):  # E20, the proxy's arm
    seen = {}

    def spy(argv, **kwargs):
        seen.update(kwargs)
        raise OSError("stop here")

    monkeypatch.setattr(session_module.subprocess, "Popen", spy)
    with pytest.raises(EgressUnproven):
        world.start()
    assert seen["stdin"] is subprocess.DEVNULL and seen["start_new_session"] is True


# -- E21 -----------------------------------------------------------------------------

def test_e21_the_model_route_is_the_actors_only_way_out(world):
    abstract = f"va-test-{os.getpid()}"
    host_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    host_listener.bind("\0" + abstract)
    host_listener.listen(1)
    world.upstream.events, world.upstream.gap = 5, 0.3
    loaded = world.loaded()
    spec = SandboxSpec(scratch=world.scratch, env={"VERIFIABLY_MODEL_URL": MODEL_URL, "SCRATCH": str(world.scratch)})
    prove(spec, world.denied(loaded))
    session = world.start()
    proxy_cmdline = Path(f"/proc/{session.process.pid}/cmdline").read_bytes()
    task = [
        ask("stream", headers=[("x-api-key", "placeholder")]),
        ask("connect-tunnel", method="CONNECT", target="api.anthropic.com:443", body=b""),
        ask("url-source", body=message(messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "url", "url": world.other.origin + "/x.png"}}]}])),
        {"kind": "connect", "name": "upstream-direct", "host": "127.0.0.1", "port": world.upstream.port},
        {"kind": "connect", "name": "doc-v4", "host": "192.0.2.1", "port": 443},
        {"kind": "connect", "name": "loopback-v6", "host": "::1", "port": 443},
        {"kind": "resolve", "name": "dns", "host": "api.anthropic.com"},
        {"kind": "abstract", "name": "abstract", "name_": abstract},
        {"kind": "sweep", "name": "sweep", "needle": world.canary.encode().hex()},
    ]
    report, _ = run_actor(world, session, task)
    closed = session.close()
    host_listener.close()
    assert report["stream"]["status"] == "200" and report["stream"]["events"] == 5
    assert report["stream"]["first"] < world.upstream.last_event_at
    assert json.loads(report["connect-tunnel"]["body"])["error"]["code"] == "target-refused"
    assert json.loads(report["url-source"]["body"])["error"]["code"] == "body-refused"
    assert all(report[name] != "CONNECTED" for name in ("upstream-direct", "doc-v4", "loopback-v6"))
    assert report["doc-v4"] == "ENETUNREACH"
    assert report["dns"] == "gaierror"
    assert report["abstract"] == "ECONNREFUSED"
    assert report["sweep"] == []
    (seen,) = world.upstream.seen
    assert seen.headers["x-api-key"] == [world.canary]
    assert world.other.connections == 0
    needle = world.canary.encode()
    assert needle not in proxy_cmdline
    assert world.canary not in " ".join(build_argv(spec, ["/usr/bin/python3"], info_fd=None))
    for root in (world.run_dir, world.scratch):
        for path in root.rglob("*"):
            if path.is_file():
                assert needle not in path.read_bytes(), path
    assert (closed.cause, closed.timed_out, closed.findings()) == ("close", False, ())


def test_a_credential_passed_by_setenv_would_sit_in_bwraps_argv(world):
    # Negative (E21): why the credential is bound as a file, never passed with --setenv:
    # bwrap's argv is readable through /proc by every same-uid process.
    spec = SandboxSpec(scratch=world.scratch, env={"ANTHROPIC_API_KEY": world.canary})
    assert world.canary in " ".join(build_argv(spec, ["/usr/bin/true"], info_fd=None))


def test_e21_runs_are_isolated(tmp_path, tls):
    worlds = [make_world(tmp_path / name, tls, canary=f"sk-canary-{name}", mode="json") for name in ("a", "b")]
    try:
        sessions = [w.start() for w in worlds]
        for w, s in zip(worlds, sessions):
            report, _ = run_actor(w, s, [ask("one")])
            assert report["one"]["status"] == "200"
        for w, s in zip(worlds, sessions):
            s.close()
            assert [line["seq"] for line in w.records() if "seq" in line] == [1]
            (seen,) = w.upstream.seen
            assert seen.headers["x-api-key"] == [w.canary]
    finally:
        for w in worlds:
            w.clean()


def test_e21_the_route_enforced_is_the_one_loaded(world):
    loaded = world.loaded()
    doc = pi_route(credential=world.credential, upstream=world.upstream.origin, ca_file=loaded.route.ca_file)
    doc["operations"][0]["models"] = ["claude-opus-5-5"]
    write_route(world.config, "anthropic", doc)  # edited after step 2
    session = EgressSession.start(loaded, world.run_dir, lease=30, denied=world.denied(loaded))
    report, _ = run_actor(world, session, [ask("haiku")])
    session.close()
    assert report["haiku"]["status"] == "200"  # the loaded bytes, not the edit
    assert load_route(world.config, "anthropic").digest != loaded.digest


def test_a_proxy_that_rereads_the_route_file_would_enforce_the_edit(world):
    # Negative (E22): a proxy given the file as it is now, not the bytes step 2 read and
    # digested, enforces an edit that baseline.json's digest does not show.
    loaded = world.loaded()
    doc = pi_route(credential=world.credential, upstream=world.upstream.origin, ca_file=loaded.route.ca_file)
    doc["operations"][0]["models"] = ["claude-opus-5-5"]
    write_route(world.config, "anthropic", doc)
    reread = dataclasses.replace(loaded, data=loaded.path.read_bytes())
    session = EgressSession.start(reread, world.run_dir, lease=30, denied=world.denied(loaded))
    world.sessions.append(session)
    report, _ = run_actor(world, session, [ask("haiku")])
    session.close()
    assert json.loads(report["haiku"]["body"])["error"]["code"] == "model-refused"


# -- E22 -----------------------------------------------------------------------------

def when_listening(world: World, action) -> threading.Thread:
    """Run `action` in the background once the proxy holds the actor's listener: the
    actor itself must be launched from the main thread (`launch` refuses others)."""

    def wait_then_act():
        deadline = time.monotonic() + 30
        while "egress-listening" not in world.events() and time.monotonic() < deadline:
            time.sleep(0.05)
        action()

    thread = threading.Thread(target=wait_then_act)
    thread.start()
    return thread


def test_e22_stop_cuts_the_stream_and_the_next_connect_is_refused(world):
    world.upstream.events, world.upstream.gap = 30, 0.3
    session = world.start()
    marker = world.scratch / "streaming"
    outcome = {}

    def stop_once_streaming():
        deadline = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        outcome["closed"] = session.close()
        (world.scratch / "go").touch()

    stopper = when_listening(world, stop_once_streaming)
    report, _ = run_actor(world, session, [
        {**ask("stream"), "mark": "streaming"},
        {"kind": "wait", "file": "go"},
        {"kind": "timed-connect", "name": "after"},
    ])
    stopper.join(60)
    assert report["stream"]["events"] < 30
    assert report["after"]["outcome"] == "ECONNREFUSED"
    records = world.records()
    stream = next(line for line in records if line.get("seq") == 1)
    assert stream["ended"] == "route-closed"
    closing = records[-1]
    assert outcome["closed"].cause == "close" and closing["closed"] == "close"
    assert all(line["seq"] <= closing["last_seq"] for line in records if line.get("seq") is not None)
    assert "egress-closed" in world.events()


ORCHESTRATOR = textwrap.dedent("""
    import json, sys, time
    sys.path.insert(0, sys.argv[1])
    from pathlib import Path
    from autonomy.egress.route import egress_denied, load_route
    from autonomy.egress.session import EgressSession
    config, run_dir, lease = Path(sys.argv[2]), Path(sys.argv[3]), float(sys.argv[4])
    loaded = load_route(config, "anthropic")
    session = EgressSession.start(loaded, run_dir, lease=lease, denied=egress_denied(config, loaded))
    print(json.dumps({"init": session.init_pid}), flush=True)
    while True:
        time.sleep(lease / 3)
        session.renew()
""")


def orchestrator(world: World, lease: float) -> tuple[subprocess.Popen, int]:
    package_parent = str(Path(autonomy.__file__).resolve().parent.parent)
    process = subprocess.Popen(
        [sys.executable, "-c", ORCHESTRATOR, package_parent, str(world.config), str(world.run_dir), str(lease)],
        stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
    )
    init = json.loads(process.stdout.readline())["init"]
    return process, init


def wait_closed(world: World, seconds: float) -> dict | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        line = closing_line(world.run_dir / "egress.jsonl")
        if line is not None:
            return line
        time.sleep(0.05)
    return None


def test_e22_a_stopped_orchestrator_loses_the_route_at_the_lease(world):
    process, _ = orchestrator(world, lease=3.0)
    try:
        time.sleep(1.5)  # renewing
        assert closing_line(world.run_dir / "egress.jsonl") is None
        process.send_signal(signal.SIGSTOP)
        line = wait_closed(world, 6.0)
        assert line is not None and line["closed"] == "lease"
    finally:
        process.send_signal(signal.SIGCONT)
        process.kill()
        process.wait()


def test_e22_a_dead_orchestrator_closes_the_route_by_eof(world):
    process, init = orchestrator(world, lease=30.0)
    process.kill()
    process.wait()
    line = wait_closed(world, 5.0)
    assert line is not None and line["closed"] == "eof"
    closed = kill_orphan(world.run_dir)
    assert (closed.cause, closed.timed_out) == ("eof", False)
    deadline = time.monotonic() + 5
    while Path(f"/proc/{init}").exists() and time.monotonic() < deadline:  # reaped by its parent
        time.sleep(0.05)
    assert not Path(f"/proc/{init}").exists()


def test_e22_run_close_kills_a_wedged_orphan_proxy(world):
    process, init = orchestrator(world, lease=30.0)
    children = Path(f"/proc/{init}/task/{init}/children").read_text().split()
    os.kill(int(children[0]), signal.SIGSTOP)
    process.kill()
    process.wait()
    started = time.monotonic()
    closed = kill_orphan(world.run_dir)
    assert 4.5 < time.monotonic() - started < 8
    assert closed.timed_out and [f.code for f in closed.findings()] == ["egress-close-timeout"]
    assert exited_now(init)  # kill_orphan returns only once the proxy has exited
    deadline = time.monotonic() + 5
    while Path(f"/proc/{init}").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not Path(f"/proc/{init}").exists()


def exited_now(pid: int) -> bool:
    try:
        fd = os.pidfd_open(pid)
    except ProcessLookupError:
        return True
    try:
        return bool(select.select([fd], [], [], 0)[0])
    finally:
        os.close(fd)


def test_a_killed_orphan_is_settled_only_once_it_has_exited(world, monkeypatch):
    # The real SIGKILL lands 0.5 s late, as an exit that takes time: kill_orphan must
    # wait for it, not settle when the signal call returns.
    process, init = orchestrator(world, lease=30.0)
    children = Path(f"/proc/{init}/task/{init}/children").read_text().split()
    os.kill(int(children[0]), signal.SIGSTOP)
    process.kill()
    process.wait()
    real = signal.pidfd_send_signal

    def slow_exit(pidfd, sig):
        target = os.pidfd_open(init)

        def later():
            try:
                real(target, sig)
            finally:
                os.close(target)

        threading.Timer(0.5, later).start()

    monkeypatch.setattr(session_module.signal, "pidfd_send_signal", slow_exit)
    closed = kill_orphan(world.run_dir, timeout=0.5)
    assert closed.timed_out
    assert exited_now(init)


def test_an_orphan_that_exits_before_the_signal_is_settled_without_error(world, monkeypatch):
    process, init = orchestrator(world, lease=30.0)
    children = Path(f"/proc/{init}/task/{init}/children").read_text().split()
    os.kill(int(children[0]), signal.SIGSTOP)
    process.kill()
    process.wait()

    real = signal.pidfd_send_signal

    def exits_first(pidfd, sig):
        real(pidfd, sig)  # the proxy really exits first...
        select.select([pidfd], [], [], 5)
        raise ProcessLookupError(3, "No such process")  # ...so the signal finds no process

    monkeypatch.setattr(session_module.signal, "pidfd_send_signal", exits_first)
    closed = kill_orphan(world.run_dir, timeout=0.5)
    assert (closed.timed_out, [f.code for f in closed.findings()]) == (False, ["egress-lost"])
    assert exited_now(init)


def test_an_orphan_that_survives_its_kill_is_a_cleanup_failure(world, monkeypatch):
    process, init = orchestrator(world, lease=30.0)
    children = Path(f"/proc/{init}/task/{init}/children").read_text().split()
    os.kill(int(children[0]), signal.SIGSTOP)
    process.kill()
    process.wait()
    monkeypatch.setattr(session_module, "CLOSE_TIMEOUT", 0.5)
    monkeypatch.setattr(session_module.signal, "pidfd_send_signal", lambda pidfd, sig: None)  # the kill never lands
    with pytest.raises(session_module.ProxySurvived) as caught:
        kill_orphan(world.run_dir, timeout=0.5)
    assert caught.value.pid == init
    assert "egress-closed" not in world.events() and "egress-lost" not in world.events()  # nothing settled


@pytest.mark.parametrize("failure", ["egress-proxy", "egress-ready", "receive"])
def test_a_failed_start_leaves_no_proxy_and_no_descriptor(world, monkeypatch, failure):
    started = {}
    real_info = session_module.read_info

    def spy_info(fd, process):
        info = real_info(fd, process)
        started["init"] = info["child-pid"]
        return info

    monkeypatch.setattr(session_module, "read_info", spy_info)
    real_event = session_module.append_event

    def event(run_dir, name, **fields):
        if name == failure:
            raise OSError(28, "No space left on device")
        real_event(run_dir, name, **fields)

    monkeypatch.setattr(session_module, "append_event", event)
    if failure == "receive":
        monkeypatch.setattr(EgressSession, "_receive", lambda self, timeout: (_ for _ in ()).throw(OSError(5, "EIO")))
    fds_before = len(os.listdir("/proc/self/fd"))
    with pytest.raises(OSError):
        world.start()
    assert exited_now(started["init"])
    assert len(os.listdir("/proc/self/fd")) == fds_before


def test_e22_sigterm_to_the_proxy_closes_it(world):
    session = world.start()
    os.kill(proxy_pid(session), signal.SIGTERM)
    line = wait_closed(world, 5.0)
    assert line is not None and line["closed"] == "term"
    assert session.close().cause == "term"


def test_e22_a_dead_proxy_leaves_nothing_listening(world):
    session = world.start()

    def kill_then_go():
        signal.pidfd_send_signal(session.pidfd, signal.SIGKILL)
        time.sleep(0.5)
        (world.scratch / "go").touch()

    killer = when_listening(world, kill_then_go)
    report, _ = run_actor(world, session, [{"kind": "wait", "file": "go"}, {"kind": "timed-connect", "name": "after"}])
    killer.join(30)
    after = report["after"]
    assert after["outcome"] == "ECONNREFUSED" and after["seconds"] < 1
    closed = session.close()
    assert [f.code for f in closed.findings()] == ["egress-lost"]


def test_e22_a_listener_copy_kept_by_the_orchestrator_would_leave_the_actor_hanging(world):
    # Negative (E22): a copy outlives the proxy, so the kernel queues the connect in
    # the backlog and nobody answers, instead of refusing it.
    session = world.start()
    kept = []

    def keeping(child, pidfd):
        listener = session_module.make_listener(child, pidfd)
        kept.append(listener.dup())
        return listener

    def kill_then_go():
        signal.pidfd_send_signal(session.pidfd, signal.SIGKILL)
        time.sleep(0.5)
        (world.scratch / "go").touch()

    killer = when_listening(world, kill_then_go)
    report, _ = run_actor(world, session, [{"kind": "wait", "file": "go"}, {"kind": "timed-connect", "name": "after"}],
                          make=keeping)
    killer.join(30)
    assert report["after"]["outcome"] in ("TimeoutError", "timeout")
    kept[0].close()
    session.close()


def test_e22_a_proxy_that_ignores_close_is_killed_after_5_s(world):
    session = world.start()
    os.kill(proxy_pid(session), signal.SIGSTOP)
    started = time.monotonic()
    closed = session.close()
    assert 4.5 < time.monotonic() - started < 8
    assert closed.timed_out and [f.code for f in closed.findings()] == ["egress-close-timeout"]
    assert "egress-close-timeout" in world.events()


def test_e22_a_credential_removed_before_the_start_is_unproven(world):
    loaded = world.loaded()
    world.credential.unlink()
    with pytest.raises(EgressUnproven) as caught:
        EgressSession.start(loaded, world.run_dir, lease=30, denied=world.denied(loaded))
    assert caught.value.code == "proxy-bind-refused"  # its bind source is gone: the static check stops it


def test_e22_a_two_line_credential_is_unproven(tmp_path, tls):
    world = make_world(tmp_path, tls, credential_text="sk-one\nsk-two\n")
    try:
        with pytest.raises(EgressUnproven) as caught:
            world.start()
        assert caught.value.code == "proxy-unready" and "credential-invalid" in caught.value.message
    finally:
        world.clean()


def test_e22_a_failed_helper_never_releases_the_actor(world):
    session = world.start()

    def refused(child, pidfd):
        time.sleep(0.5)  # an actor already released would have printed by now
        raise EgressUnproven("listener-failed", "setns: Operation not permitted")

    with pytest.raises(EgressUnproven):
        run_actor(world, session, [{"kind": "connect", "name": "ran", "host": "192.0.2.1", "port": 443}], make=refused)
    assert not (world.scratch.parent / "actor.out").read_bytes()
    session.kill()


def test_e22_a_proxy_that_never_listens_is_unproven(world):
    session = world.start()
    os.kill(proxy_pid(session), signal.SIGSTOP)
    started = time.monotonic()
    with pytest.raises(EgressUnproven) as caught:
        run_actor(world, session, [{"kind": "connect", "name": "ran", "host": "192.0.2.1", "port": 443}])
    assert caught.value.code == "proxy-unlistening" and 4.5 < time.monotonic() - started < 8
    assert not (world.scratch.parent / "actor.out").read_bytes()
    session.kill()
