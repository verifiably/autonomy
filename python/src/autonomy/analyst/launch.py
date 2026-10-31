"""`autonomy analyst` (envelope design decision 14): a fresh pi analyst under the sandbox,
with caller-declared read-only inputs, extra denied paths and one output directory,
composed from Plan B1's launch path and the egress plan, with no endpoint.

Step 1 refuses on configuration before anything exists. Two calls of the implementer's:
an input that is itself a denied path is refused here as `bind-overlaps-denied` (the
static check's code), cheaper than a doomed launch; and `<cache>` stands in for scratch
in the release directory's check, since scratch does not exist yet."""

from __future__ import annotations

import json
import os
import secrets
import select
import signal
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from autonomy.analyst.release import check_release_dir, release
from autonomy.analyst.toolchain import (
    ANALYST_TOOLS, AnalystRefused, PiInstall, check_node, check_pi, default_node_dir, default_pi_dir, epoch_record,
)
from autonomy.analyst.walk import walk
from autonomy.baseline import append_event, fsync_dir, utc_now, write_all
from autonomy.channel import LineChannel
from autonomy.egress.errors import EgressUnproven, RouteRefused
from autonomy.egress.helper import MODEL_URL
from autonomy.egress.route import LoadedRoute, egress_denied, load_route
from autonomy.egress.session import EGRESS_RECORDS, EgressClosed, EgressSession, _start_time, closing_line
from autonomy.run import LEASE_DEFAULT, LEASE_FLOOR, Diag, RunRefused, _home, _xdg
from autonomy.sandbox.bwrap import Sandboxed, launch, preflight, probe
from autonomy.sandbox.spec import SYSTEM_RO, SandboxSpec
from autonomy.sandbox.static import SandboxUnproven, check_binds, check_sources
from autonomy.stdio import ACTOR_FDS, StdioKind, StdioRefused, check_report_fd, check_stdio

EXIT_CLEAN, EXIT_REFUSED, EXIT_FINDINGS, EXIT_UNSTARTED = 0, 2, 3, 4
DEADLINE_DEFAULT = 3600.0
TERMINATE_GRACE = 10.0
RUN_ID_BYTES = 16
LAUNCHER_LOG = "launcher.log"
_HANDLED = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)


@dataclass(frozen=True)
class AnalystRequest:
    model_route: str
    model: str
    inputs: tuple[Path, ...]
    denied: tuple[Path, ...]
    release_dir: Path
    report_fd: int | None = None
    pi_dir: Path | None = None
    node_dir: Path | None = None
    lease: float = LEASE_DEFAULT
    deadline: float = DEADLINE_DEFAULT


@dataclass(frozen=True)
class Places:
    state: Path
    cache: Path
    config: Path


@dataclass(frozen=True)
class Prepared:
    places: Places
    route: LoadedRoute
    inputs: tuple[Path, ...]
    denied: tuple[Path, ...]
    release_dir: Path
    pi: PiInstall
    node_dir: Path
    stdio: tuple[StdioKind, StdioKind, StdioKind]


@dataclass
class Progress:
    """Set the moment step 2 has made the directories, for a caller that must account
    for a run when `execute` raises."""

    run_dir: Path | None = None
    scratch: Path | None = None


def pi_argv(pi: PiInstall, model: str, scratch: Path) -> list[str]:
    return [
        str(pi.executable), "--mode", "rpc", "--provider", "anthropic", "--model", model, "--thinking", "off",
        "--session-dir", str(scratch / "sessions"), "--no-approve", "--no-extensions", "--no-skills",
        "--no-prompt-templates", "--no-mcp", "--no-context-files", "--tools", ",".join(ANALYST_TOOLS),
    ]


def actor_env(node_dir: Path, scratch: Path) -> dict[str, str]:
    return {
        "PATH": f"{node_dir}/bin:/usr/bin", "HOME": str(scratch / "home"), "PI_CODING_AGENT_DIR": str(scratch / "agent"),
        "PI_OFFLINE": "1", "PI_TELEMETRY": "0", "LANG": "C.UTF-8", "VERIFIABLY_MODEL_URL": MODEL_URL,
    }


def places(env: Mapping[str, str]) -> Places:
    """§3 step 1's resolution for `<state>`, `<cache>` and `<config>`; `$XDG_RUNTIME_DIR`
    is not required, since the analyst opens no endpoint socket."""
    return Places(
        state=_xdg(env, "XDG_STATE_HOME", ".local", "state") / "verifiably-autonomy",
        cache=_xdg(env, "XDG_CACHE_HOME", ".cache") / "verifiably-autonomy",
        config=_xdg(env, "XDG_CONFIG_HOME", ".config") / "verifiably-autonomy",
    )


def _resolve_inputs(inputs: tuple[Path, ...], toolchain: tuple[Path, ...]) -> tuple[Path, ...]:
    resolved: list[Path] = []
    for given in inputs:
        try:
            real = Path(given).resolve(strict=True)
        except OSError as caught:
            raise AnalystRefused("input-missing", f"{given}: {caught}") from None
        if not real.is_dir():
            raise AnalystRefused("input-missing", f"{given}: not a directory")
        resolved.append(real)
    everything = [*resolved, *toolchain]
    for i, a in enumerate(everything):
        for b in everything[i + 1:]:
            if a == b or a.is_relative_to(b) or b.is_relative_to(a):
                if a in resolved or b in resolved:
                    raise AnalystRefused("input-nested", f"{a} and {b} nest; each admitted tree must stand alone")
    return tuple(resolved)


def _resolve_denied(denied: tuple[Path, ...]) -> tuple[Path, ...]:
    resolved: list[Path] = []
    for given in denied:
        real = Path(given).resolve(strict=False)
        try:
            os.lstat(real)
        except FileNotFoundError:
            pass
        except OSError as caught:
            raise AnalystRefused("denied-unreadable", f"{given}: a denied path must be stat-able: {caught}") from None
        resolved.append(real)
    return tuple(resolved)


def refuse(request: AnalystRequest, env: Mapping[str, str], *, actor_fds: tuple[int, int, int] = ACTOR_FDS) -> Prepared:
    """Decision 14 step 1: every configuration refusal, before anything exists."""
    if request.lease < LEASE_FLOOR:
        raise AnalystRefused("lease-below-floor", f"the lease is {request.lease:g} s; the floor is {LEASE_FLOOR:g} s")
    try:
        stdio = check_stdio(actor_fds)
        if request.report_fd is not None:
            check_report_fd(request.report_fd, actor_fds)
        where = places(env)
        loaded = load_route(where.config, request.model_route)
    except (StdioRefused, RunRefused, RouteRefused) as caught:
        raise AnalystRefused(caught.code, caught.message) from None
    operation = loaded.route.operation("POST", "/v1/messages", "beta=true")
    if operation is None or request.model not in operation.models:
        raise AnalystRefused("model-unrouted", f"route {request.model_route} does not allow model {request.model!r} on POST /v1/messages?beta=true")
    pi = check_pi(request.pi_dir if request.pi_dir is not None else default_pi_dir(env, _home(env)))
    node_dir = request.node_dir if request.node_dir is not None else default_node_dir(env)
    if node_dir is None:
        raise AnalystRefused("node-missing", "node is not on PATH; pass --node-dir or set NODE_DIR")
    node = check_node(node_dir)
    inputs = _resolve_inputs(request.inputs, (node, pi.dir))
    denied = (*_resolve_denied(request.denied), *egress_denied(where.config, loaded), where.state.resolve(strict=False))
    try:
        check_sources(inputs, denied)
    except SandboxUnproven as caught:
        raise AnalystRefused(caught.code, str(caught)) from None
    release_dir = check_release_dir(request.release_dir, forbidden=(*inputs, *denied, where.cache))
    return Prepared(where, loaded, inputs, (*denied, release_dir), release_dir, pi, node, stdio)


@dataclass(frozen=True)
class _Dirs:
    run_id: str
    run_dir: Path
    scratch: Path


def _allocate(where: Places) -> _Dirs:
    """Step 2: the run directory, scratch and its five subdirectories, each new, all or
    none (as `run.allocate`). A directory that cannot be made is `allocation-failed`."""
    run_id = secrets.token_hex(RUN_ID_BYTES)
    run_dir = where.state / "analyst" / run_id
    scratch_root = where.cache / "analyst" / run_id
    scratch = scratch_root / "scratch"
    made: list[Path] = []
    path = run_dir
    try:
        for path in (run_dir, scratch_root, scratch, *(scratch / name for name in ("agent", "agent/bin", "home", "sessions", "outputs"))):
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.mkdir(mode=0o700)
            made.append(path)
        return _Dirs(run_id, run_dir, scratch.resolve())
    except BaseException as caught:
        for created in reversed(made):
            created.rmdir()
        if isinstance(caught, OSError):
            raise AnalystRefused("allocation-failed", f"cannot make {path}: {caught}") from caught
        raise


def _write_json(path: Path, value: object) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        write_all(fd, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    fsync_dir(path.parent)


def _line(value: Mapping[str, object]) -> str:
    return json.dumps(value, separators=(",", ":"))


class _Log:
    """`launcher.log` in the run directory: every diagnostic after the launch, whatever
    became of the launcher's own fd 2."""

    def __init__(self, run_dir: Path) -> None:
        self.fd = os.open(run_dir / LAUNCHER_LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC, 0o600)

    def write(self, line: str) -> None:
        try:
            write_all(self.fd, f"{utc_now()} {line}\n".encode("utf-8", "replace"))
        except OSError:
            pass

    def close(self) -> None:
        os.close(self.fd)


def _take_stdio(log: _Log) -> None:
    """The CLI handed its own stdio to pi: fds 0 and 1 go to /dev/null and fd 2 to the log,
    as `autonomy run` does after its launch (decision 12)."""
    null = os.open(os.devnull, os.O_RDWR | os.O_CLOEXEC)
    try:
        os.dup2(null, 0)
        os.dup2(null, 1)
    finally:
        os.close(null)
    os.dup2(log.fd, 2)


def _supervise(actor: Sandboxed, session: EgressSession, request: AnalystRequest, log: _Log) -> int | None:
    """Step 5: renew the lease every lease/3 until the namespace's init exits, the
    deadline passes, a handled signal arrives, or the proxy exits on its own. Returns
    pi's exit status (bwrap's, which mirrors its child's), or None when it could not be
    collected."""
    stop: list[int] = []
    previous = {sig: signal.signal(sig, lambda signum, frame: stop.append(signum)) for sig in _HANDLED}
    try:
        started = renewed = time.monotonic()
        period = request.lease / 3
        while True:
            now = time.monotonic()
            if stop:
                log.write(f"signal {stop[0]}: terminating the analyst")
                return actor.terminate(grace=TERMINATE_GRACE)
            if now - started >= request.deadline:
                log.write(f"deadline of {request.deadline:g} s reached: terminating the analyst")
                return actor.terminate(grace=TERMINATE_GRACE)
            if session.exited():
                log.write("the proxy exited on its own: terminating the analyst")
                return actor.terminate(grace=TERMINATE_GRACE)
            if now - renewed >= period:
                try:
                    session.renew()
                except OSError as caught:
                    log.write(f"lease renewal failed: {caught}")
                renewed = now
            wait = min(1.0, max(0.0, period - (now - renewed)), max(0.0, request.deadline - (now - started)))
            if select.select([actor.pidfd], [], [], wait)[0]:
                break
        try:
            return actor.wait(timeout=TERMINATE_GRACE)
        except subprocess.TimeoutExpired:
            log.write("bwrap did not exit after its namespace died; killing it")
            actor.close()
            return None
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _close_route(session: EgressSession, run_dir: Path, log: _Log) -> EgressClosed:
    try:
        return session.close()
    except OSError as caught:  # the control socket's peer is gone: the proxy died or closed on its own
        log.write(f"the route's close could not be sent ({caught}); settling from its records")
        session.kill()
        line = closing_line(run_dir / EGRESS_RECORDS)
        return EgressClosed(None if line is None else line["closed"], None if line is None else line["last_seq"], False)


def execute(
    request: AnalystRequest,
    env: Mapping[str, str],
    *,
    diag: Diag,
    progress: Progress,
    actor_fds: tuple[int, int, int] = ACTOR_FDS,
    actor_argv: Callable[[PiInstall, str, Path], list[str]] = pi_argv,
) -> int:
    """Decision 14's six steps. `actor_argv` is the test hook that puts a shell actor in
    pi's place. After step 1 the report fd is closed on every way out, as `run.execute`
    does, so a caller reading it sees EOF."""
    prepared = refuse(request, env, actor_fds=actor_fds)
    report: LineChannel | None = None
    log: _Log | None = None
    try:
        if request.report_fd is not None:
            report = LineChannel(request.report_fd)
        dirs = _allocate(prepared.places)
        progress.run_dir, progress.scratch = dirs.run_dir, dirs.scratch
        run_dir, scratch = dirs.run_dir, dirs.scratch
        diag(f"analyst run {dirs.run_id} in {run_dir}")
        _write_json(scratch / "agent/models.json", {"providers": {"anthropic": {"baseUrl": MODEL_URL, "apiKey": "placeholder"}}})
        _write_json(run_dir / "epoch.json", epoch_record(prepared.pi, prepared.node_dir))
        append_event(run_dir, "allocated", run=dirs.run_id, scratch=str(scratch), release=str(prepared.release_dir),
                     inputs=[str(p) for p in prepared.inputs], denied=[str(p) for p in prepared.denied])
        if report is not None and not report.write_line(_line({"run": dirs.run_id, "run_dir": str(run_dir), "scratch": str(scratch)})):
            append_event(run_dir, "report-unwritten", line="run")
        spec = SandboxSpec(scratch=scratch, ro_binds=(prepared.node_dir, prepared.pi.dir, *prepared.inputs),
                           env=actor_env(prepared.node_dir, scratch))
        denied = prepared.denied
        try:
            preflight()
            check_binds(spec, denied)
            walked = walk(user_trees=[prepared.node_dir, prepared.pi.dir, *prepared.inputs], system_trees=list(SYSTEM_RO), denied=denied)
            _write_json(run_dir / "walk.json", walked.to_json())
            probe(spec, denied)
        except SandboxUnproven as caught:
            append_event(run_dir, "unproven", code=caught.code, path=caught.path, message=str(caught))
            diag(f"analyst run {dirs.run_id} never started: {caught}")
            return EXIT_UNSTARTED
        append_event(run_dir, "proved", walk_seconds=walked.seconds)
        try:
            session = EgressSession.start(prepared.route, run_dir, lease=request.lease, denied=denied)
        except EgressUnproven as caught:
            append_event(run_dir, "unproven", code=caught.code, path="proxy", message=caught.message)
            diag(f"analyst run {dirs.run_id} never started: {caught}")
            return EXIT_UNSTARTED
        append_event(run_dir, "proxy", pid=session.init_pid)
        try:
            actor = launch(spec, actor_argv(prepared.pi, request.model, scratch), stdin=actor_fds[0], stdout=actor_fds[1],
                           stderr=actor_fds[2], before_release=session.attach)
        except (SandboxUnproven, EgressUnproven) as caught:
            session.kill()
            code = caught.code
            append_event(run_dir, "unproven", code=code, path="launch", message=str(caught))
            diag(f"analyst run {dirs.run_id} never started: {caught}")
            return EXIT_UNSTARTED
        route_closed = False
        try:  # from here the actor and the proxy are live: every way out kills what is still up
            try:
                start_time: int | None = _start_time(actor.child_pid)
            except OSError:  # an actor that exited at once: its init is already reaped
                start_time = None
            append_event(run_dir, "launched", child_pid=actor.child_pid, start_time=start_time)
            log = _Log(run_dir)
            log.write(f"launched pi as namespace init {actor.child_pid}")
            if tuple(actor_fds) == ACTOR_FDS:
                _take_stdio(log)
            pi_exit = _supervise(actor, session, request, log)
            closed = _close_route(session, run_dir, log)
            route_closed = True
        finally:
            actor.close()
            if not route_closed:
                try:
                    session.kill()
                except Exception:  # noqa: BLE001 - the original exception is what matters
                    pass
        released = release(scratch / "outputs", prepared.release_dir)
        _write_json(run_dir / "release.json", released.to_json())
        findings = pi_exit != 0 or closed.cause != "close" or bool(closed.findings()) or bool(released.refused)
        code = EXIT_FINDINGS if findings else EXIT_CLEAN
        append_event(run_dir, "closed", pi_exit=pi_exit, egress=closed.cause, released=len(released.released),
                     refused=len(released.refused), exit=code)
        closing = _line({"run": dirs.run_id, "exit": code, "pi_exit": pi_exit, "egress": closed.cause,
                         "released": len(released.released), "refused": len(released.refused)})
        if report is not None and not report.write_line(closing):
            append_event(run_dir, "report-unwritten", line="closing")
        log.write(f"closed: {closing}")
        diag(f"analyst run {dirs.run_id} closed with exit {code}")
        return code
    finally:
        if log is not None:
            log.close()
        if report is not None:
            report.close()
        if request.report_fd is not None:
            os.close(request.report_fd)
