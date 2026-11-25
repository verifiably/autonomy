"""Read a local Git branch ref directly without running Git or following symlinks."""

from __future__ import annotations

import errno
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from autonomy.run import RunRefused

_OPEN_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_OPEN_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_MAX_PACKED_REFS = 32 * 1024 * 1024
_MAX_LOOSE_REF = 256
_OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_FORBIDDEN_REF_CHARS = frozenset(" ~^:?*[\\")


def _refuse(detail: str, cause: BaseException | None = None) -> RunRefused:
    err = RunRefused("delegation-base", detail)
    if cause is not None:
        err.__cause__ = cause
    return err


def _validate_ref(ref: str) -> tuple[tuple[str, ...], str]:
    if type(ref) is not str or not ref.startswith("refs/heads/"):
        raise _refuse("ref must be a full refs/heads/ branch name")
    branch = ref[len("refs/heads/"):]
    if not branch or ref.endswith(".") or ".." in ref or "@{" in ref:
        raise _refuse("ref is not in canonical Git branch form")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F or ch in _FORBIDDEN_REF_CHARS for ch in ref):
        raise _refuse("ref contains a control or Git-reserved character")
    parts = branch.split("/")
    for part in parts:
        if not part or part.startswith(".") or part.endswith(".lock"):
            raise _refuse("ref has an invalid path component")
    full_parts = ref.split("/")
    return tuple(full_parts[:-1]), full_parts[-1]


@contextmanager
def _open_admin(repository: Path) -> Iterator[int]:
    raw = str(repository)
    if not repository.is_absolute() or "\x00" in raw or os.path.normpath(raw) != raw:
        raise _refuse("repository path is not canonical")
    try:
        directory = os.open(repository.anchor, _OPEN_DIR)
    except OSError as exc:
        raise _refuse(f"cannot open repository root: {exc}", exc) from exc
    try:
        for part in repository.parts[1:]:
            nxt = os.open(part, _OPEN_DIR, dir_fd=directory)
            os.close(directory)
            directory = nxt

        try:
            dotgit_info = os.stat(".git", dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            admin = directory
        else:
            if not stat.S_ISDIR(dotgit_info.st_mode):
                raise _refuse("repository .git must be a directory")
            admin = os.open(".git", _OPEN_DIR, dir_fd=directory)
            os.close(directory)
            directory = admin

        head_info = os.stat("HEAD", dir_fd=directory, follow_symlinks=False)
        if not stat.S_ISREG(head_info.st_mode):
            raise _refuse("repository HEAD is not a regular file")
        try:
            os.stat("reftable", dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise _refuse("reftable repositories are not supported")

        yield directory
    except RunRefused:
        raise
    except OSError as exc:
        raise _refuse(f"cannot open repository metadata: {exc}", exc) from exc
    finally:
        os.close(directory)


def _read_bounded(fd: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, min(65536, limit + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            raise _refuse("ref file exceeds maximum size")
    return b"".join(chunks)


def _loose_tip(admin_fd: int, dir_parts: tuple[str, ...], leaf: str) -> str | None:
    current = os.dup(admin_fd)
    try:
        for part in dir_parts:
            try:
                nxt = os.open(part, _OPEN_DIR, dir_fd=current)
            except FileNotFoundError:
                return None
            except OSError as exc:
                raise _refuse(f"cannot traverse loose ref directory {part}: {exc}", exc) from exc
            os.close(current)
            current = nxt

        try:
            fd = os.open(leaf, _OPEN_FILE, dir_fd=current)
        except FileNotFoundError:
            return None
        except OSError as exc:
            if exc.errno == errno.EISDIR:
                raise _refuse(f"ref {leaf} is a directory", exc) from exc
            raise _refuse(f"cannot open loose ref {leaf}: {exc}", exc) from exc

        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise _refuse("loose ref is not a regular file")
            raw = _read_bounded(fd, _MAX_LOOSE_REF)
        finally:
            os.close(fd)
    finally:
        os.close(current)

    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise _refuse("loose ref is not ASCII", exc) from exc
    line = text[:-1] if text.endswith("\n") else text
    if line.startswith("ref:") or _OID.fullmatch(line) is None:
        raise _refuse("loose ref does not hold one full commit OID")
    return line


def _packed_tip(admin_fd: int, ref: str) -> str:
    try:
        fd = os.open("packed-refs", _OPEN_FILE, dir_fd=admin_fd)
    except FileNotFoundError:
        raise _refuse(f"ref {ref} is absent") from None
    except OSError as exc:
        raise _refuse(f"cannot open packed-refs: {exc}", exc) from exc

    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _refuse("packed-refs is not a regular file")
        if info.st_size > _MAX_PACKED_REFS:
            raise _refuse("packed-refs exceeds 32 MiB")
        raw = _read_bounded(fd, _MAX_PACKED_REFS)
    finally:
        os.close(fd)

    if not raw:
        raise _refuse(f"ref {ref} is absent")
    if not raw.endswith(b"\n"):
        raise _refuse("packed-refs is truncated")
    try:
        lines = raw[:-1].decode("utf-8").split("\n")
    except UnicodeDecodeError as exc:
        raise _refuse("packed-refs is not valid UTF-8", exc) from exc

    found: str | None = None
    saw_entry = False
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if line.startswith("^"):
            if not saw_entry or _OID.fullmatch(line[1:]) is None:
                raise _refuse("malformed peeled line in packed-refs")
            continue
        oid, sep, name = line.partition(" ")
        if sep != " " or _OID.fullmatch(oid) is None or not name or any(ch.isspace() for ch in name):
            raise _refuse("malformed entry in packed-refs")
        saw_entry = True
        if name == ref:
            if found is not None and found != oid:
                raise _refuse(f"conflicting entries for {ref} in packed-refs")
            found = oid

    if found is None:
        raise _refuse(f"ref {ref} is absent")
    return found


def branch_tip(repository: Path, ref: str) -> str:
    dir_parts, leaf = _validate_ref(ref)
    with _open_admin(repository) as admin_fd:
        loose = _loose_tip(admin_fd, dir_parts, leaf)
        if loose is not None:
            return loose
        return _packed_tip(admin_fd, ref)
