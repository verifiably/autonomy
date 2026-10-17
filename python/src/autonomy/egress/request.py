"""Strict HTTP/1.1 on the actor's side, and the request the proxy frames itself for the
upstream (envelope design decision 13). Nothing the actor sends about framing, hops or
destinations crosses: the target must be origin-form, the body comes with one
`Content-Length`, and the proxy writes `Host`, the credential and its own length."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from autonomy.egress.errors import Refused
from autonomy.egress.route import Route

MAX_HEAD = 64 * 1024
_TCHAR = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_METHOD = re.compile(rb"[A-Z]+")
_TARGET = re.compile(rb"/[\x21-\x7e]*")
_VALUE = re.compile(rb"[\t\x20-\x7e\x80-\xff]*")
_DIGITS = re.compile(r"[0-9]{1,15}")


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    query: str
    headers: tuple[tuple[str, str], ...]
    content_length: int


def _malformed(message: str) -> Refused:
    return Refused("request-malformed", message)


def parse_head(head: bytes) -> Request:
    lines = head.split(b"\r\n")
    parts = lines[0].split(b" ")
    if len(parts) != 3:
        raise _malformed("the request line is not METHOD TARGET HTTP/1.1")
    method, target, version = parts
    if not _METHOD.fullmatch(method):
        raise _malformed("the method is not an upper-case token")
    if method == b"CONNECT":
        raise Refused("target-refused", "CONNECT is refused: the proxy opens no tunnel")
    if version != b"HTTP/1.1":
        raise _malformed("the version is not HTTP/1.1")
    if not _TARGET.fullmatch(target):
        raise Refused("target-refused", "only an origin-form target (/path) is accepted")
    if b"#" in target:
        raise _malformed("a request target carries no fragment")
    path, _, query = target.decode("ascii").partition("?")
    headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        if not line or line[:1] in (b" ", b"\t"):
            raise _malformed("an empty or folded header line")
        name, colon, value = line.partition(b":")
        if not colon or not _TCHAR.fullmatch(name):
            raise _malformed("a header line is not NAME: VALUE")
        value = value.strip(b" \t")
        if not _VALUE.fullmatch(value):
            raise _malformed(f"header {name.decode('ascii')} holds a control character")
        headers.append((name.decode("ascii").lower(), value.decode("latin-1")))
    names = [name for name, _ in headers]
    if "transfer-encoding" in names:
        raise _malformed("a request body must come with Content-Length; Transfer-Encoding is refused")
    if "upgrade" in names:
        raise Refused("target-refused", "Upgrade is refused: the proxy forwards no other protocol")
    lengths = [value for name, value in headers if name == "content-length"]
    if len(lengths) > 1:
        raise _malformed("Content-Length is repeated")
    if lengths and not _DIGITS.fullmatch(lengths[0]):
        raise _malformed("Content-Length is not a decimal number")
    return Request(method.decode("ascii"), path, query, tuple(headers), int(lengths[0]) if lengths else 0)


def connection_named(headers: tuple[tuple[str, str], ...]) -> frozenset[str]:
    """The headers a `Connection` header names: hop-by-hop, so always dropped."""
    return frozenset(
        token.strip(" \t").lower()
        for name, value in headers if name == "connection"
        for token in value.split(",") if token.strip(" \t")
    )


def forwarded_headers(request: Request, route: Route) -> tuple[tuple[str, str], ...]:
    """The route's `forward_headers`, each once, less any header `Connection` names.
    Every other header is dropped. A repeated forwarded header, or a token outside
    `header_tokens`, is refused."""
    counts = Counter(name for name, _ in request.headers)
    hop = connection_named(request.headers)
    kept: list[tuple[str, str]] = []
    for name, value in request.headers:
        if name not in route.forward_headers or name in hop:
            continue
        if counts[name] > 1:
            raise Refused("header-refused", f"header {name} is repeated")
        allowed = route.header_tokens.get(name)
        if allowed is not None:
            tokens = [token.strip(" \t") for token in value.split(",")]
            outside = [token for token in tokens if token not in allowed]
            if outside:
                raise Refused("header-refused", f"header {name} holds {outside}; the route allows {sorted(allowed)}")
        kept.append((name, value))
    return tuple(kept)


def frame(request: Request, route: Route, headers: tuple[tuple[str, str], ...], body: bytes, credential: str) -> bytes:
    target = request.path + (f"?{request.query}" if request.query else "")
    lines = [f"{request.method} {target} HTTP/1.1", f"host: {route.authority}"]
    lines += [f"{name}: {value}" for name, value in headers]
    if route.credential_header == "x-api-key":
        lines.append(f"x-api-key: {credential}")
    else:
        lines.append(f"authorization: Bearer {credential}")
    lines += [f"content-length: {len(body)}", "connection: close"]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


def refusal(code: str, message: str) -> bytes:
    body = json.dumps({"type": "error", "error": {"type": "egress_refused", "code": code, "message": message}}).encode()
    head = (
        "HTTP/1.1 403 Forbidden\r\ncontent-type: application/json\r\n"
        f"content-length: {len(body)}\r\nconnection: close\r\n\r\n"
    )
    return head.encode("ascii") + body
