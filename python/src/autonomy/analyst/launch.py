"""`autonomy analyst` (envelope design decision 14): a fresh pi analyst under the sandbox,
with caller-declared read-only inputs, extra denied paths and one output directory,
composed from Plan B1's launch path and the egress plan, with no endpoint.

Step 1 refuses on configuration before anything exists. Two calls of the implementer's:
an input that is itself a denied path is refused here as `bind-overlaps-denied` (the
static check's code), cheaper than a doomed launch; and `<cache>` stands in for scratch
in the release directory's check, since scratch does not exist yet."""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import select
import signal
import stat
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from autonomy.analyst.release import check_release_dir, release
from autonomy.analyst.toolchain import (
    ANALYST_TOOLS, AnalystRefused, PiInstall, bwrap_info, check_node, check_pi, check_thinking, default_node_dir,
    default_pi_dir, epoch_record,
)
from autonomy.analyst.walk import walk
from autonomy.baseline import append_event, fsync_dir, utc_now, write_all
from autonomy.channel import LineChannel
from autonomy.egress.errors import EgressUnproven, RouteRefused
from autonomy.egress.helper import MODEL_URL
from autonomy.egress.route import LoadedRoute, all_egress_denied, egress_denied, load_route
from autonomy.egress.session import EGRESS_RECORDS, EgressClosed, EgressSession, _start_time, closing_line
from autonomy.run import LEASE_DEFAULT, LEASE_FLOOR, Diag, RunRefused, _home, _xdg
from autonomy.sandbox.bwrap import Sandboxed, launch, preflight, probe
from autonomy.sandbox.spec import SYSTEM_LINKS, SYSTEM_RO, SandboxSpec
from autonomy.sandbox.static import SandboxUnproven, check_binds, check_recreated_links, check_sources
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
    thinking: str
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


def pi_argv(pi: PiInstall, model: str, thinking: str, scratch: Path) -> list[str]:
    return [
        str(pi.executable), "--mode", "rpc", "--provider", "anthropic", "--model", model, "--thinking", thinking,
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
    check_thinking(pi, request.model, request.thinking)
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
    actor_argv: Callable[[PiInstall, str, str, Path], list[str]] = pi_argv,
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
        _write_json(
            run_dir / "epoch.json",
            epoch_record(prepared.pi, prepared.node_dir, model=request.model, thinking=request.thinking),
        )
        append_event(run_dir, "allocated", run=dirs.run_id, model_route=request.model_route, model=request.model,
                     thinking=request.thinking, scratch=str(scratch), release=str(prepared.release_dir),
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
            actor = launch(spec, actor_argv(prepared.pi, request.model, request.thinking, scratch), stdin=actor_fds[0],
                           stdout=actor_fds[1], stderr=actor_fds[2], before_release=session.attach)
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
            append_event(run_dir, "launched", child_pid=actor.child_pid, start_time=start_time, model=request.model,
                         thinking=request.thinking)
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


@dataclass(frozen=True)
class CommandRequest:
    inputs: tuple[Path, ...]
    denied: tuple[Path, ...]
    release_dir: Path
    argv: tuple[str, ...]
    workdir: Path | None = None
    report_fd: int | None = None
    deadline: float = DEADLINE_DEFAULT


@dataclass(frozen=True)
class CommandPrepared:
    places: Places
    inputs: tuple[Path, ...]
    input_kinds: tuple[str, ...]
    denied: tuple[Path, ...]
    release_dir: Path
    argv: tuple[str, ...]
    executable_path: Path
    executable_realpath: Path
    executable_sha256: str
    workdir: Path | None
    symlinks: tuple[tuple[Path, Path], ...]
    report_fd: int | None
    deadline: float
    bwrap: dict[str, str | None]


def command_env(scratch: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/bin",
        "HOME": str(scratch / "home"),
        "LANG": "C.UTF-8",
        "VERIFIABLY_OUTPUTS": str(scratch / "outputs"),
    }


def _under_any(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def _resolve_command_inputs(inputs: tuple[Path, ...]) -> tuple[tuple[Path, ...], tuple[str, ...]]:
    if not inputs:
        raise AnalystRefused("input-missing", "at least one --input is required")
    resolved: list[Path] = []
    kinds: list[str] = []
    for given in inputs:
        try:
            real = Path(given).resolve(strict=True)
            info = os.stat(real)
        except OSError as caught:
            raise AnalystRefused("input-missing", f"{given}: {caught}") from None
        if stat.S_ISDIR(info.st_mode):
            kinds.append("directory")
        elif stat.S_ISREG(info.st_mode):
            kinds.append("file")
        else:
            raise AnalystRefused("input-unsupported", f"{given}: must be a regular file or directory")
        resolved.append(real)
    for i, a in enumerate(resolved):
        for sys_ro in SYSTEM_RO:
            if a == sys_ro or a.is_relative_to(sys_ro) or sys_ro.is_relative_to(a):
                raise AnalystRefused("input-nested", f"{a} overlaps system tree {sys_ro}")
        for b in resolved[i + 1:]:
            if a == b or a.is_relative_to(b) or b.is_relative_to(a):
                raise AnalystRefused("input-nested", f"{a} and {b} nest; each admitted input must stand alone")
    return tuple(resolved), tuple(kinds)


def _discover_command_symlinks(
    cmd_path: Path, inputs: tuple[Path, ...], input_kinds: tuple[str, ...]
) -> tuple[tuple[Path, Path], ...]:
    dir_inputs = tuple(inp for inp, kind in zip(inputs, input_kinds) if kind == "directory")
    admitted_dirs = (Path("/usr"), *dir_inputs)
    system_link_paths = set(SYSTEM_LINKS)

    candidates: list[Path] = []
    seen_hops: set[Path] = set()
    cur = cmd_path
    while cur.is_symlink() and cur not in seen_hops:
        seen_hops.add(cur)
        target = Path(os.readlink(cur))
        hop = target if target.is_absolute() else Path(os.path.normpath(cur.parent / target))
        candidates.append(hop)
        cur = hop

    venv_root = cmd_path.parent.parent
    if _under_any(venv_root, dir_inputs):
        cfg = venv_root / "pyvenv.cfg"
        try:
            if cfg.is_file() and not cfg.is_symlink():
                for line in cfg.read_text(errors="replace").splitlines():
                    key, sep, val = line.partition("=")
                    if sep and key.strip() == "home":
                        home_path = Path(val.strip())
                        if home_path.is_absolute():
                            candidates.append(home_path)
        except OSError:
            pass

    discovered: list[tuple[Path, Path]] = []
    for cand in candidates:
        prefixes = [*reversed(cand.parents)][1:] + [cand]
        for prefix in prefixes:
            if not prefix.is_symlink() or str(prefix) in system_link_paths:
                continue
            try:
                resolved_target = prefix.resolve(strict=True)
            except OSError as caught:
                raise AnalystRefused("command-missing", f"{prefix}: {caught}") from None
            if not resolved_target.is_dir():
                continue
            if not _under_any(resolved_target, admitted_dirs):
                raise AnalystRefused(
                    "command-unbound",
                    f"recreated directory symlink {prefix} targets {resolved_target} outside /usr and declared directory inputs",
                )
            try:
                parent_real = prefix.parent.resolve(strict=True)
            except OSError as caught:
                raise AnalystRefused("command-invalid", f"{prefix.parent}: {caught}") from None
            if prefix.parent != parent_real:
                raise AnalystRefused("command-invalid", f"recreated symlink {prefix} has a symlinked parent")
            if _under_any(prefix.parent, (*SYSTEM_RO, *inputs)):
                raise AnalystRefused(
                    "command-invalid", f"recreated symlink {prefix} lies inside a read-only bind {prefix.parent}"
                )
            pair = (resolved_target, prefix)
            if pair not in discovered:
                discovered.append(pair)
            break
    return tuple(discovered)


def refuse_command(
    request: CommandRequest, env: Mapping[str, str], *, stdio_fds: tuple[int, int, int] = ACTOR_FDS
) -> CommandPrepared:
    """Decision 14 `autonomy command` step 1: every configuration refusal before anything exists."""
    if not (math.isfinite(request.deadline) and request.deadline > 0):
        raise AnalystRefused("deadline-invalid", f"the deadline {request.deadline!r} must be a finite positive number")
    try:
        if request.report_fd is not None:
            check_report_fd(request.report_fd, stdio_fds)
        where = places(env)
    except (StdioRefused, RunRefused) as caught:
        raise AnalystRefused(caught.code, caught.message) from None

    inputs, input_kinds = _resolve_command_inputs(request.inputs)

    workdir: Path | None = None
    if request.workdir is not None:
        try:
            workdir = Path(request.workdir).resolve(strict=True)
        except OSError as caught:
            raise AnalystRefused("workdir-invalid", f"{request.workdir}: {caught}") from None
        if not workdir.is_dir():
            raise AnalystRefused("workdir-invalid", f"{request.workdir}: not a directory")
        dir_inputs = tuple(inp for inp, kind in zip(inputs, input_kinds) if kind == "directory")
        if not _under_any(workdir, dir_inputs):
            raise AnalystRefused("workdir-unbound", f"{workdir} is not inside any declared directory --input")

    if not request.argv or not request.argv[0]:
        raise AnalystRefused("command-missing", "a command executable is required after --")
    raw_cmd = request.argv[0]
    if (
        not raw_cmd.startswith("/")
        or raw_cmd.endswith("/")
        or any(seg in ("", ".", "..") for seg in raw_cmd.split("/")[1:])
    ):
        raise AnalystRefused("command-invalid", f"{raw_cmd!r} must be a normalized absolute path")
    cmd_path = Path(raw_cmd)
    try:
        parent_real = cmd_path.parent.resolve(strict=True)
    except OSError as caught:
        raise AnalystRefused("command-invalid", f"{cmd_path.parent}: {caught}") from None
    if cmd_path.parent != parent_real:
        raise AnalystRefused("command-invalid", f"{cmd_path}'s parent directory contains a symlink")
    if not os.path.lexists(cmd_path):
        raise AnalystRefused("command-missing", f"{cmd_path} does not exist")
    try:
        real_cmd = cmd_path.resolve(strict=True)
    except OSError as caught:
        raise AnalystRefused("command-missing", f"{cmd_path}: {caught}") from None
    if not real_cmd.is_file():
        raise AnalystRefused("command-missing", f"{real_cmd} is not a regular file")
    if not os.access(real_cmd, os.X_OK):
        raise AnalystRefused("command-not-executable", f"{real_cmd} is not executable")

    admitted_real = (Path("/usr"), *inputs)
    merged_links = tuple(Path(link) for link in SYSTEM_LINKS if Path(link).is_symlink())
    admitted_cmd = (*admitted_real, *merged_links)
    if not _under_any(cmd_path, admitted_cmd) or not _under_any(real_cmd, admitted_real):
        raise AnalystRefused(
            "command-unbound", f"{cmd_path} (resolving to {real_cmd}) must lie under /usr or a declared --input"
        )

    symlinks = _discover_command_symlinks(cmd_path, inputs, input_kinds)
    try:
        executable_sha256 = hashlib.sha256(real_cmd.read_bytes()).hexdigest()
    except OSError as caught:
        raise AnalystRefused("command-missing", f"{real_cmd}: {caught}") from None

    non_release_denied = _resolve_denied(
        tuple(dict.fromkeys([*_resolve_denied(request.denied), *all_egress_denied(where.config), where.state.resolve(strict=False)]))
    )
    try:
        check_sources((*inputs, *SYSTEM_RO), non_release_denied)
        check_recreated_links(tuple(link for _, link in symlinks), non_release_denied)
    except SandboxUnproven as caught:
        raise AnalystRefused(caught.code, str(caught)) from None

    release_dir = check_release_dir(request.release_dir, forbidden=(*inputs, *non_release_denied, where.cache))
    denied = (*non_release_denied, release_dir)
    try:
        check_sources((*inputs, *SYSTEM_RO), denied)
        check_recreated_links(tuple(link for _, link in symlinks), denied)
    except SandboxUnproven as caught:
        raise AnalystRefused(caught.code, str(caught)) from None

    return CommandPrepared(
        places=where,
        inputs=inputs,
        input_kinds=input_kinds,
        denied=denied,
        release_dir=release_dir,
        argv=tuple(request.argv),
        executable_path=cmd_path,
        executable_realpath=real_cmd,
        executable_sha256=executable_sha256,
        workdir=workdir,
        symlinks=symlinks,
        report_fd=request.report_fd,
        deadline=request.deadline,
        bwrap=bwrap_info(),
    )


def _allocate_command(where: Places) -> _Dirs:
    """Step 2 for `autonomy command`: `<state>/command/<run-id>/` and `<cache>/command/<run-id>/scratch/`
    with `home/` and `outputs/`."""
    run_id = secrets.token_hex(RUN_ID_BYTES)
    run_dir = where.state / "command" / run_id
    scratch_root = where.cache / "command" / run_id
    scratch = scratch_root / "scratch"
    made: list[Path] = []
    path = run_dir
    try:
        for path in (run_dir, scratch_root, scratch, scratch / "home", scratch / "outputs"):
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


def _replace_json(path: Path, value: object) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        write_all(fd, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    fsync_dir(path.parent)


def _hash_log_file(run_dir: Path, name: str) -> dict[str, object]:
    data = (run_dir / name).read_bytes()
    return {
        "path": name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _supervise_command(actor: Sandboxed, deadline: float, log: _Log) -> tuple[int | None, bool, int | None]:
    """Step 4 supervision for `autonomy command`: wait on `actor.pidfd` until exit, deadline,
    or handled signal (`SIGTERM`, `SIGINT`, `SIGHUP`)."""
    stop: list[int] = []
    previous = {sig: signal.signal(sig, lambda signum, frame: stop.append(signum)) for sig in _HANDLED}
    try:
        started = time.monotonic()
        while True:
            now = time.monotonic()
            if stop:
                sig = stop[0]
                log.write(f"signal {sig}: terminating the command")
                return actor.terminate(grace=TERMINATE_GRACE), False, sig
            if now - started >= deadline:
                log.write(f"deadline of {deadline:g} s reached: terminating the command")
                return actor.terminate(grace=TERMINATE_GRACE), True, None
            wait = min(1.0, max(0.0, deadline - (now - started)))
            if select.select([actor.pidfd], [], [], wait)[0]:
                break
        try:
            status = actor.wait(timeout=TERMINATE_GRACE)
        except subprocess.TimeoutExpired:
            log.write("bwrap did not exit after its namespace died; killing it")
            actor.close()
            return None, False, None
        signal_num = (
            -status
            if status is not None and status < 0
            else (status - 128 if status is not None and status > 128 else None)
        )
        return status, False, signal_num
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def execute_command(
    request: CommandRequest,
    env: Mapping[str, str],
    *,
    diag: Diag,
    progress: Progress,
    stdio_fds: tuple[int, int, int] = ACTOR_FDS,
    take_stdio: bool = False,
) -> int:
    """Decision 14 `autonomy command` steps 1–5."""
    prepared = refuse_command(request, env, stdio_fds=stdio_fds)
    report: LineChannel | None = None
    log: _Log | None = None
    try:
        if request.report_fd is not None:
            report = LineChannel(request.report_fd)
        dirs = _allocate_command(prepared.places)
        progress.run_dir, progress.scratch = dirs.run_dir, dirs.scratch
        run_dir, scratch = dirs.run_dir, dirs.scratch
        diag(f"command run {dirs.run_id} in {run_dir}")
        workdir = prepared.workdir or scratch
        argv_list = list(prepared.argv)
        argv_sha256 = hashlib.sha256(json.dumps(argv_list, separators=(",", ":")).encode("utf-8")).hexdigest()
        epoch_doc: dict[str, object] = {
            "inputs": [
                {"path": str(p), "kind": k, "sha256": None, "files": None, "bytes": None}
                for p, k in zip(prepared.inputs, prepared.input_kinds)
            ],
            "argv": argv_list,
            "argv_sha256": argv_sha256,
            "executable": {
                "path": str(prepared.executable_path),
                "realpath": str(prepared.executable_realpath),
                "sha256": prepared.executable_sha256,
            },
            "workdir": str(workdir),
            "bwrap": prepared.bwrap,
        }
        _write_json(run_dir / "epoch.json", epoch_doc)
        append_event(
            run_dir,
            "allocated",
            run=dirs.run_id,
            scratch=str(scratch),
            release=str(prepared.release_dir),
            workdir=str(workdir),
            inputs=[str(p) for p in prepared.inputs],
            denied=[str(p) for p in prepared.denied],
            argv=argv_list,
            executable=epoch_doc["executable"],
        )
        if report is not None and not report.write_line(
            _line({"run": dirs.run_id, "run_dir": str(run_dir), "scratch": str(scratch)})
        ):
            append_event(run_dir, "report-unwritten", line="run")
        spec = SandboxSpec(
            scratch=scratch,
            ro_binds=prepared.inputs,
            symlinks=prepared.symlinks,
            chdir=workdir,
            outputs_link=True,
            env=command_env(scratch),
        )
        denied = prepared.denied
        try:
            preflight()
            check_binds(spec, denied)
            walked = walk(
                user_trees=list(prepared.inputs),
                system_trees=list(SYSTEM_RO),
                denied=denied,
                digest_inputs=list(prepared.inputs),
            )
            _write_json(run_dir / "walk.json", walked.to_json())
            epoch_doc = {**epoch_doc, "inputs": [d.to_json() for d in walked.inputs]}
            _replace_json(run_dir / "epoch.json", epoch_doc)
            probe(spec, denied)
        except SandboxUnproven as caught:
            append_event(run_dir, "unproven", code=caught.code, path=caught.path, message=str(caught))
            diag(f"command run {dirs.run_id} never started: {caught}")
            return EXIT_UNSTARTED
        append_event(run_dir, "proved", walk_seconds=walked.seconds)

        null_fd = os.open(os.devnull, os.O_RDONLY | os.O_CLOEXEC)
        out_fd = os.open(run_dir / "stdout.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        err_fd = os.open(run_dir / "stderr.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        try:
            try:
                actor = launch(spec, argv_list, stdin=null_fd, stdout=out_fd, stderr=err_fd)
            except SandboxUnproven as caught:
                append_event(run_dir, "unproven", code=caught.code, path="launch", message=str(caught))
                diag(f"command run {dirs.run_id} never started: {caught}")
                return EXIT_UNSTARTED
        finally:
            os.close(null_fd)
            os.close(out_fd)
            os.close(err_fd)

        try:  # from here the command namespace is live: every way out kills and reaps it
            try:
                start_time: int | None = _start_time(actor.child_pid)
            except OSError:
                start_time = None
            append_event(run_dir, "launched", child_pid=actor.child_pid, start_time=start_time, argv=argv_list)
            log = _Log(run_dir)
            log.write(f"launched command as namespace init {actor.child_pid}")
            if take_stdio:
                _take_stdio(log)
            command_exit, timed_out, signal_num = _supervise_command(actor, prepared.deadline, log)
        finally:
            actor.close()

        released = release(scratch / "outputs", prepared.release_dir)
        _write_json(run_dir / "release.json", released.to_json())
        stdout_info = _hash_log_file(run_dir, "stdout.log")
        stderr_info = _hash_log_file(run_dir, "stderr.log")
        findings = command_exit != 0 or timed_out or signal_num is not None or bool(released.refused)
        code = EXIT_FINDINGS if findings else EXIT_CLEAN
        append_event(
            run_dir,
            "closed",
            command_exit=command_exit,
            timed_out=timed_out,
            signal=signal_num,
            stdout=stdout_info,
            stderr=stderr_info,
            released=len(released.released),
            refused=len(released.refused),
            exit=code,
        )
        closing = _line(
            {
                "run": dirs.run_id,
                "exit": code,
                "command_exit": command_exit,
                "released": len(released.released),
                "refused": len(released.refused),
            }
        )
        if report is not None and not report.write_line(closing):
            append_event(run_dir, "report-unwritten", line="closing")
        log.write(f"closed: {closing}")
        diag(f"command run {dirs.run_id} closed with exit {code}")
        return code
    finally:
        if log is not None:
            log.close()
        if report is not None:
            report.close()
        if request.report_fd is not None:
            os.close(request.report_fd)

