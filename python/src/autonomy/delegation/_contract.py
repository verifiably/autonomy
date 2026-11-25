"""Closed fields, canonical ref grammar, and resource bounds of a development delegation."""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from autonomy.run import RunRefused

KIND = "development-delegation.v1"
TERMINATION_SECONDS = 15
_MAXIMUM = 2**53 - 1
_MIB = 1 << 20
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_UNIT = re.compile(r"[A-Za-z0-9:_.@\\-]{1,247}\.service")
_FORBIDDEN_REF_CHARS = frozenset(" ~^:?*[\\")


@dataclass(frozen=True)
class Ceiling:
    prepared_bytes: int
    storage_bytes: int
    storage_inodes: int
    receiver_bytes: int
    prepare_seconds: int


def _refuse(code: str, message: str) -> RunRefused:
    return RunRefused(code, message)


def _require(condition: object, message: str, code: str = "delegation-invalid") -> None:
    if not condition:
        raise _refuse(code, message)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def identifier(value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise _refuse("delegation-invalid", "invalid delegation identifier")
    return value


def valid_unit(value: object) -> str:
    if type(value) is not str or _UNIT.fullmatch(value) is None:
        raise _refuse("delegation-invalid", "invalid systemd user service unit name")
    return value


def _positive_int(value: object, code: str) -> int:
    if type(value) is not int or not (1 <= value <= _MAXIMUM):
        raise _refuse(code, "limit must be a positive integer")
    return value


def _valid_ref(value: object) -> str:
    if type(value) is not str or not value.startswith("refs/heads/"):
        raise _refuse("delegation-invalid", "ref must be a full refs/heads/ branch name")
    branch = value[len("refs/heads/"):]
    if not branch or value.endswith(".") or ".." in value or "@{" in value:
        raise _refuse("delegation-invalid", "ref is not in canonical Git branch form")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F or ch in _FORBIDDEN_REF_CHARS for ch in value):
        raise _refuse("delegation-invalid", "ref contains a control or Git-reserved character")
    for part in branch.split("/"):
        if not part or part.startswith(".") or part.endswith(".lock"):
            raise _refuse("delegation-invalid", "ref has an invalid path component")
    return value


def _canonical_repo_path(value: object) -> str:
    if type(value) is not str or "\x00" in value:
        raise _refuse("delegation-invalid", "repository path must be a canonical absolute directory")
    path = Path(value)
    if not path.is_absolute() or os.path.normpath(value) != value:
        raise _refuse("delegation-invalid", "repository path must be canonical and absolute")
    try:
        resolved = path.resolve(strict=True)
        is_dir = resolved.is_dir()
    except OSError as exc:
        raise _refuse("delegation-invalid", f"repository path is unavailable: {exc}") from exc
    if resolved != path or not is_dir:
        raise _refuse("delegation-invalid", "repository path must be a canonical existing directory")
    return value


def memory_floor(writable_bytes: int, ceiling: Ceiling) -> int:
    return writable_bytes + 2048 * ceiling.storage_inodes + 64 * _MIB


def peak_memory(limits: Mapping[str, int], ceiling: Ceiling) -> int:
    return limits["memory_bytes"] + limits["writable_bytes"] + ceiling.receiver_bytes


def _check_limits(value: object, ceiling: Ceiling, code: str) -> dict[str, int]:
    expected = {"starts", "deadline_seconds", "writable_bytes", "memory_bytes", "tasks"}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise _refuse(code, "limits must declare starts, deadline_seconds, writable_bytes, memory_bytes and tasks")
    parsed = {key: _positive_int(value[key], code) for key in expected}
    writable = parsed["writable_bytes"]
    page = os.sysconf("SC_PAGE_SIZE")
    _require(
        ceiling.prepared_bytes <= writable <= ceiling.storage_bytes and writable % page == 0,
        "writable_bytes is outside bounds or not page-aligned",
        code,
    )
    _require(
        parsed["memory_bytes"] >= memory_floor(writable, ceiling),
        "memory_bytes is below the required floor for writable_bytes and inodes",
        code,
    )
    _require(parsed["tasks"] >= 16, "tasks must be at least 16", code)
    return parsed


def within(limits: Mapping[str, int], ceiling: Ceiling) -> None:
    _check_limits(limits, ceiling, "delegation-bounds")


def definition(value: object, ceiling: Ceiling) -> dict:
    fields = {
        "kind",
        "delegation_id",
        "source",
        "expires",
        "orchestrator",
        "repositories",
        "actors",
        "limits",
        "model",
    }
    _require(type(value) is dict and set(value) == fields, "grant has missing or unexpected fields")
    assert isinstance(value, dict)
    _require(value["kind"] == KIND, f"grant kind must be {KIND}")
    delegation_id = identifier(value["delegation_id"])
    source = value["source"]
    _require(type(source) is str and bool(source.strip()), "grant source is required")
    expires = _positive_int(value["expires"], "delegation-invalid")

    orchestrator = value["orchestrator"]
    _require(
        type(orchestrator) is dict and set(orchestrator) == {"name", "unit"},
        "orchestrator must name name and unit",
    )
    orch_name = identifier(orchestrator["name"])
    unit = valid_unit(orchestrator["unit"])

    repositories = value["repositories"]
    _require(type(repositories) is dict and len(repositories) >= 1, "at least one repository is required")
    parsed_repos: dict[str, dict[str, str]] = {}
    seen_paths: set[str] = set()
    for name, entry in repositories.items():
        repo_name = identifier(name)
        _require(type(entry) is dict and set(entry) == {"path", "ref"}, "repository entry requires path and ref")
        repo_path = _canonical_repo_path(entry["path"])
        _require(repo_path not in seen_paths, "duplicate repository path in grant")
        seen_paths.add(repo_path)
        parsed_repos[repo_name] = {"path": repo_path, "ref": _valid_ref(entry["ref"])}

    actors = value["actors"]
    _require(type(actors) is dict and len(actors) >= 1, "at least one actor is required")
    parsed_actors: dict[str, list[str]] = {}
    seen_argvs: set[tuple[str, ...]] = set()
    for name, argv in actors.items():
        actor_name = identifier(name)
        _require(
            type(argv) is list
            and len(argv) >= 1
            and all(type(arg) is str and "\x00" not in arg for arg in argv)
            and bool(argv[0]),
            "actor command must be a non-empty string array",
        )
        frozen = tuple(argv)
        _require(frozen not in seen_argvs, "duplicate actor command in grant")
        seen_argvs.add(frozen)
        parsed_actors[actor_name] = list(argv)

    limits = _check_limits(value["limits"], ceiling, "delegation-invalid")
    _require(value["model"] is None, "model must be null")
    return {
        "kind": KIND,
        "delegation_id": delegation_id,
        "source": source,
        "expires": expires,
        "orchestrator": {"name": orch_name, "unit": unit},
        "repositories": parsed_repos,
        "actors": parsed_actors,
        "limits": limits,
        "model": None,
    }
