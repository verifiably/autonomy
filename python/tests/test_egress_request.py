import json

import pytest

from egress_fixtures import pi_route, to_toml
from autonomy.egress.errors import Refused
from autonomy.egress.request import forwarded_headers, frame, parse_head, refusal
from autonomy.egress.route import parse_route

ROUTE = parse_route(to_toml(pi_route(credential="/nonexistent/credential")).encode())


def head(*lines: str) -> bytes:
    return "\r\n".join(lines).encode("latin-1")


def refused(raw: bytes) -> str:
    with pytest.raises(Refused) as caught:
        parse_head(raw)
    return caught.value.code


def test_a_well_formed_request():
    request = parse_head(head(
        "POST /v1/messages?beta=true HTTP/1.1", "Host: 127.0.0.1:4780",
        "Content-Length: 12", "Anthropic-Version:  2023-06-01 ",
    ))
    assert (request.method, request.path, request.query, request.content_length) == (
        "POST", "/v1/messages", "beta=true", 12,
    )
    assert ("anthropic-version", "2023-06-01") in request.headers


@pytest.mark.parametrize(("raw", "code"), [
    (head("CONNECT api.anthropic.com:443 HTTP/1.1", "Host: x"), "target-refused"),
    (head("POST http://other/v1/messages HTTP/1.1", "Host: x"), "target-refused"),
    (head("POST other:443 HTTP/1.1", "Host: x"), "target-refused"),
    (head("OPTIONS * HTTP/1.1", "Host: x"), "target-refused"),
    (head("POST /v1/messages HTTP/1.1", "Upgrade: h2c"), "target-refused"),
    (head("POST /v1/messages HTTP/1.0", "Host: x"), "request-malformed"),
    (head("POST /v1/messages  HTTP/1.1", "Host: x"), "request-malformed"),
    (head("post /v1/messages HTTP/1.1", "Host: x"), "request-malformed"),
    (head("POST /v1/messages#frag HTTP/1.1", "Host: x"), "request-malformed"),
    (head("POST /v1/messages HTTP/1.1", "Host: x", " folded"), "request-malformed"),
    (head("POST /v1/messages HTTP/1.1", "Host : x"), "request-malformed"),
    (head("POST /v1/messages HTTP/1.1", "X-Bad: a\x00b"), "request-malformed"),
    (head("POST /v1/messages HTTP/1.1", "Transfer-Encoding: chunked"), "request-malformed"),
    (head("POST /v1/messages HTTP/1.1", "Content-Length: 5", "Content-Length: 5"), "request-malformed"),
    (head("POST /v1/messages HTTP/1.1", "Content-Length: +5"), "request-malformed"),
    (head("POST /v1/messages HTTP/1.1", "Content-Length: 1e3"), "request-malformed"),
])
def test_refused_heads(raw, code):
    assert refused(raw) == code


def test_paths_are_kept_byte_for_byte():
    for target in ("/v1/messages/../x", "/v1/%2e%2e/x", "//other/v1/messages", "/v1/messages/./"):
        request = parse_head(head(f"POST {target} HTTP/1.1", "Host: x"))
        assert request.path == target
        assert ROUTE.operation("POST", request.path, request.query) is None


def test_unlisted_headers_are_dropped_and_listed_ones_kept():
    request = parse_head(head(
        "POST /v1/messages?beta=true HTTP/1.1", "Host: other", "X-Forwarded-Host: other",
        "X-Probe: 1", "x-api-key: placeholder", "Authorization: Bearer sk-ant-oat-placeholder",
        "Connection: x-api-key", "Content-Type: application/json", "Content-Length: 2",
    ))
    assert forwarded_headers(request, ROUTE) == (("content-type", "application/json"),)


def test_a_header_that_connection_names_is_dropped():
    request = parse_head(head(
        "POST /v1/messages?beta=true HTTP/1.1", "Connection: User-Agent, close",
        "User-Agent: pi", "Content-Type: application/json",
    ))
    assert forwarded_headers(request, ROUTE) == (("content-type", "application/json"),)


@pytest.mark.parametrize("lines", [
    ("anthropic-beta: interleaved-thinking-2025-05-14", "anthropic-beta: mcp-client-2025-04-04"),
    ("Anthropic-Beta: interleaved-thinking-2025-05-14", "anthropic-beta: interleaved-thinking-2025-05-14"),
    ("anthropic-beta: interleaved-thinking-2025-05-14, mcp-client-2025-04-04",),
    ("anthropic-version: 2099-01-01",),
])
def test_feature_headers_are_checked_token_by_token(lines):
    request = parse_head(head("POST /v1/messages?beta=true HTTP/1.1", *lines))
    with pytest.raises(Refused) as caught:
        forwarded_headers(request, ROUTE)
    assert caught.value.code == "header-refused"


def test_tokens_are_trimmed_of_optional_whitespace():
    request = parse_head(head(
        "POST /v1/messages?beta=true HTTP/1.1",
        "anthropic-beta:  interleaved-thinking-2025-05-14 ,\tfine-grained-tool-streaming-2025-05-14",
    ))
    assert len(forwarded_headers(request, ROUTE)) == 1


def test_the_proxy_frames_the_upstream_request_itself():
    request = parse_head(head("POST /v1/messages?beta=true HTTP/1.1", "Host: other", "Content-Length: 2"))
    raw = frame(request, ROUTE, (("anthropic-version", "2023-06-01"),), b"{}", "sk-canary")
    head_part, _, body = raw.partition(b"\r\n\r\n")
    lines = head_part.decode().split("\r\n")
    assert lines[0] == "POST /v1/messages?beta=true HTTP/1.1"
    assert lines[1:] == [
        "host: api.anthropic.com", "anthropic-version: 2023-06-01", "x-api-key: sk-canary",
        "content-length: 2", "connection: close",
    ]
    assert body == b"{}"


def test_a_bearer_route_sends_authorization():
    doc = pi_route(credential="/nonexistent/credential")
    doc["credential"]["header"] = "authorization"
    route = parse_route(to_toml(doc).encode())
    request = parse_head(head("POST /v1/messages HTTP/1.1"))
    assert b"authorization: Bearer sk-canary\r\n" in frame(request, route, (), b"", "sk-canary")


def test_a_refusal_names_its_code():
    raw = refusal("operation-refused", "allowed: POST /v1/messages?beta=true")
    head_part, _, body = raw.partition(b"\r\n\r\n")
    assert head_part.startswith(b"HTTP/1.1 403 Forbidden\r\n")
    assert b"connection: close" in head_part
    assert json.loads(body) == {"type": "error", "error": {
        "type": "egress_refused", "code": "operation-refused", "message": "allowed: POST /v1/messages?beta=true",
    }}
