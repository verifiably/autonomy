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
from autonomy.analyst.toolchain import AnalystRefused
from autonomy.channel import LineChannel
from autonomy.run import (
    EXIT_CODES, EXIT_REFUSED, LEASE_DEFAULT, LEASE_FLOOR, Diag, Progress, RunRefused, RunRequest,
    endpoint_side_unbuilt, execute,
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

    def __call__(self, message: str) -> None:
        if self._channel is None:
            self._channel = LineChannel(2)
        for line in message.splitlines():
            data = (_PREFIX + line).encode("utf-8", "replace")[: self._limit]
            self._channel.write_line(data.decode("utf-8", "ignore"))  # a dropped diagnostic is ignored

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()


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
    run = commands.add_parser(
        "run",
        help="run one actor under the envelope",
        description="Run one actor under the envelope. Exit 0 clean, 3 quarantined, 4 unwired, 2 refused.",
    )
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


def _run(args: argparse.Namespace, diag: Diag, progress: Progress) -> int:
    try:
        routes = dict(args.route)
        if len(routes) != len(args.route):
            raise RunRefused("route-repeated", "each kind takes one --route")
        try:
            chosen = tier(args.tier, routes or None)
        except TierRefused as caught:
            raise RunRefused(caught.code, str(caught).removeprefix(f"{caught.code}: ")) from None
        request = RunRequest(chosen, args.lease, args.report_fd, tuple(args.actor), args.model_route)
        return execute(request, os.environ, endpoint_side_unbuilt, diag=diag, progress=progress)
    except RunRefused as caught:
        diag(f"refused: {caught.code}: {caught.message}")
        return EXIT_REFUSED


def _analyst(args: argparse.Namespace, diag: Diag, progress: analyst.Progress) -> int:
    try:
        if not args.input:
            raise AnalystRefused("input-missing", "at least one --input directory is required")
        request = analyst.AnalystRequest(
            args.model_route, args.model, args.thinking, tuple(args.input), tuple(args.deny), args.release,
            report_fd=args.report_fd, pi_dir=args.pi_dir, node_dir=args.node_dir, lease=args.lease,
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


def _unexpected(caught: BaseException, diag: Diag, progress: Progress | analyst.Progress, *, label: str = "run") -> int:
    """The last resort for an exception nothing else handles, SIGINT's
    `KeyboardInterrupt` included: one diagnostic line, then exit 2 when no run
    directory exists, or 4 when one does. That run has no `disposition.json` and is
    left for `run close`, and `execute` has already closed its report fd; without a
    run directory, the process's exit closes it."""
    if isinstance(progress, analyst.Progress):
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
    progress: Progress | analyst.Progress = Progress()
    label = "run"
    try:
        raw_argv = list(sys.argv[1:] if argv is None else argv)
        cmd_argv: list[str] = []
        if raw_argv and raw_argv[0] == "command":
            if "--" in raw_argv:
                sep = raw_argv.index("--")
                raw_argv, cmd_argv = raw_argv[:sep], raw_argv[sep + 1:]
        try:
            args = _parser(diag).parse_args(raw_argv)
        except _Stop as stop:
            return stop.status
        if args.command == "analyst":
            label = "analyst run"
            progress = analyst.Progress()
            return _analyst(args, diag, progress)
        if args.command == "command":
            label = "command run"
            progress = analyst.Progress()
            return _command(args, cmd_argv, diag, progress)
        return _run(args, diag, progress)
    except BaseException as caught:
        return _unexpected(caught, diag, progress, label=label)
    finally:
        diag.close()
