"""The run directory's records (docs/records.md). This module holds `events.jsonl`
and the durable-write helpers; `baseline.json` and `seal.json` join it with the
endpoint."""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import stat
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

EVENTS = "events.jsonl"
ADMISSION_LOCK = "admission.lock"


@contextmanager
def lock(path: Path, *, create: bool = False, nowait: bool = False,
         until: float | None = None, cancelled: Callable[[], bool] | None = None) -> Iterator[int]:
    flags = os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(path, flags | (os.O_CREAT if create else 0), 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise ValueError(f"invalid run lock {path.name}")
        bounded = until is not None or cancelled is not None
        while True:
            now = time.monotonic()
            if (cancelled is not None and cancelled()) or (until is not None and now >= until):
                raise TimeoutError(f"waiting for {path.name} was interrupted")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | (fcntl.LOCK_NB if nowait or bounded else 0))
                break
            except BlockingIOError:
                if nowait or not bounded:
                    raise
                time.sleep(0.05 if until is None else min(0.05, max(0, until - time.monotonic())))
        yield fd
    finally:
        os.close(fd)


def is_publication_alias(name: str, final: str) -> bool:
    return re.fullmatch(rf"\.{re.escape(final)}\.[0-9a-f]{{16}}\.tmp", name) is not None


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
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        size = os.fstat(fd).st_size
        if size and os.pread(fd, 1, size - 1) != b"\n":
            raise ValueError("cannot append to an incomplete event journal")
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
                or info.st_mode & 0o077 or not _private_links(path, fd, info)):
            raise ValueError(f"{path.name} must be an owned private regular file")
        return stream.read()


def _private_links(path: Path, fd: int, info: os.stat_result) -> bool:
    if info.st_nlink == 1:
        return True
    if info.st_nlink != 2:
        return False
    for candidate in path.parent.iterdir():
        if is_publication_alias(candidate.name, path.name):
            try:
                if os.path.samestat(candidate.lstat(), info):
                    return os.fstat(fd).st_nlink in (1, 2)
            except FileNotFoundError:
                continue
    return os.fstat(fd).st_nlink == 1


def read_events(run_dir: Path) -> tuple[tuple[dict[str, object], ...], bool]:
    """Return complete journal rows and whether bytes from the last row were torn."""
    try:
        data = read_private_bytes(run_dir / EVENTS)
    except FileNotFoundError:
        return (), False
    *complete, tail = data.split(b"\n")
    return tuple(decode_object(line) for line in complete), bool(tail)


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
