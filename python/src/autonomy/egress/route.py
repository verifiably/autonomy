"""The model route (envelope design decision 13): operator configuration naming the
one upstream, the operations an actor may ask for, and the credential the proxy adds.
It is parsed strictly. An unknown key, an empty list the dialect needs, or a header
the proxy always drops makes the route `route-invalid`."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal
from urllib.parse import urlsplit

from autonomy.egress.errors import RouteRefused

DIALECTS = frozenset({"anthropic-messages"})
FEATURE_HEADERS: Mapping[str, frozenset[str]] = MappingProxyType(
    {"anthropic-messages": frozenset({"anthropic-beta", "anthropic-version"})}
)
"""Headers that switch provider features or select the body's shape: a route that
forwards one must list its tokens."""
KNOWN_BLOCK_TYPES = frozenset({"text", "image", "document", "tool_use", "tool_result", "thinking", "redacted_thinking"})
"""Block types whose nested positions `anthropic-messages` defines: only these may be listed."""
KNOWN_SOURCE_TYPES = frozenset({"base64", "text", "content", "url", "file"})
ALWAYS_DROPPED = frozenset(
    {
        "host", "forwarded",
        "x-api-key", "authorization", "proxy-authorization", "cookie", "set-cookie",
        "content-length", "transfer-encoding", "connection", "keep-alive", "te", "trailer", "upgrade", "expect",
    }
)
_ROUTE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_METHOD = re.compile(r"[A-Z]+")
_PATH = re.compile(r"/[\x21-\x7e]*")


def always_dropped(name: str) -> bool:
    lowered = name.lower()
    return lowered in ALWAYS_DROPPED or lowered.startswith("x-forwarded-")


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    queries: frozenset[str]
    models: frozenset[str]
    fields: frozenset[str]
    tool_types: frozenset[str]
    block_types: frozenset[str]
    source_types: frozenset[str]


@dataclass(frozen=True)
class Route:
    api: str
    host: str
    port: int
    ca_file: Path | None
    operations: tuple[Operation, ...]
    forward_headers: frozenset[str]
    header_tokens: Mapping[str, frozenset[str]]
    credential_file: Path
    credential_header: Literal["x-api-key", "authorization"]
    max_request_bytes: int

    @property
    def upstream(self) -> str:
        return f"https://{self.authority}"

    @property
    def authority(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return host if self.port == 443 else f"{host}:{self.port}"

    def operation(self, method: str, path: str, query: str) -> Operation | None:
        for op in self.operations:
            if op.method == method and op.path == path and query in op.queries:
                return op
        return None

    def describe(self) -> str:
        return ", ".join(
            f"{op.method} {op.path}" + (f"?{query}" if query else "")
            for op in self.operations
            for query in sorted(op.queries)
        )


def _invalid(message: str) -> RouteRefused:
    return RouteRefused("route-invalid", message)


def _table(value: object, where: str, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise _invalid(f"{where} must be a table")
    unknown = set(value) - required - set(optional)
    if unknown:
        raise _invalid(f"{where} has unknown keys: {', '.join(sorted(unknown))}")
    missing = required - set(value)
    if missing:
        raise _invalid(f"{where} lacks: {', '.join(sorted(missing))}")
    return value


def _strings(value: object, where: str, *, nonempty: bool) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _invalid(f"{where} must be a list of strings")
    if nonempty and not value:
        raise _invalid(f"{where} must not be empty")
    if len(set(value)) != len(value):
        raise _invalid(f"{where} repeats an entry")
    return value


def _absolute(value: object, where: str) -> Path:
    if not isinstance(value, str) or "\x00" in value or not Path(value).is_absolute():
        raise _invalid(f"{where} must be an absolute path")
    return Path(value)


def _upstream(value: object) -> tuple[str, int]:
    if not isinstance(value, str):
        raise _invalid("upstream must be a string")
    try:
        parts = urlsplit(value)
        port = parts.port
        hostname = parts.hostname
    except ValueError as caught:  # an unmatched IPv6 bracket, a port out of range
        raise _invalid(f"upstream {value!r} is not a URL: {caught}") from None
    if parts.scheme != "https" or not hostname:
        raise _invalid(f"upstream {value!r} must be one https origin")
    if parts.username is not None or parts.password is not None or parts.path or parts.query or parts.fragment:
        raise _invalid(f"upstream {value!r} must be an origin: no userinfo, path, query or fragment")
    return hostname, port or 443


def _headers(value: object, where: str) -> frozenset[str]:
    names = [name.lower() for name in _strings(value, where, nonempty=False)]
    if len(set(names)) != len(names):
        raise _invalid(f"{where} repeats a header (names compare case-insensitively)")
    for name in names:
        if not _TOKEN.fullmatch(name):
            raise _invalid(f"{where}: {name!r} is not a header name")
        if always_dropped(name):
            raise _invalid(f"{where}: {name} is always dropped and cannot be forwarded")
    return frozenset(names)


def _operation(value: object, where: str) -> Operation:
    table = _table(
        value, where,
        {"method", "path", "models", "fields", "block_types"},
        {"queries", "tool_types", "source_types"},
    )
    method = table["method"]
    if not isinstance(method, str) or not _METHOD.fullmatch(method):
        raise _invalid(f"{where}.method must be an upper-case HTTP method")
    path = table["path"]
    if not isinstance(path, str) or not _PATH.fullmatch(path) or "?" in path or "#" in path:
        raise _invalid(f"{where}.path must be an absolute path with no query")
    fields = _strings(table["fields"], f"{where}.fields", nonempty=True)
    if "model" not in fields:
        raise _invalid(f"{where}.fields must include model")
    blocks = _strings(table["block_types"], f"{where}.block_types", nonempty=True)
    undefined = set(blocks) - KNOWN_BLOCK_TYPES
    if undefined:
        raise _invalid(f"{where}.block_types: the dialect defines no nested positions for {sorted(undefined)}")
    sources = _strings(table.get("source_types", []), f"{where}.source_types", nonempty=False)
    if set(sources) - KNOWN_SOURCE_TYPES:
        raise _invalid(f"{where}.source_types: unknown {sorted(set(sources) - KNOWN_SOURCE_TYPES)}")
    return Operation(
        method=method,
        path=path,
        queries=frozenset(_strings(table.get("queries", [""]), f"{where}.queries", nonempty=True)),
        models=frozenset(_strings(table["models"], f"{where}.models", nonempty=True)),
        fields=frozenset(fields),
        tool_types=frozenset(_strings(table.get("tool_types", []), f"{where}.tool_types", nonempty=False)),
        block_types=frozenset(blocks),
        source_types=frozenset(sources),
    )


def parse_route(data: bytes) -> Route:
    try:
        doc = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as caught:
        raise _invalid(f"not UTF-8 TOML: {caught}") from None
    top = _table(
        doc, "the route",
        {"api", "upstream", "operations", "forward_headers", "credential", "max_request_bytes"},
        {"ca_file", "header_tokens"},
    )
    api = top["api"]
    if not isinstance(api, str) or api not in DIALECTS:
        raise _invalid(f"api {api!r} is not a dialect this build defines ({', '.join(sorted(DIALECTS))})")
    host, port = _upstream(top["upstream"])
    forward = _headers(top["forward_headers"], "forward_headers")
    tokens_table = top.get("header_tokens", {})
    if not isinstance(tokens_table, dict):
        raise _invalid("header_tokens must be a table")
    tokens: dict[str, frozenset[str]] = {}
    for name, values in tokens_table.items():
        lowered = name.lower()
        if lowered not in forward:
            raise _invalid(f"header_tokens names {name}, which is not forwarded")
        listed = _strings(values, f"header_tokens.{name}", nonempty=True)
        if not all(_TOKEN.fullmatch(token) for token in listed):
            raise _invalid(f"header_tokens.{name} holds a value that is not a token")
        tokens[lowered] = frozenset(listed)
    for name in FEATURE_HEADERS[api] & forward:
        if name not in tokens:
            raise _invalid(f"{name} switches provider features: forwarding it needs header_tokens.{name}")
    operations = top["operations"]
    if not isinstance(operations, list) or not operations:
        raise _invalid("the route needs at least one operation")
    parsed = tuple(_operation(op, f"operations[{i}]") for i, op in enumerate(operations))
    if len({(op.method, op.path) for op in parsed}) != len(parsed):
        raise _invalid("two operations share a method and path")
    credential = _table(top["credential"], "credential", {"file", "header"})
    header = credential["header"]
    if header not in ("x-api-key", "authorization"):
        raise _invalid("credential.header must be x-api-key or authorization")
    limit = top["max_request_bytes"]
    if type(limit) is not int or limit <= 0:
        raise _invalid("max_request_bytes must be a positive integer")
    return Route(
        api=api,
        host=host,
        port=port,
        ca_file=_absolute(top["ca_file"], "ca_file") if "ca_file" in top else None,
        operations=parsed,
        forward_headers=forward,
        header_tokens=MappingProxyType(tokens),
        credential_file=_absolute(credential["file"], "credential.file"),
        credential_header=header,
        max_request_bytes=limit,
    )


@dataclass(frozen=True)
class LoadedRoute:
    """The route as read at step 2: these bytes are digested into `baseline.json` and
    handed to the proxy, so the route enforced is the one recorded."""

    name: str
    path: Path
    data: bytes
    digest: str
    route: Route


def check_credential(path: Path) -> None:
    """Step 2's check of the credential file, by `fstat` on an `O_PATH` descriptor:
    the orchestrator never reads its bytes."""

    def refused(why: str) -> RouteRefused:
        return RouteRefused("credential-unavailable", f"{path}: {why}")

    try:
        fd = os.open(path, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        raise refused("missing") from None
    except OSError as caught:
        raise refused(caught.strerror or str(caught)) from None
    try:
        info = os.fstat(fd)
    finally:
        os.close(fd)
    if stat.S_ISLNK(info.st_mode):
        raise refused("a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise refused("not a regular file")
    if info.st_uid != os.getuid():
        raise refused(f"owned by uid {info.st_uid}, not {os.getuid()}")
    if info.st_nlink != 1:
        raise refused(f"has {info.st_nlink} links; a second name could sit in a bound directory")
    if info.st_mode & 0o077:
        raise refused(f"mode {stat.S_IMODE(info.st_mode):04o} has group or other permission bits")


def load_route(config: Path, name: str) -> LoadedRoute:
    if not _ROUTE_NAME.fullmatch(name):
        raise RouteRefused("route-unknown", f"{name!r} is not a route name ([a-z0-9][a-z0-9_-]*)")
    path = config / "routes" / f"{name}.toml"
    try:
        data = path.read_bytes()
        real = path.resolve(strict=True)
    except FileNotFoundError:
        raise RouteRefused("route-unknown", f"no route file {path}") from None
    except OSError as caught:
        raise RouteRefused("route-unknown", f"cannot read {path}: {caught.strerror}") from None
    route = parse_route(data)
    check_credential(route.credential_file)
    return LoadedRoute(name, real, data, hashlib.sha256(data).hexdigest(), route)


def egress_denied(config: Path, loaded: LoadedRoute) -> tuple[Path, ...]:
    """The denied set's entries for a run with this route (decision 13, spec §7)."""
    return (config.resolve(), loaded.path, loaded.route.credential_file.resolve())
