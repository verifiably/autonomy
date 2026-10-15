"""The run directory's records (envelope design §6). This module holds `events.jsonl`
and the durable-write helpers; `baseline.json` and `seal.json` join it with the
endpoint."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

EVENTS = "events.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def append_event(run_dir: Path, event: str, **fields: object) -> None:
    """Append one line and fsync it. The file is created on first use, and its
    directory fsynced then."""
    path = run_dir / EVENTS
    created = not path.exists()
    record = {**fields, "event": event, "at": utc_now()}
    line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        write_all(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    if created:
        fsync_dir(run_dir)
