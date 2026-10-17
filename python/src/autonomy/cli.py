"""The `autonomy` command (envelope design §3, decision 12).

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
from collections.abc import Sequence

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
        help="the model route under <config>/routes/NAME.toml: the actor's only network path (decision 13)",
    )
    run.add_argument("actor", nargs="+", metavar="ACTOR", help="the actor's argv, after --")
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


def _unexpected(caught: BaseException, diag: Diag, progress: Progress) -> int:
    """The last resort for an exception nothing else handles, SIGINT's
    `KeyboardInterrupt` included: one diagnostic line, then exit 2 when no run
    directory exists, or 4 when one does. That run has no `disposition.json` and is
    left for `run close`, and `execute` has already closed its report fd; without a
    run directory, the process's exit closes it."""
    status = EXIT_REFUSED if progress.dirs is None else _EXIT_LEFT
    try:
        message = " ".join(str(caught).splitlines())
        what = f"{type(caught).__name__}: {message}" if message else type(caught).__name__
        if progress.dirs is None:
            diag(f"failed: {what}")
        else:
            diag(f"run {progress.dirs.run_id} stopped by {what}; {progress.dirs.run_dir} is left for run close")
    except BaseException:
        pass  # a diagnostic that cannot be written is ignored (decision 12); the exit code is the record
    return status


def main(argv: Sequence[str] | None = None) -> int:
    diag = _Diagnostics()
    progress = Progress()
    try:
        try:
            args = _parser(diag).parse_args(argv)
        except _Stop as stop:
            return stop.status
        return _run(args, diag, progress)
    except BaseException as caught:
        return _unexpected(caught, diag, progress)
    finally:
        diag.close()
