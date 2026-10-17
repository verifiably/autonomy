import json

import pytest

from egress_fixtures import MODEL, pi_route, to_toml
from autonomy.egress.dialect import check_body, parse_body
from autonomy.egress.errors import Refused
from autonomy.egress.route import parse_route

OP = parse_route(to_toml(pi_route(credential="/nonexistent/credential")).encode()).operations[0]


def body(**extra) -> dict:
    return {"model": MODEL, "max_tokens": 16, "stream": True,
            "messages": [{"role": "user", "content": "hi"}], **extra}


def code_of(data: bytes) -> str:
    with pytest.raises(Refused) as caught:
        check_body(parse_body(data), OP)
    return caught.value.code


def test_a_plain_request_passes():
    check_body(parse_body(json.dumps(body()).encode()), OP)


@pytest.mark.parametrize("data", [
    b'{"model": "claude-haiku-5-5", "model": "claude-opus-5-5"}',
    b'{"model": "claude-haiku-5-5", "metadata": {"a": 1, "a": 2}}',
    b'\xef\xbb\xbf{"model": "claude-haiku-5-5"}',
    b'{"model": "claude-haiku-5-5", "temperature": NaN}',
    b'{"model": "claude-haiku-5-5", "temperature": Infinity}',
    b'["model"]',
    b'{"model": "claude-haiku-5-5", "x": "\xff"}',
    b'{"model": "claude-haiku-5-5", "system": "\\ud800"}',
    b'{"model": ' + b"[" * 100_000 + b"]" * 100_000 + b"}",
    b'{"model": "claude-haiku-5-5", "max_tokens": 1' + b"0" * 5000 + b"}",
    b"not json",
])
def test_strict_json(data):
    with pytest.raises(Refused) as caught:
        parse_body(data)
    assert caught.value.code == "request-malformed"


def test_a_model_outside_the_route():
    assert code_of(json.dumps(body(model="claude-opus-5-5")).encode()) == "model-refused"
    assert code_of(json.dumps({"messages": []}).encode()) == "model-refused"


@pytest.mark.parametrize("extra", [
    {"mcp_servers": [{"type": "url", "url": "https://attacker.example/mcp", "name": "x"}]},
    {"container": "container_123"},
    {"tools": [{"type": "web_fetch_20250910", "name": "web_fetch"}]},
    {"tools": [{"type": "web_search_20250305", "name": "web_search"}]},
    {"tools": [{"type": "custom", "name": "t", "input_schema": {"type": "object"}}]},
    {"messages": [{"role": "user", "content": [
        {"type": "image", "source": {"type": "url", "url": "https://attacker.example/x.png"}}]}]},
    {"messages": [{"role": "user", "content": [
        {"type": "document", "source": {"type": "file", "file_id": "file_1"}}]}]},
    {"messages": [{"role": "user", "content": [{"type": "search_result", "source": "https://x", "content": []}]}]},
    {"messages": [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t",
                                                 "content": [{"type": "search_result"}]}]}]},
    {"messages": [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": [
        {"type": "image", "source": {"type": "url", "url": "https://attacker.example/y.png"}}]}]}]},
    {"system": [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": ""}}]},
    {"tools": [{"type": ["web_fetch_20250910"], "name": "t"}]},
    {"messages": [{"role": "user", "content": [{"type": {"x": 1}}]}]},
])
def test_a_body_that_asks_the_provider_to_reach_out(extra):
    assert code_of(json.dumps(body(**extra)).encode()) == "body-refused"


def test_client_tools_without_a_type_pass():
    check_body(parse_body(json.dumps(body(tools=[{"name": "bash", "input_schema": {"type": "object"}}])).encode()), OP)


def test_a_tool_use_input_is_the_clients_data():
    # The positions are closed, not the whole body: a tool's input may hold anything.
    message = {"role": "assistant", "content": [
        {"type": "tool_use", "id": "t", "name": "fetch", "input": {"type": "url", "url": "https://x"}}]}
    check_body(parse_body(json.dumps(body(messages=[message])).encode()), OP)


def test_a_whole_body_walk_would_refuse_the_clients_data():
    # Negative (E21): the positions are closed, not the whole body. A walker that refuses
    # every {"type": "url"} anywhere refuses this request, which check_body passes.
    message = {"role": "assistant", "content": [
        {"type": "tool_use", "id": "t", "name": "fetch", "input": {"type": "url", "url": "https://x"}}]}
    data = body(messages=[message])

    def walk(value):
        if isinstance(value, dict):
            if value.get("type") == "url":
                raise Refused("body-refused", "a url anywhere")
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    check_body(parse_body(json.dumps(data).encode()), OP)
    with pytest.raises(Refused):
        walk(data)


def test_a_base64_image_passes():
    message = {"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}]}
    check_body(parse_body(json.dumps(body(messages=[message])).encode()), OP)


def test_nested_sources_are_checked_at_any_depth():
    doc = pi_route(credential="/nonexistent/credential")
    doc["operations"][0]["block_types"].append("document")
    doc["operations"][0]["source_types"].append("content")
    op = parse_route(to_toml(doc).encode()).operations[0]
    nested = {"role": "user", "content": [{"type": "document", "source": {"type": "content", "content": [
        {"type": "image", "source": {"type": "url", "url": "https://attacker.example/z.png"}}]}}]}
    with pytest.raises(Refused) as caught:
        check_body(parse_body(json.dumps(body(messages=[nested])).encode()), op)
    assert caught.value.code == "body-refused"
