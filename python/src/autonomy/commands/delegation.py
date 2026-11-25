"""Operator commands for issuing, revoking and reporting development delegations."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import time
from datetime import datetime, timezone

from autonomy import development
from autonomy.allowance import AllowanceRefused, private_config, storage
from autonomy.baseline import write_all
from autonomy.delegation import (
    Ceiling,
    Delegation,
    Host,
    Start,
    current_host,
    definition,
    identifier,
    peak_memory,
    survey,
)
from autonomy.run import EXIT_REFUSED, RunRefused


def add_parser(commands) -> None:
    group = commands.add_parser("delegation", help="manage operator grants for delegated development runs")
    ops = group.add_subparsers(dest="operation", required=True, parser_class=commands._parser_class)
    ops.add_parser("issue", help="confirm and issue a named delegation from operator config").add_argument("name")
    ops.add_parser("revoke", help="permanently close a delegation and stop any running actor").add_argument("delegation")
    rep = ops.add_parser("report", help="settle and report a delegation and its starts")
    rep.add_argument("delegation")
    rep.add_argument("--attempt", default=None)


def _format_terms(grant_cfg: dict, ceil: Ceiling, unfinished: tuple[Start, ...]) -> str:
    limits = grant_cfg["limits"]
    starts = int(limits["starts"])
    deadline = int(limits["deadline_seconds"])
    writable = int(limits["writable_bytes"])
    total_seconds = starts * deadline
    total_disk = starts * (ceil.prepared_bytes + writable)
    peak_bytes = peak_memory(limits, ceil)
    expires = int(grant_cfg["expires"])
    expires_iso = datetime.fromtimestamp(expires, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        f"Delegation ID: {grant_cfg['delegation_id']}",
        f"Orchestrator: {grant_cfg['orchestrator']['name']} (unit: {grant_cfg['orchestrator']['unit']})",
        "Repositories:",
    ]
    for repo_name, entry in sorted(grant_cfg["repositories"].items()):
        lines.append(f"  {repo_name}: {entry['path']} ({entry['ref']})")
    lines.append("Commands:")
    for actor_name, argv in sorted(grant_cfg["actors"].items()):
        lines.append(f"  {actor_name}: {shlex.join(argv)}")
    lines.extend(
        [
            f"Longest total run time: {total_seconds} s ({starts} x {deadline} s)",
            f"Most retained disk: {total_disk} bytes ({total_disk // (1 << 20)} MiB)",
            f"Peak memory at once: {peak_bytes} bytes ({peak_bytes // (1 << 20)} MiB)",
            f"Expires: {expires_iso} ({expires})",
        ]
    )
    if unfinished:
        lines.append("Earlier unfinished starts on this unit:")
        for item in unfinished:
            lines.append(f"  run {item.run} (attempt {item.attempt}, state {item.state})")
    lines.append(f"Type delegation ID '{grant_cfg['delegation_id']}' to confirm: ")
    return "\n".join(lines)


def _read_tty_line(tty_fd: int, limit: int = 256) -> str | None:
    chunks: list[bytes] = []
    total = 0
    while total < limit:
        try:
            byte = os.read(tty_fd, 1)
        except OSError:
            return None
        if not byte:
            return None
        chunks.append(byte)
        total += 1
        if byte == b"\n":
            return b"".join(chunks).rstrip(b"\r\n").decode("utf-8", "replace")
    return None


def _confirm_on_tty(grant_cfg: dict, ceil: Ceiling, unfinished: tuple[Start, ...]) -> None:
    previous_hup = signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        try:
            tty_fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY | os.O_CLOEXEC)
        except OSError as exc:
            raise RunRefused("delegation-unconfirmed", f"no controlling terminal for confirmation: {exc}") from exc
        try:
            prompt = _format_terms(grant_cfg, ceil, unfinished)
            write_all(tty_fd, prompt.encode("utf-8"))
            typed = _read_tty_line(tty_fd)
        except OSError as exc:
            raise RunRefused("delegation-unconfirmed", f"controlling terminal closed during confirmation: {exc}") from exc
        finally:
            os.close(tty_fd)
    finally:
        signal.signal(signal.SIGHUP, previous_hup)
    if typed != grant_cfg["delegation_id"]:
        raise RunRefused("delegation-unconfirmed", "typed confirmation did not match delegation_id")


def execute(args: argparse.Namespace, *, host: Host | None = None) -> int:
    try:
        resolved = current_host() if host is None else host
        if args.operation == "issue":
            name = identifier(args.name)
            try:
                raw = private_config(resolved.config / "delegations" / f"{name}.json")
            except AllowanceRefused as exc:
                raise RunRefused("delegation-invalid", str(exc)) from exc
            ceil = development.ceiling()
            grant_cfg = definition(raw, ceil)
            if grant_cfg["expires"] <= time.time():
                raise RunRefused("delegation-expired", "grant has already expired")
            try:
                root = storage(resolved.config)
            except AllowanceRefused as exc:
                raise RunRefused("delegation-unavailable", str(exc)) from exc
            unit = grant_cfg["orchestrator"]["unit"]
            found = survey(root, unit)
            if found.holders:
                raise RunRefused(
                    "delegation-unit-held",
                    f"unit {unit} already has an active or stopping grant ({found.holders[0]})",
                )
            if (root / f"{grant_cfg['delegation_id']}.sqlite").exists():
                raise RunRefused("delegation-closed", f"grant ID {grant_cfg['delegation_id']} was already used")
            _confirm_on_tty(grant_cfg, ceil, found.unfinished)
            issued = Delegation.issue(root, grant_cfg)
            receipt = development.report(issued, resolved)
            write_all(1, (json.dumps(receipt, allow_nan=False) + "\n").encode("utf-8"))
            return 0

        if args.operation == "revoke":
            grant = development.open_grant(resolved, args.delegation)
            res = development.revoke(grant, resolved)
            unit = grant.grant().config["orchestrator"]["unit"]
            revoke_receipt: dict[str, object] = {
                "delegation_id": grant.name,
                "cause": res.cause,
                "first": res.first,
                "actor": res.actor,
                "acknowledged": res.acknowledged,
            }
            if not res.acknowledged:
                revoke_receipt["stop_unit"] = f"systemctl --user stop {unit}"
            write_all(1, (json.dumps(revoke_receipt, allow_nan=False) + "\n").encode("utf-8"))
            if not res.acknowledged:
                raise RunRefused(
                    "delegation-stop-unacknowledged",
                    f"closure is durable ({res.cause}), stop unacknowledged (actor {res.actor}); run systemctl --user stop {unit}",
                )
            return 0

        grant = development.open_grant(resolved, args.delegation)
        report_receipt = development.report(grant, resolved, attempt=args.attempt)
        write_all(1, (json.dumps(report_receipt, allow_nan=False) + "\n").encode("utf-8"))
        return 0
    except RunRefused as exc:
        write_all(2, f"autonomy: refused: {exc.code}: {exc.message}\n".encode("utf-8", "replace"))
        return EXIT_REFUSED
