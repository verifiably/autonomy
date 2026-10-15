"""The run supervisor (envelope design §3): steps 1 and 2, and the close's records
(`disposition.json`, the report fd's two lines, the exit code). Steps 3 to 9 are a
`Steps` callable; until science's run endpoint exists, `endpoint_side_unbuilt` closes
every run `unwired` before any chain is read or the actor starts."""

from __future__ import annotations

import json
import os
import pwd
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from autonomy.baseline import append_event, fsync_dir, utc_now, write_all
from autonomy.channel import LineChannel
from autonomy.closing import Disposition, disposition_of
from autonomy.membership import Finding
from autonomy.stdio import ACTOR_FDS, StdioKind, StdioRefused, check_report_fd, check_stdio
from autonomy.tiers import Tier

LEASE_FLOOR = 10.0
LEASE_DEFAULT = 60.0
EXIT_REFUSED = 2
EXIT_CODES: Mapping[Disposition, int] = MappingProxyType({"clean": 0, "quarantined": 3, "unwired": 4})
DISPOSITION = "disposition.json"

Diag = Callable[[str], None]


class RunRefused(Exception):
    """A configuration refusal at step 2: exit 2, and no run directory."""

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


@dataclass(frozen=True)
class Places:
    state: Path
    cache: Path
    runtime: Path


def _xdg(env: Mapping[str, str], name: str, fallback: Path) -> Path:
    """The XDG base directory spec: a relative or empty value is invalid and ignored."""
    value = env.get(name, "")
    return Path(value) if value and Path(value).is_absolute() else fallback


def places(env: Mapping[str, str]) -> Places:
    runtime = env.get("XDG_RUNTIME_DIR", "")
    if not runtime or not Path(runtime).is_absolute():
        raise RunRefused(
            "runtime-dir-unset", "XDG_RUNTIME_DIR must name an absolute directory: the endpoint's socket lives there"
        )
    home = Path(env.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir)
    return Places(
        state=_xdg(env, "XDG_STATE_HOME", home / ".local" / "state") / "verifiably-autonomy",
        cache=_xdg(env, "XDG_CACHE_HOME", home / ".cache") / "verifiably-autonomy",
        runtime=Path(runtime),
    )


@dataclass(frozen=True)
class RunDirs:
    run_id: str
    run_dir: Path
    scratch: Path
    socket_dir: Path


def allocate(where: Places) -> RunDirs:
    """Step 1. The socket directory's name is the run id's first 12 hex digits, short
    because of the 107-byte AF_UNIX path limit. Each directory is new: a collision
    fails rather than sharing one."""
    run_id = secrets.token_hex(16)
    run_dir = where.state / "runs" / run_id
    scratch = where.cache / "scratch" / run_id
    socket_dir = where.runtime / "va" / run_id[:12]
    for path in (run_dir, scratch, socket_dir):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.mkdir(mode=0o700)
    return RunDirs(run_id, run_dir, scratch.resolve(), socket_dir)


def refuse(request: RunRequest, *, actor_fds: tuple[int, int, int] = ACTOR_FDS) -> tuple[StdioKind, StdioKind, StdioKind]:
    """Step 2's checks that need no world. The tier is refused when it is built; the
    write-corpus and orphaned-run checks need science's reads."""
    if request.lease < LEASE_FLOOR:
        raise RunRefused("lease-below-floor", f"the lease is {request.lease:g} s; the floor is {LEASE_FLOOR:g} s")
    try:
        kinds = check_stdio(actor_fds)
        if request.report_fd is not None:
            check_report_fd(request.report_fd, actor_fds)
    except StdioRefused as caught:
        raise RunRefused(caught.code, caught.message) from None
    return kinds


@dataclass(frozen=True)
class Opened:
    request: RunRequest
    dirs: RunDirs
    stdio: tuple[StdioKind, StdioKind, StdioKind]


Steps = Callable[[Opened], Sequence[Finding]]
"""Steps 3 to 9 and the close's seal and check: everything between the report fd's
first line and `disposition.json`. Returns the run's findings."""


def endpoint_side_unbuilt(opened: Opened) -> tuple[Finding, ...]:
    """This build has no science reads and no endpoint, so step 3 cannot capture a
    baseline. The run closes `unwired` before any chain is read or the actor starts."""
    return (
        Finding(
            "baseline-unavailable",
            "science",
            "this build has no science reads or run endpoint yet; the baseline cannot be captured "
            "and the actor never starts",
        ),
    )


def write_disposition(run_dir: Path, run_id: str, disposition: Disposition, findings: Sequence[Finding]) -> None:
    """Published once and atomically, before the closing line. The record is written
    and fsynced under a temporary name in the run directory, then hard-linked to its
    final name: `link` refuses a name that exists, so a disposition is never replaced.
    The contract is absent before publication, complete after it. An interruption
    before the link leaves no `disposition.json`, and a retry succeeds. An interruption
    after the link (at the final directory fsync) leaves a complete `disposition.json`,
    and a retry raises `FileExistsError`. A writer killed outright leaves only its
    temporary behind. The directory is fsynced last."""
    record = {
        "version": 1,
        "run": run_id,
        "disposition": disposition,
        "findings": [{"code": f.code, "ref": f.ref, "message": f.message} for f in findings],
        "closed_at": utc_now(),
        "members": {},
        "closing_heads": None,
    }
    temporary = run_dir / f".{DISPOSITION}.{secrets.token_hex(8)}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        try:
            write_all(fd, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.link(temporary, run_dir / DISPOSITION)
    finally:
        temporary.unlink()
    fsync_dir(run_dir)


def _line(value: Mapping[str, object]) -> str:
    return json.dumps(value, separators=(",", ":"))


def execute(
    request: RunRequest,
    env: Mapping[str, str],
    steps: Steps,
    *,
    diag: Diag,
    actor_fds: tuple[int, int, int] = ACTOR_FDS,
) -> int:
    """Refuse (raising `RunRefused` before anything exists), allocate, report the run,
    run `steps`, then close: `disposition.json`, the closing line, the exit code. The
    report fd is closed on the way out."""
    stdio = refuse(request, actor_fds=actor_fds)
    where = places(env)
    report = None if request.report_fd is None else LineChannel(request.report_fd)
    try:
        dirs = allocate(where)
        diag(f"run {dirs.run_id} in {dirs.run_dir}")
        if report is not None and not report.write_line(
            _line({"run": dirs.run_id, "run_dir": str(dirs.run_dir), "scratch": str(dirs.scratch)})
        ):
            append_event(dirs.run_dir, "report-unwritten", line="run")
        findings = tuple(steps(Opened(request, dirs, stdio)))
        disposition = disposition_of(findings)
        code = EXIT_CODES[disposition]
        write_disposition(dirs.run_dir, dirs.run_id, disposition, findings)
        if report is not None and not report.write_line(
            _line({"run": dirs.run_id, "disposition": disposition, "exit": code})
        ):
            append_event(dirs.run_dir, "report-unwritten", line="closing")
        diag(f"run {dirs.run_id} closed {disposition}: {', '.join(f.code for f in findings) or 'no findings'}")
        return code
    finally:
        if report is not None:
            report.close()
            os.close(report.fd)
