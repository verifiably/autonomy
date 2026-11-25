"""Private-file checks, exclusive publication, and one transaction over a grant database."""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from autonomy.baseline import fsync_dir


class GrantMissing(Exception):
    """No grant of the requested kind exists at this path."""


class GrantUnusable(Exception):
    """The grant storage, file permissions, or stored record is unusable."""


def private_path(path: Path, *, directory: bool) -> None:
    try:
        info = path.lstat()
        resolved = path.resolve()
    except OSError as exc:
        raise GrantUnusable("accounting requires private owned storage") from exc
    mode = 0o700 if directory else 0o600
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not (
        path.is_absolute()
        and path == resolved
        and kind(info.st_mode)
        and stat.S_IMODE(info.st_mode) == mode
        and info.st_uid == os.geteuid()
    ):
        raise GrantUnusable("accounting requires private owned storage")


def publish_grant_file(root: Path, path: Path, build: Callable[[sqlite3.Connection], None]) -> None:
    try:
        private_path(root, directory=True)
        with tempfile.NamedTemporaryFile(dir=root, prefix=".issuing-") as temporary:
            with closing(sqlite3.connect(temporary.name)) as db:
                db.execute("PRAGMA synchronous=EXTRA")
                build(db)
                db.commit()
            os.fsync(temporary.fileno())
            os.link(temporary.name, path)
            fsync_dir(root)
    except (FileExistsError, GrantUnusable):
        raise
    except (OSError, sqlite3.Error) as exc:
        raise GrantUnusable("cannot publish durable grant") from exc


def _decode_config(raw: object) -> dict:
    if not isinstance(raw, str):
        raise GrantUnusable("invalid grant record")
    try:
        config = json.loads(raw)
    except ValueError as exc:
        raise GrantUnusable("invalid grant record") from exc
    if type(config) is not dict:
        raise GrantUnusable("invalid grant record")
    return config


@contextmanager
def grant_transaction(
    root: Path, path: Path, field: str, name: str
) -> Iterator[tuple[sqlite3.Connection, dict, str | None]]:
    private_path(root, directory=True)
    try:
        private_path(path, directory=False)
    except GrantUnusable as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            raise GrantMissing("unknown grant") from None
        raise
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=1)
    except (sqlite3.Error, OSError, ValueError) as exc:
        raise GrantUnusable("unusable accounting state") from exc
    with closing(conn) as db:
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=EXTRA")
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT * FROM grant_record").fetchall()
            if len(rows) != 1:
                raise GrantUnusable("invalid grant record")
            config = _decode_config(rows[0]["cfg"])
            if field not in config:
                raise GrantMissing("grant is of another kind")
            if config[field] != name:
                raise GrantUnusable("grant identity differs")
            expires = config.get("expires")
            if type(expires) is not int:
                raise GrantUnusable("invalid grant expiry")
            cause = rows[0]["closed"]
            if cause is not None and not isinstance(cause, str):
                raise GrantUnusable("invalid grant closure")
            if cause is None and time.time() >= expires:
                db.execute(
                    "UPDATE grant_record SET closed='expired',closed_at=?",
                    (int(time.time()),),
                )
                db.commit()
                db.execute("BEGIN IMMEDIATE")
                cause = "expired"
        except (GrantMissing, GrantUnusable):
            raise
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError) as exc:
            raise GrantUnusable("unusable accounting state") from exc
        yield db, config, cause
        try:
            db.commit()
        except (sqlite3.Error, OSError) as exc:
            raise GrantUnusable("cannot commit grant transaction") from exc


def stored_grant(root: Path, path: Path) -> tuple[dict, str | None]:
    private_path(root, directory=True)
    private_path(path, directory=False)
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=1)
    except (sqlite3.Error, OSError, ValueError) as exc:
        raise GrantUnusable("unusable accounting state") from exc
    with closing(conn) as db:
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=EXTRA")
            rows = db.execute("SELECT cfg, closed FROM grant_record").fetchall()
            if len(rows) != 1:
                raise GrantUnusable("invalid grant record")
            config = _decode_config(rows[0]["cfg"])
            closed = rows[0]["closed"]
            if closed is not None and not isinstance(closed, str):
                raise GrantUnusable("invalid grant closure")
            return config, closed
        except GrantUnusable:
            raise
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError) as exc:
            raise GrantUnusable("unusable accounting state") from exc
