"""The run directory's records (docs/records.md). This module holds `events.jsonl`
and the durable-write helpers; `baseline.json` and `seal.json` join it with the
endpoint."""

from __future__ import annotations

import json
import os
import secrets
import stat
from collections.abc import Mapping
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


def publish_bytes(path: Path, data: bytes) -> None:
    """Publish complete bytes once, with the containing directory synced."""
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        try:
            write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.link(temporary, path)
    finally:
        temporary.unlink()
    fsync_dir(path.parent)


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



def publish_json(path: Path, value: Mapping[str, object]) -> None:
    publish_bytes(path, (json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n").encode())


def read_private_bytes(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError(f"{path.name} must be an owned private regular file")
        return stream.read()


def _unique_fields(fields: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(fields)
    if len(result) != len(fields):
        raise ValueError("duplicate fields in protected run record")
    return result


def decode_object(data: bytes) -> dict[str, object]:
    row = json.loads(data, object_pairs_hook=_unique_fields)
    if type(row) is not dict:
        raise ValueError("protected run record must be a JSON object")
    return row


def read_record(path: Path) -> dict[str, object]:
    return decode_object(read_private_bytes(path))
