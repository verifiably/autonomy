"""Allocate runs and publish their reports and terminal dispositions."""

from __future__ import annotations

import json
import os
import pwd
import re
import secrets
import signal
import stat
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

from autonomy.baseline import append_event, decode_object, fsync_dir, publish_bytes, read_private_bytes, utc_now
from autonomy.channel import LineChannel
from autonomy.closing import SEVERITY, Disposition, disposition_of
from autonomy.egress.errors import RouteRefused
from autonomy.egress.route import LoadedRoute, load_route
from autonomy.membership import Finding
from autonomy.stdio import ACTOR_FDS, StdioKind, StdioRefused, check_report_fd, check_stdio
from autonomy.tiers import Tier

LEASE_FLOOR = 10.0
LEASE_DEFAULT = 60.0
DEADLINE_DEFAULT = 3600.0
EXIT_REFUSED = 2
EXIT_CODES: Mapping[Disposition, int] = MappingProxyType({"clean": 0, "quarantined": 3, "unwired": 4})
DISPOSITION = "disposition.json"

Diag = Callable[[str], None]


class RunRefused(Exception):
    """A configuration refusal at step 2, or a failed allocation at step 1: exit 2,
    and no run directory."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RunRequest:
    tier: Tier
    lease: float
    report_fd: int | None
    actor_argv: tuple[str, ...]
    model_route: str | None = None
    deadline: float = DEADLINE_DEFAULT
    toolchain: tuple[Path, ...] = ()


@dataclass(frozen=True)
class Places:
    state: Path
    cache: Path
    runtime: Path
    config: Path


def _absolute(value: str) -> Path | None:
    """An absolute path, or None for an unset, empty or relative value, which the XDG
    base directory spec calls invalid and ignores."""
    return Path(value) if value and Path(value).is_absolute() else None


def _home(env: Mapping[str, str]) -> Path:
    """HOME when it is absolute, else the passwd entry's home directory, else a refusal."""
    home = _absolute(env.get("HOME", ""))
    if home is not None:
        return home
    uid = os.getuid()
    try:
        entry = pwd.getpwuid(uid).pw_dir
    except KeyError:
        raise RunRefused("home-unknown", f"HOME is not an absolute path and uid {uid} has no passwd entry") from None
    home = _absolute(entry)
    if home is None:
        raise RunRefused("home-unknown", f"HOME is not an absolute path and uid {uid}'s passwd home {entry!r} is not either")
    return home


def _xdg(env: Mapping[str, str], name: str, *default: str) -> Path:
    """`name` when it is absolute, else `default` under the home directory, which is
    looked up only then."""
    return _absolute(env.get(name, "")) or _home(env).joinpath(*default)


def state_root(env: Mapping[str, str]) -> Path:
    return _xdg(env, "XDG_STATE_HOME", ".local", "state") / "verifiably-autonomy"


def places(env: Mapping[str, str]) -> Places:
    runtime = _absolute(env.get("XDG_RUNTIME_DIR", ""))
    if runtime is None:
        raise RunRefused(
            "runtime-dir-unset", "XDG_RUNTIME_DIR must name an absolute directory: the endpoint's socket lives there"
        )
    return Places(
        state=state_root(env),
        cache=_xdg(env, "XDG_CACHE_HOME", ".cache") / "verifiably-autonomy",
        runtime=runtime,
        config=_xdg(env, "XDG_CONFIG_HOME", ".config") / "verifiably-autonomy",
    )


@dataclass(frozen=True)
class RunDirs:
    run_id: str
    run_dir: Path
    scratch: Path
    socket_dir: Path


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError(f"{path} must be a private directory owned by the current user (0700)")


def ensure_run_parents(where: Places) -> None:
    path = where.runtime
    try:
        if not path.is_dir():
            raise ValueError(f"{path} must be a directory")
        for path in (where.runtime / "va", where.state, where.cache, where.state / "runs", where.cache / "scratch"):
            path.parent.mkdir(parents=True, exist_ok=True)
            _private_directory(path)
    except (OSError, ValueError) as caught:
        raise RunRefused("allocation-failed", f"cannot prepare {path}: {caught}") from caught


@contextmanager
def _hold_stop_signals() -> Iterator[None]:
    state = signal.pthread_sigmask(signal.SIG_BLOCK, (signal.SIGINT, signal.SIGTERM, signal.SIGHUP))
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, state)


def allocate(where: Places, *, progress: Progress | None = None) -> RunDirs:
    """Step 1. The socket directory's name is the run id's first 12 hex digits, short
    because of the 107-byte AF_UNIX path limit. Each directory is new: a collision
    fails rather than sharing one.

    All three directories or none: if this call raises, it has first removed the ones
    it made (their parents, shared by every run, stay). A directory that cannot be
    made is refused `allocation-failed`, so the run exits 2 with no run directory.
    Should a removal itself fail, its error propagates instead."""
    ensure_run_parents(where)
    run_id = secrets.token_hex(16)
    run_dir = where.state / "runs" / run_id
    scratch = where.cache / "scratch" / run_id
    socket_dir = where.runtime / "va" / run_id[:12]
    made: list[Path] = []
    path = run_dir
    try:
        for path in (run_dir, scratch, socket_dir):
            with _hold_stop_signals():
                path.mkdir(mode=0o700)
                made.append(path)
        with _hold_stop_signals():
            dirs = RunDirs(run_id, run_dir, scratch.resolve(), socket_dir)
            if progress is not None:
                progress.dirs = dirs
        return dirs
    except BaseException as caught:
        if progress is not None:
            progress.dirs = None
        for created in reversed(made):
            created.rmdir()
        if isinstance(caught, OSError):
            raise RunRefused("allocation-failed", f"cannot make {path}: {caught}") from caught
        raise


def refuse(request: RunRequest, *, actor_fds: tuple[int, int, int] = ACTOR_FDS) -> tuple[StdioKind, StdioKind, StdioKind]:
    """Step 2's checks that need no world. The tier is refused when it is built; the
    write-corpus and orphaned-run checks need science's reads."""
    if request.lease < LEASE_FLOOR:
        raise RunRefused("lease-below-floor", f"the lease is {request.lease:g} s; the floor is {LEASE_FLOOR:g} s")
    return check_run_stdio(request.report_fd, actor_fds)


def check_run_stdio(report_fd: int | None, actor_fds: tuple[int, int, int]) -> tuple[StdioKind, StdioKind, StdioKind]:
    try:
        kinds = check_stdio(actor_fds)
        if report_fd is not None:
            check_report_fd(report_fd, actor_fds)
    except StdioRefused as caught:
        raise RunRefused(caught.code, caught.message) from None
    return kinds


@dataclass
class Progress:
    """Retained run and durable disposition checkpoints for unexpected errors."""

    dirs: RunDirs | None = None
    durable_exit: int | None = None


@dataclass
class DevelopmentProgress:
    """Retained run and verdict checkpoints for the CLI's unexpected-error path."""

    run_dir: Path | None = None
    durable_exit: int | None = None


@dataclass(frozen=True)
class Opened:
    request: RunRequest
    dirs: RunDirs
    stdio: tuple[StdioKind, StdioKind, StdioKind]
    places: Places
    route: LoadedRoute | None


RunOpener = Callable[[Places, LoadedRoute | None, Progress], AbstractContextManager[RunDirs]]


@contextmanager
def _open_local(where: Places, _route: LoadedRoute | None, progress: Progress) -> Iterator[RunDirs]:
    yield allocate(where, progress=progress)


@dataclass(frozen=True)
class RunResult:
    findings: tuple[Finding, ...]
    members: Mapping[str, Sequence[str]]
    closing_heads: Mapping[str, object] | None


Steps = Callable[[Opened], Sequence[Finding] | RunResult]
"""Steps 3 to 9 and the close's seal and check: everything between the report fd's
first line and `disposition.json`. Returns the run's findings."""


def write_disposition(
    run_dir: Path, run_id: str, disposition: Disposition, findings: Sequence[Finding], *,
    members: Mapping[str, Sequence[str]] | None = None, closing_heads: Mapping[str, object] | None = None,
) -> None:
    """Published once and atomically, before the closing line. The record is written
    and fsynced under a temporary name in the run directory, then hard-linked to its
    final name: `link` refuses a name that exists, so a disposition is never replaced.
    The contract is absent before publication, complete after it. An interruption
    before the link leaves no `disposition.json`, and a retry succeeds. An interruption
    after the link (at the final directory fsync) leaves a complete `disposition.json`,
    and a retry raises `FileExistsError`. A writer killed outright before the link
    leaves only its temporary behind. The directory is fsynced last."""
    record = {
        "version": 1,
        "run": run_id,
        "disposition": disposition,
        "findings": [{"code": f.code, "ref": f.ref, "message": f.message} for f in findings],
        "closed_at": utc_now(),
        "members": dict(members) if members is not None else {},
        "closing_heads": dict(closing_heads) if closing_heads is not None else None,
    }
    publish_bytes(run_dir / DISPOSITION, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def read_disposition(run_dir: Path) -> tuple[bytes, int] | None:
    """Read and validate a published science receipt before relying on it."""
    def check_digest(value: object, length: int) -> None:
        if not isinstance(value, str) or re.fullmatch(f"[0-9a-f]{{{length}}}", value) is None:
            raise ValueError("invalid science receipt identity")

    try:
        raw = read_private_bytes(run_dir / DISPOSITION)
    except FileNotFoundError:
        return None
    doc = decode_object(raw)
    if (set(doc) != {"version", "run", "disposition", "findings", "closed_at", "members", "closing_heads"}
            or type(doc["version"]) is not int or doc["version"] != 1 or doc["run"] != run_dir.name
            or not isinstance(doc["members"], dict) or not isinstance(doc["findings"], list)):
        raise ValueError("invalid stored science disposition")
    stamp = doc["closed_at"]
    if not isinstance(stamp, str) or datetime.fromisoformat(stamp.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("invalid stored science disposition timestamp")
    for chain_id, entries in doc["members"].items():
        check_digest(chain_id, 32)
        if not isinstance(entries, list) or len(set(entries)) != len(entries):
            raise ValueError("invalid terminal chain members")
        for digest in entries:
            check_digest(digest, 64)
    heads = doc["closing_heads"]
    if heads is not None:
        if not isinstance(heads, dict) or set(heads) != {"world", "written", "mounts"}:
            raise ValueError("invalid terminal closing heads")
        if heads["world"] is not None:
            check_digest(heads["world"], 64)
        for entries in (heads["written"], heads["mounts"]):
            if not isinstance(entries, dict):
                raise ValueError("invalid terminal chain heads")
            for chain_id, tip in entries.items():
                check_digest(chain_id, 32)
                check_digest(tip, 64)
    findings = []
    for row in doc["findings"]:
        if (not isinstance(row, dict) or set(row) != {"code", "ref", "message"}
                or not all(isinstance(item, str) for item in row.values()) or row["code"] not in SEVERITY):
            raise ValueError("invalid stored finding")
        findings.append(Finding(row["code"], row["ref"], row["message"]))
    if doc["disposition"] != disposition_of(findings):
        raise ValueError("stored disposition disagrees with its findings")
    fsync_dir(run_dir)
    return raw, EXIT_CODES[doc["disposition"]]



def _route(name: str | None, where: Places) -> LoadedRoute | None:
    """Step 2's route refusals: before anything exists, so a refusal
    leaves no run directory and writes nothing on the report fd."""
    if name is None:
        return None
    try:
        return load_route(where.config, name)
    except RouteRefused as caught:
        raise RunRefused(caught.code, caught.message) from None


def _line(value: Mapping[str, object]) -> str:
    return json.dumps(value, separators=(",", ":"))


def execute(
    request: RunRequest,
    env: Mapping[str, str],
    steps: Steps,
    *,
    diag: Diag,
    progress: Progress,
    actor_fds: tuple[int, int, int] = ACTOR_FDS,
    open_run: RunOpener = _open_local,
) -> int:
    """Refuse, allocate, report the run, run `steps`, then close: `disposition.json`,
    the closing line, the exit code.

    Step 2 (`refuse`, `places` and the model route) raises before anything exists, `RunRefused` or an
    error it did not expect, and leaves the report fd open and unwritten for the
    process's exit to close. From there on the report fd is closed on every way out:
    a return, a refused allocation (`RunRefused`, nothing written and nothing kept),
    or any exception, which propagates with `progress.dirs` telling whether a run
    directory exists."""
    stdio = refuse(request, actor_fds=actor_fds)
    where = places(env)
    route = _route(request.model_route, where)
    report: LineChannel | None = None
    try:
        if request.report_fd is not None:
            report = LineChannel(request.report_fd)
        with open_run(where, route, progress) as dirs:
            diag(f"run {dirs.run_id} in {dirs.run_dir}")
            if report is not None and not report.write_line(
                _line({"run": dirs.run_id, "run_dir": str(dirs.run_dir), "scratch": str(dirs.scratch)})
            ):
                append_event(dirs.run_dir, "report-unwritten", line="run")
            result = steps(Opened(request, dirs, stdio, where, route))
            findings = result.findings if isinstance(result, RunResult) else tuple(result)
            disposition = disposition_of(findings)
            code = EXIT_CODES[disposition]
            with _hold_stop_signals():
                if isinstance(result, RunResult):
                    write_disposition(dirs.run_dir, dirs.run_id, disposition, findings,
                                      members=result.members, closing_heads=result.closing_heads)
                else:
                    write_disposition(dirs.run_dir, dirs.run_id, disposition, findings)
                progress.durable_exit = code
            if report is not None and not report.write_line(
                _line({"run": dirs.run_id, "disposition": disposition, "exit": code})
            ):
                append_event(dirs.run_dir, "report-unwritten", line="closing")
            diag(f"run {dirs.run_id} closed {disposition}: {', '.join(f.code for f in findings) or 'no findings'}")
            return code
    finally:
        if report is not None:
            report.close()
        if request.report_fd is not None:
            os.close(request.report_fd)
