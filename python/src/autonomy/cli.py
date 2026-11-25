"""The `autonomy` command (docs/envelope.md).

`autonomy run` never reads fd 0 and never writes fd 1, help and refusals included:
both belong to the actor. Diagnostics go to fd 2 through a non-blocking channel,
truncated to one write each, and are for a person only. The record is the exit code,
the run directory and the report fd. No exception reaches CPython's default hook,
whose traceback would be a blocking write to fd 2: `main` returns an exit code on
every path."""

from __future__ import annotations

import argparse
import functools
import math
import os
import select
import sys
from collections.abc import Sequence
from pathlib import Path

import autonomy.analyst.launch as analyst
from autonomy import development, science_run
from autonomy.analyst.toolchain import AnalystRefused
from autonomy.baseline import write_all
from autonomy.channel import LineChannel
from autonomy.commands import allowance, delegation
from autonomy.run import (
    DEADLINE_DEFAULT, EXIT_CODES, EXIT_REFUSED, LEASE_DEFAULT, LEASE_FLOOR, DevelopmentProgress, Diag,
    Progress, RunRefused, RunRequest,
)
from autonomy.tiers import TierRefused, tier

_PREFIX = "autonomy: "
_FD_LIMIT = 2**31  # a descriptor number is a C int
_EXIT_LEFT = EXIT_CODES["unwired"]
"""A run whose directory exists but that ended without its close: left for `run close`."""


class _Diagnostics:
    """Diagnostics on fd 2, a `Diag`. The channel is opened at the first diagnostic,
    never before: it may open a descriptor, and one opened while fd 0 is closed would
    take number 0 and pass step 2's check. Every diagnostic a run that goes on emits
    follows step 2; one emitted earlier (a usage error, a refused tier) ends the
    process. `main` closes it before returning: a socket left to interpreter shutdown
    can warn there, on the blocking `sys.stderr`."""

    _limit = select.PIPE_BUF - 1  # room for the newline

    def __init__(self) -> None:
        self._channel: LineChannel | None = None
        self._private_log = False

    def __call__(self, message: str) -> None:
        if self._private_log:
            os.write(2, (_PREFIX + message + "\n").encode("utf-8", "replace"))
            return
        if self._channel is None:
            self._channel = LineChannel(2)
        for line in message.splitlines():
            data = (_PREFIX + line).encode("utf-8", "replace")[: self._limit]
            self._channel.write_line(data.decode("utf-8", "ignore"))  # a dropped diagnostic is ignored

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
            self._channel = None


class _Stop(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


class _Parser(argparse.ArgumentParser):
    """argparse with every message on the diagnostic channel, help included, and no
    sys.exit."""

    def __init__(self, *args, diag: Diag, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._diag = diag

    def _print_message(self, message: str, file=None) -> None:
        if message:
            self._diag(message)

    def exit(self, status: int = 0, message: str | None = None):
        if message:
            self._diag(message)
        raise _Stop(status)


def _seconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of seconds") from None
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not a positive number of seconds")
    return value


def _fd(text: str) -> int:
    if not (text.isascii() and text.isdigit()) or int(text) >= _FD_LIMIT:
        raise argparse.ArgumentTypeError(f"{text!r} is not a descriptor number")
    return int(text)


def _route(text: str) -> tuple[str, str]:
    kind, sep, family = text.partition("=")
    if not sep or not kind or not family:
        raise argparse.ArgumentTypeError(f"{text!r} is not KIND=FAMILY")
    return kind, family


def _parser(diag: Diag) -> _Parser:
    parser = _Parser(prog="autonomy", description="The envelope of verifiably: what may run unattended.", diag=diag)
    commands = parser.add_subparsers(
        dest="command", required=True, parser_class=functools.partial(_Parser, diag=diag)
    )
    allowance.add_parser(commands)
    delegation.add_parser(commands)
    run = commands.add_parser(
        "run",
        help="run one actor under the envelope",
        description="Run one actor under the envelope. Exit 0 clean, 3 quarantined, 4 unwired, 5 idle (development), 2 refused.",
        epilog="For offline development use autonomy run --development --help. Use run stop ID to stop a run or run close ID to recover its verdict.",
    )
    run.add_argument("--allowance", metavar="CAMPAIGN/MEMBER")
    run.add_argument("--conversation-id", metavar="UUID")
    run.add_argument("--provider-session-id", metavar="UUID")
    run.add_argument("--tier", required=True, help="report-only, coordination or mints; publishes is refused")
    run.add_argument(
        "--route", action="append", default=[], type=_route, metavar="KIND=FAMILY",
        help="a kind a mints tier may mint, and its route; repeat for each kind",
    )
    run.add_argument(
        "--lease", type=_seconds, default=LEASE_DEFAULT, metavar="SECONDS",
        help=f"the endpoint's lease (default {LEASE_DEFAULT:g}, floor {LEASE_FLOOR:g})",
    )
    run.add_argument(
        "--report-fd", type=_fd, metavar="N",
        help="an anonymous pipe or connected AF_UNIX stream socket, not fd 0-2, for the run and closing lines",
    )
    run.add_argument(
        "--model-route", metavar="NAME",
        help="the model route under <config>/routes/NAME.toml: the actor's only network path",
    )
    run.add_argument(
        "--deadline", type=_seconds, default=DEADLINE_DEFAULT, metavar="SECONDS",
        help=f"monotonic run deadline (default {DEADLINE_DEFAULT:g})",
    )
    run.add_argument(
        "--toolchain", action="append", default=[], type=Path, metavar="PATH",
        help="an actor runtime path bound read-only after verification; repeat for each path",
    )
    run.add_argument("actor", nargs="+", metavar="ACTOR", help="the actor's argv, after --")
    analyst_parser = commands.add_parser(
        "analyst",
        help="run a fresh pi analyst over declared inputs under the sandbox",
        description=(
            "Run a fresh pi analyst under the sandbox with only the declared read-only inputs, the declared paths "
            "denied, and its outputs released to one directory. Exit 0 clean, 3 released with findings, "
            "4 the analyst never started, 2 refused."
        ),
    )
    analyst_parser.add_argument("--allowance", metavar="CAMPAIGN/MEMBER")
    analyst_parser.add_argument("--model-route", required=True, metavar="NAME", help="the model route under <config>/routes/NAME.toml")
    analyst_parser.add_argument("--model", required=True, metavar="MODEL", help="pi's --model; must be in the route's models")
    analyst_parser.add_argument("--thinking", required=True, metavar="LEVEL", help="pi's --thinking level; must be supported for --model in pi's registry")
    analyst_parser.add_argument("--input", action="append", default=[], type=Path, metavar="DIR", help="a directory bound read-only at its real path; repeat for each")
    analyst_parser.add_argument("--deny", action="append", default=[], type=Path, metavar="PATH", help="a path the analyst must not reach; repeat for each")
    analyst_parser.add_argument("--release", required=True, type=Path, metavar="DIR", help="an existing empty directory the outputs are released into")
    analyst_parser.add_argument("--report-fd", type=_fd, metavar="N", help="an anonymous pipe or connected AF_UNIX stream socket, not fd 0-2, for the run and closing lines")
    analyst_parser.add_argument("--pi-dir", type=Path, metavar="DIR", help="the pinned pi install (default PI_DIR, else ~/.local/share/pi/<version>)")
    analyst_parser.add_argument("--node-dir", type=Path, metavar="DIR", help="the node prefix (default NODE_DIR, else the prefix of node on PATH)")
    analyst_parser.add_argument("--lease", type=_seconds, default=LEASE_DEFAULT, metavar="SECONDS", help=f"the route's lease (default {LEASE_DEFAULT:g}, floor {LEASE_FLOOR:g})")
    analyst_parser.add_argument("--deadline", type=_seconds, default=analyst.DEADLINE_DEFAULT, metavar="SECONDS", help=f"the whole run's wall-clock bound (default {analyst.DEADLINE_DEFAULT:g})")
    command_parser = commands.add_parser(
        "command",
        help="run a pinned command over declared inputs under the sandbox with no model or network",
        description=(
            "Run a pinned command under the sandbox with only the declared read-only inputs, the declared paths "
            "denied, no model or network route, and its outputs released to one directory. Exit 0 clean, "
            "3 released with findings, 4 the command never started, 2 refused."
        ),
    )
    command_parser.add_argument("--input", action="append", default=[], type=Path, metavar="PATH", help="a regular file or directory bound read-only at its real path; repeat for each")
    command_parser.add_argument("--deny", action="append", default=[], type=Path, metavar="PATH", help="a path the command must not reach; repeat for each")
    command_parser.add_argument("--release", required=True, type=Path, metavar="DIR", help="an existing empty directory the outputs are released into")
    command_parser.add_argument("--workdir", type=Path, metavar="DIR", help="working directory inside a declared directory --input (default: scratch)")
    command_parser.add_argument("--report-fd", type=_fd, metavar="N", help="an anonymous pipe or connected AF_UNIX stream socket, not fd 0-2, for the run and closing lines")
    command_parser.add_argument("--deadline", type=_seconds, default=analyst.DEADLINE_DEFAULT, metavar="SECONDS", help=f"the whole run's wall-clock bound (default {analyst.DEADLINE_DEFAULT:g})")
    return parser


def _run(args: argparse.Namespace, diag: _Diagnostics, progress: Progress) -> int:
    try:
        routes = dict(args.route)
        if len(routes) != len(args.route):
            raise RunRefused("route-repeated", "each kind takes one --route")
        try:
            chosen = tier(args.tier, routes or None)
        except TierRefused as caught:
            raise RunRefused(caught.code, str(caught).removeprefix(f"{caught.code}: ")) from None
        request = RunRequest(chosen, args.lease, args.report_fd, tuple(args.actor), args.model_route,
                             args.deadline, tuple(args.toolchain), args.allowance, args.conversation_id, args.provider_session_id)
        return science_run.execute(request, os.environ, diag=diag, progress=progress,
                                   actor_launched=lambda run_dir: _release_supervisor_stdio(diag, run_dir))
    except RunRefused as caught:
        if progress.dirs is not None:
            raise
        diag(f"refused: {caught.code}: {caught.message}")
        return EXIT_REFUSED


_DEVELOPMENT_VALUES = (
    "tier", "route", "lease", "model-route", "repository", "base", "deadline", "report-fd", "delegation", "attempt",
)


def _development_options(options: Sequence[str]) -> list[str]:
    # argparse recognizes -1 as a value but treats -inf as a switch. Pass
    # both through admission, which owns the typed refusal for a bad value.
    flags = {f"--{name}" for name in _DEVELOPMENT_VALUES}
    normalized = []
    index = 0
    while index < len(options):
        item = options[index]
        if item in flags and index + 1 < len(options):
            value = options[index + 1]
            if value.startswith("-") and not value.startswith("--") and value != "-h":
                item = f"{item}={value}"
                index += 1
        normalized.append(item)
        index += 1
    return normalized


def _release_supervisor_stdio(diag: _Diagnostics, run_dir: Path | None = None) -> None:
    diag.close()
    null = os.open(os.devnull, os.O_RDWR | os.O_CLOEXEC)
    try:
        os.dup2(null, 0)
        os.dup2(null, 1)
        if run_dir is None:
            os.dup2(null, 2)
        else:
            log = os.open(run_dir / "orchestrator.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC, 0o600)
            try:
                os.dup2(log, 2)
                diag._private_log = True
            finally:
                os.close(log)
    finally:
        os.close(null)


def _development_run(
    options: Sequence[str], actor: Sequence[str], diag: _Diagnostics, progress: DevelopmentProgress,
) -> int:
    parser = _Parser(prog="autonomy run --development", diag=diag, allow_abbrev=False,
                     description="Prepare one offline Git candidate under supervision.")
    parser.add_argument("--development", action="store_true", help=argparse.SUPPRESS)
    for name in _DEVELOPMENT_VALUES:
        parser.add_argument(f"--{name}", default=None, nargs="?", const="")
    args = parser.parse_args(_development_options(options))
    if any(value is not None for value in (args.tier, args.route, args.lease)):
        raise RunRefused("development-mode-conflict", "omit --tier, --route and --lease for development runs")
    if args.model_route is not None:
        raise RunRefused("development-model-route-refused", "omit the model route for supervised offline development")
    if (args.delegation is None) != (args.attempt is None):
        raise RunRefused("development-mode-conflict", "pass --delegation and --attempt together")
    if not args.repository:
        raise RunRefused("development-repository-invalid", "select an approved local repository with --repository")
    if not args.base:
        raise RunRefused("development-base-invalid", "supply the full approved commit ID with --base")
    try:
        deadline = _seconds(args.deadline or "")
    except argparse.ArgumentTypeError as caught:
        raise RunRefused("deadline-invalid", "supply a positive finite --deadline in seconds") from caught
    if not actor:
        parser.error("supply the actor executable and argv after --")
    try:
        report_fd = None if args.report_fd is None else _fd(args.report_fd)
    except argparse.ArgumentTypeError as caught:
        raise RunRefused("stdio-refused", str(caught)) from caught
    request = development.DevelopmentRequest(
        Path(args.repository), args.base, deadline, tuple(actor), report_fd, args.delegation, args.attempt,
    )
    return development.execute(request, os.environ, diag=diag, progress=progress,
                               actor_launched=lambda: _release_supervisor_stdio(diag))


def _run_control(action: str, options: Sequence[str], diag: Diag) -> int:
    parser = _Parser(prog=f"autonomy run {action}", diag=diag)
    parser.add_argument("run_id", nargs="?", metavar="RUN_ID")
    args = parser.parse_args(options)
    if args.run_id is None:
        raise RunRefused("run-invalid", "supply the recorded run ID")
    return science_run.control(action, args.run_id, os.environ, diag=diag, emit=lambda receipt: write_all(1, receipt.encode()))


def _analyst(args: argparse.Namespace, diag: Diag, progress: analyst.Progress) -> int:
    try:
        if not args.input:
            raise AnalystRefused("input-missing", "at least one --input directory is required")
        request = analyst.AnalystRequest(
            args.model_route, args.model, args.thinking, tuple(args.input), tuple(args.deny), args.release,
            report_fd=args.report_fd, pi_dir=args.pi_dir, node_dir=args.node_dir, lease=args.lease, allowance=args.allowance,
            deadline=args.deadline,
        )
        return analyst.execute(request, os.environ, diag=diag, progress=progress)
    except AnalystRefused as caught:
        diag(f"refused: {caught.code}: {caught.message}")
        return EXIT_REFUSED


def _command(args: argparse.Namespace, cmd_argv: Sequence[str], diag: Diag, progress: analyst.Progress) -> int:
    try:
        if not args.input:
            raise AnalystRefused("input-missing", "at least one --input is required")
        if not cmd_argv:
            raise AnalystRefused("command-missing", "a command executable is required after --")
        request = analyst.CommandRequest(
            inputs=tuple(args.input),
            denied=tuple(args.deny),
            release_dir=args.release,
            argv=tuple(cmd_argv),
            workdir=args.workdir,
            report_fd=args.report_fd,
            deadline=args.deadline,
        )
        return analyst.execute_command(request, os.environ, diag=diag, progress=progress, take_stdio=True)
    except AnalystRefused as caught:
        diag(f"refused: {caught.code}: {caught.message}")
        return EXIT_REFUSED


def _unexpected(caught: BaseException, diag: Diag, progress: Progress | analyst.Progress | DevelopmentProgress, *, label: str = "run") -> int:
    """The last resort for an exception nothing else handles, SIGINT's
    `KeyboardInterrupt` included: one diagnostic line, then exit 2 when no run
    directory exists, or 4 when one does. That run has no `disposition.json` and is
    left for `run close`, and `execute` has already closed its report fd; without a
    run directory, the process's exit closes it."""
    if isinstance(progress, (Progress, DevelopmentProgress)) and progress.durable_exit is not None:
        return progress.durable_exit
    if isinstance(progress, (analyst.Progress, DevelopmentProgress)):
        run_dir = progress.run_dir
    else:
        run_dir = None if progress.dirs is None else progress.dirs.run_dir
    status = EXIT_REFUSED if run_dir is None else _EXIT_LEFT
    try:
        message = " ".join(str(caught).splitlines())
        what = f"{type(caught).__name__}: {message}" if message else type(caught).__name__
        if run_dir is None:
            diag(f"failed: {what}")
        else:
            diag(f"{label} {run_dir.name} stopped by {what}; {run_dir} is left" + (" for run close" if label == "run" else ""))
    except BaseException:
        pass  # a diagnostic that cannot be written is ignored; the exit code is the record
    return status


def main(argv: Sequence[str] | None = None) -> int:
    diag = _Diagnostics()
    progress: Progress | analyst.Progress | DevelopmentProgress = Progress()
    label = "run"
    try:
        raw_argv = list(sys.argv[1:] if argv is None else argv)
        before, actor = raw_argv, []
        if "--" in raw_argv:
            sep = raw_argv.index("--")
            before, actor = raw_argv[:sep], raw_argv[sep + 1:]
        if before[:1] == ["run"]:
            if len(before) > 1 and before[1] in ("stop", "close"):
                if before != raw_argv:
                    raise RunRefused("run-invalid", "control commands take only the recorded run ID")
                return _run_control(before[1], before[2:], diag)
            if "--development" in before[1:]:
                progress = DevelopmentProgress()
                return _development_run(before[1:], actor, diag, progress)
        args = _parser(diag).parse_args(before if raw_argv[:1] == ["command"] else raw_argv)
        if args.command == "allowance":
            return allowance.execute(args)
        if args.command == "delegation":
            return delegation.execute(args)
        if args.command == "analyst":
            label = "analyst run"
            progress = analyst.Progress()
            return _analyst(args, diag, progress)
        if args.command == "command":
            label = "command run"
            progress = analyst.Progress()
            return _command(args, actor, diag, progress)
        return _run(args, diag, progress)
    except _Stop as stop:
        return stop.status
    except RunRefused as caught:
        if (isinstance(progress, DevelopmentProgress) and progress.run_dir is not None
                or isinstance(progress, Progress) and progress.dirs is not None):
            return _unexpected(caught, diag, progress)
        try:
            diag(f"refused: {caught.code}: {caught.message}")
        except BaseException:
            return _unexpected(caught, diag, progress)
        return EXIT_REFUSED
    except BaseException as caught:
        return _unexpected(caught, diag, progress, label=label)
    finally:
        try:
            diag.close()
        except BaseException:
            pass
