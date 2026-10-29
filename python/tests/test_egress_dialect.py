import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

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


# Literal fixtures from decision 13, independent of the validator's key tables.
ALL_OP = replace(OP, block_types=frozenset({"text", "image", "document", "tool_use", "tool_result",
                                           "thinking", "redacted_thinking"}),
                 source_types=frozenset({"base64", "text", "content", "url", "file"}),
                 tool_types=frozenset({"custom"}))
SOURCES = {
    "png": {"type": "base64", "media_type": "image/png", "data": "AAAA"},
    "jpeg": {"type": "base64", "media_type": "image/jpeg", "data": "AAAA"},
    "gif": {"type": "base64", "media_type": "image/gif", "data": "AAAA"},
    "webp": {"type": "base64", "media_type": "image/webp", "data": "AAAA"},
    "pdf": {"type": "base64", "media_type": "application/pdf", "data": "AAAA"},
    "text": {"type": "text", "media_type": "text/plain", "data": "hello"},
    "content": {"type": "content", "content": []},
    "url": {"type": "url", "url": "https://synthetic.invalid/image"},
    "file": {"type": "file", "file_id": "synthetic"},
}
BLOCKS = {
    "text": {"type": "text", "text": "hello"},
    "image": {"type": "image", "source": SOURCES["png"]},
    "document": {"type": "document", "source": SOURCES["text"]},
    "tool_use": {"type": "tool_use", "id": "t", "name": "local", "input": {}},
    "tool_result": {"type": "tool_result", "tool_use_id": "t"},
    "thinking": {"type": "thinking", "thinking": "thought", "signature": "sig"},
    "redacted_thinking": {"type": "redacted_thinking", "data": "redacted"},
}
TOOL = {"name": "local", "input_schema": {}}
BLOCK_PATH = ("messages", 0, "content", 0)


def block_body(block):
    return body(messages=[{"role": "user", "content": [deepcopy(block)]}])


def at(payload, path):
    for key in path:
        payload = payload[key]
    return payload


def control_cases():
    cases = [("root", body(), (), ("model", "messages", "max_tokens"))]
    for role in ("user", "assistant", "system"):
        cases.append((role, body(messages=[{"role": role, "content": []}]),
                      ("messages", 0), ("role", "content")))
    for kind, block in BLOCKS.items():
        cases.append((kind, block_body(block), BLOCK_PATH, tuple(block)))
    for name, source in SOURCES.items():
        parent = "image" if name in {"png", "jpeg", "gif", "webp"} else "document"
        cases.append((f"source-{name}", block_body({"type": parent, "source": source}),
                      (*BLOCK_PATH, "source"), tuple(source)))
    cases += [
        ("tool", body(tools=[TOOL]), ("tools", 0), ("name", "input_schema")),
        ("cache", block_body({**BLOCKS["text"], "cache_control": {"type": "ephemeral"}}),
         (*BLOCK_PATH, "cache_control"), ("type",)),
        ("citations", block_body({**BLOCKS["document"], "citations": {}}), (*BLOCK_PATH, "citations"), ()),
        ("effort", body(output_config={}), ("output_config",), ()),
        ("message-effort", body(messages=[{"role": "system", "content": [], "output_config": {}}]),
         ("messages", 0, "output_config"), ()),
        ("metadata", body(metadata={}), ("metadata",), ()),
        ("binding", body(thinking={"type": "adaptive", "block_binding": {}}),
         ("thinking", "block_binding"), ()),
    ]
    for kind in ("disabled", "between_tools", "adaptive", "enabled"):
        obj = {"type": kind}
        if kind == "enabled":
            obj["budget_tokens"] = 16
        cases.append((f"thinking-{kind}", body(thinking=obj), ("thinking",), tuple(obj)))
    for kind in ("auto", "any", "tool", "none"):
        obj = {"type": kind}
        if kind == "tool":
            obj["name"] = "not-defined-in-this-request"
        cases.append((f"choice-{kind}", body(tool_choice=obj), ("tool_choice",), tuple(obj)))
    return cases


CONTROLS = control_cases()


@pytest.mark.parametrize("name,payload,path,required", CONTROLS, ids=[c[0] for c in CONTROLS])
def test_control_object_key_sets(name, payload, path, required):
    assert check_body(parse_body(json.dumps(payload).encode()), ALL_OP) is None
    altered = deepcopy(payload)
    at(altered, path)["future_feature"] = {"tools": []}
    with pytest.raises(Refused) as caught:
        check_body(parse_body(json.dumps(altered).encode()), ALL_OP)
    assert caught.value.code == "body-refused"


@pytest.mark.parametrize("payload,path,key", [
    pytest.param(payload, path, key, id=f"{name}-{key}")
    for name, payload, path, required in CONTROLS for key in required
])
def test_required_fields_and_nullable_leaves_missing(payload, path, key):
    altered = deepcopy(payload)
    del at(altered, path)[key]
    with pytest.raises(Refused) as caught:
        check_body(parse_body(json.dumps(altered).encode()), ALL_OP)
    assert caught.value.code == ("model-refused" if not path and key == "model" else "body-refused")


@pytest.mark.parametrize("payload,path,key", [
    pytest.param(payload, path, key, id=f"{name}-{key}")
    for name, payload, path, required in CONTROLS for key in required if key not in {"input", "input_schema"}
])
def test_required_fields_and_nullable_leaves_wrong_type(payload, path, key):
    altered = deepcopy(payload)
    at(altered, path)[key] = None
    with pytest.raises(Refused) as caught:
        check_body(parse_body(json.dumps(altered).encode()), ALL_OP)
    assert caught.value.code == ("model-refused" if not path and key == "model" else "body-refused")


def optional_cases():
    cases = []

    def add(name, payload, path, key, accepted, refused):
        for verdict, values in ((True, accepted), (False, refused)):
            for index, value in enumerate(values):
                changed = deepcopy(payload)
                at(changed, path)[key] = value
                cases.append(pytest.param(changed, verdict, id=f"{name}-{key}-{verdict}-{index}"))

    for kind in ("text", "image", "document", "tool_use", "tool_result"):
        add(kind, block_body(BLOCKS[kind]), BLOCK_PATH, "cache_control",
            [None, {"type": "ephemeral"}, {"type": "ephemeral", "ttl": "1h"}], [True, {}, []])
    add("tool", body(tools=[TOOL]), ("tools", 0), "cache_control", [None, {"type": "ephemeral"}], [{}, "5m"])
    for key in ("title", "context"):
        add("document", block_body(BLOCKS["document"]), BLOCK_PATH, key, [None, ""], [True, {}])
    add("document", block_body(BLOCKS["document"]), BLOCK_PATH, "citations",
        [None, {}, {"enabled": True}, {"enabled": False}], [[], True, {"enabled": None}, {"enabled": 1}])
    add("tool_result", block_body(BLOCKS["tool_result"]), BLOCK_PATH, "content", ["", []], [None, {}])
    add("tool_result", block_body(BLOCKS["tool_result"]), BLOCK_PATH, "is_error", [True, False], [None, 1])
    for key in ("strict", "defer_loading"):
        add("tool", body(tools=[TOOL]), ("tools", 0), key, [True, False], [None, 1, "true"])
    add("tool", body(tools=[TOOL]), ("tools", 0), "description", [""], [None, True])
    add("tool", body(tools=[TOOL]), ("tools", 0), "eager_input_streaming", [True, False, None], [1, "true"])
    add("tool", body(tools=[TOOL]), ("tools", 0), "type", ["custom"], [None, "server", {}, []])
    add("metadata", body(metadata={}), ("metadata",), "user_id", [None, "id"], [1, {}])
    for kind in ("enabled", "adaptive"):
        thinking = {"type": kind, **({"budget_tokens": 1} if kind == "enabled" else {})}
        add(kind, body(thinking=thinking), ("thinking",), "display",
            [None, "summarized", "omitted", "updates"], ["future", True, {}])
        add(kind, body(thinking=thinking), ("thinking",), "block_binding",
            [None, {}, {"prefix_mismatch_behavior": "error"}, {"prefix_mismatch_behavior": "drop_block"},
             {"prefix_mismatch_behavior": None}], [[], True, {"prefix_mismatch_behavior": "future"}])
    for kind in ("auto", "any", "tool"):
        choice = {"type": kind, **({"name": "local"} if kind == "tool" else {})}
        add(kind, body(tool_choice=choice), ("tool_choice",), "disable_parallel_tool_use",
            [True, False], [None, 0, "false"])
    add("effort", body(output_config={}), ("output_config",), "effort",
        [None, "low", "medium", "high", "xhigh", "max"], ["future", True, {}])
    add("cache", block_body({**BLOCKS["text"], "cache_control": {"type": "ephemeral"}}),
        (*BLOCK_PATH, "cache_control"), "ttl", ["5m", "1h"], [None, "future", 5])
    return cases


@pytest.mark.parametrize("payload,accept", optional_cases())
def test_required_fields_and_nullable_leaves_optional(payload, accept):
    if accept:
        assert check_body(parse_body(json.dumps(payload).encode()), ALL_OP) is None
    else:
        with pytest.raises(Refused) as caught:
            check_body(parse_body(json.dumps(payload).encode()), ALL_OP)
        assert caught.value.code == "body-refused"


@pytest.mark.parametrize("key", ["messages", "max_tokens", "system", "stream", "tools", "tool_choice",
                                  "thinking", "temperature", "metadata", "stop_sequences", "top_p", "top_k",
                                  "output_config"])
def test_required_fields_and_nullable_leaves_top_null(key):
    with pytest.raises(Refused) as caught:
        check_body(body(**{key: None}), ALL_OP)
    assert caught.value.code == "body-refused"


@pytest.mark.parametrize("role", ["user", "assistant", "system"])
@pytest.mark.parametrize("config", [None, {}, {"effort": "high"}])
def test_system_effort_needs_route_permission(role, config):
    payload = body(messages=[{"role": role, "content": [], "output_config": config}])
    if role == "system":
        assert check_body(payload, OP) is None
    else:
        with pytest.raises(Refused) as caught:
            check_body(payload, OP)
        assert caught.value.code == "body-refused"
    with pytest.raises(Refused) as caught:
        check_body(payload, replace(OP, fields=OP.fields - {"output_config"}))
    assert caught.value.code == "body-refused"


@pytest.mark.parametrize("context", ["user", "assistant", "system", "top-system", "result", "document"])
@pytest.mark.parametrize("kind", list(BLOCKS))
def test_nested_permissions_and_contexts_blocks(context, kind):
    block = deepcopy(BLOCKS[kind])
    if context == "top-system":
        payload, allowed = body(system=[block]), {"text"}
    elif context == "result":
        payload, allowed = block_body({**BLOCKS["tool_result"], "content": [block]}), {"text", "image", "document"}
    elif context == "document":
        payload, allowed = block_body({"type": "document", "source": {"type": "content", "content": [block]}}), {"text", "image"}
    else:
        payload, allowed = body(messages=[{"role": context, "content": [block]}]), set(BLOCKS)
    if kind in allowed:
        assert check_body(payload, ALL_OP) is None
        with pytest.raises(Refused) as caught:
            check_body(payload, replace(ALL_OP, block_types=ALL_OP.block_types - {kind}))
    else:
        with pytest.raises(Refused) as caught:
            check_body(payload, ALL_OP)
    assert caught.value.code == "body-refused"


@pytest.mark.parametrize("kind", list(BLOCKS))
@pytest.mark.parametrize("source", list(SOURCES))
def test_nested_permissions_and_contexts_sources(kind, source):
    block = {**deepcopy(BLOCKS[kind]), "source": deepcopy(SOURCES[source])}
    image = kind == "image" and source in {"png", "jpeg", "gif", "webp", "url", "file"}
    document = kind == "document" and source in {"pdf", "text", "content", "url", "file"}
    if image or document:
        assert check_body(block_body(block), ALL_OP) is None
        with pytest.raises(Refused) as caught:
            check_body(block_body(block), replace(ALL_OP, source_types=ALL_OP.source_types - {block["source"]["type"]}))
    else:
        with pytest.raises(Refused) as caught:
            check_body(block_body(block), ALL_OP)
    assert caught.value.code == "body-refused"


@pytest.mark.parametrize("source", ["url", "file"])
@pytest.mark.parametrize("mutation", ["source-permission", "block-permission", "block-key", "source-key"])
def test_nested_permissions_and_contexts_recursion(source, mutation):
    image = {"type": "image", "source": deepcopy(SOURCES[source])}
    payload = block_body({**BLOCKS["tool_result"], "content": [
        {"type": "document", "source": {"type": "content", "content": [image]}}]})
    assert check_body(payload, ALL_OP) is None
    op = ALL_OP
    if mutation == "source-permission":
        op = replace(op, source_types=op.source_types - {source})
    elif mutation == "block-permission":
        op = replace(op, block_types=op.block_types - {"image"})
    elif mutation == "block-key":
        image["future_feature"] = {}
    else:
        image["source"]["future_feature"] = {}
    # block_body copied its outer fixture; mutate the actual descendant.
    nested = at(payload, (*BLOCK_PATH, "content", 0, "source", "content"))
    nested[0] = image
    with pytest.raises(Refused) as caught:
        check_body(payload, op)
    assert caught.value.code == "body-refused"


@pytest.mark.parametrize("field", ["top_k", "budget_tokens", "temperature", "top_p"])
@pytest.mark.parametrize("value", [True, 1.0, "1", None, {}, 0, -1, 1.25])
def test_numeric_controls_do_not_coerce(field, value):
    payload = body(thinking={"type": "enabled", "budget_tokens": value}) if field == "budget_tokens" else body(**{field: value})
    accept = type(value) is int or (field in {"temperature", "top_p"} and type(value) is float)
    if accept:
        assert check_body(parse_body(json.dumps(payload).encode()), OP) is None
    else:
        with pytest.raises(Refused) as caught:
            check_body(parse_body(json.dumps(payload).encode()), OP)
        assert caught.value.code == "body-refused"


@pytest.mark.parametrize("value", [True, 1.0, "1", None, {}, 0, -1, 1.25])
def test_max_tokens_is_an_integer(value):
    if type(value) is int:
        assert check_body(body(max_tokens=value), OP) is None
    else:
        with pytest.raises(Refused) as caught:
            check_body(body(max_tokens=value), OP)
        assert caught.value.code == "body-refused"


@pytest.mark.parametrize("field", ["temperature", "top_p"])
def test_numeric_controls_do_not_coerce_large_integers(field):
    raw = json.dumps(body(**{field: int("9" * 400)})).encode()
    parsed = parse_body(raw)
    assert type(parsed[field]) is int and parsed[field] == int("9" * 400)
    assert check_body(parsed, OP) is None


@pytest.mark.parametrize("field", ["temperature", "top_p"])
def test_numeric_controls_do_not_coerce_overflow(field):
    raw = json.dumps(body(**{field: "overflow"})).encode().replace(b'"overflow"', b'1e999')
    with pytest.raises(Refused) as caught:
        check_body(parse_body(raw), OP)
    assert caught.value.code == "body-refused"


@pytest.mark.parametrize("extra", [
    {"tools": [{**TOOL, "input_examples": []}]},
    {"tools": [{**TOOL, "allowed_callers": ["direct"]}]},
    {"messages": [{"role": "user", "content": [{**BLOCKS["text"], "citations": None}]}]},
    {"messages": [{"role": "user", "content": [{**BLOCKS["image"], "transformations": None}]}]},
    {"messages": [{"role": "assistant", "content": [{**BLOCKS["tool_use"], "caller": {"type": "direct"}}]}]},
    {"messages": [{"role": "user", "content": [{**BLOCKS["tool_result"], "toolset_name": None}]}]},
    {"thinking": {"type": "future"}}, {"thinking": {"type": []}},
    {"thinking": {"type": "disabled", "budget_tokens": 1}},
    {"thinking": {"type": "between_tools", "display": None}},
    {"thinking": {"type": "adaptive", "budget_tokens": 1}},
    {"tool_choice": {"type": "none", "name": "local"}}, {"tool_choice": {"type": "future"}},
    {"tool_choice": {"type": {}}}, {"output_config": {"format": {}}},
    {"output_config": {"task_budget": {}}}, {"metadata": {"user_id": 3}},
    {"stream": 1}, {"stop_sequences": [1]}, {"stop_sequences": "stop"},
    {"messages": [{"role": [], "content": []}]}, {"messages": [{"role": "future", "content": []}]},
    {"messages": [{"role": "system", "content": [], "clear_at": "never"}]},
])
def test_control_variants_refused(extra):
    with pytest.raises(Refused) as caught:
        check_body(body(**extra), ALL_OP)
    assert caught.value.code == "body-refused"


@pytest.mark.parametrize("extra", [{"messages": []}, {"tools": []}, {"system": []}, {"stop_sequences": []},
                                   {"system": ""}, {"stop_sequences": ["", "stop"]}, {"stream": False}])
def test_control_variants_empty_arrays_and_scalars(extra):
    assert check_body(body(**extra), ALL_OP) is None


def test_custom_client_tool_needs_route_permission():
    payload = body(tools=[{**TOOL, "type": "custom"}])
    assert check_body(payload, ALL_OP) is None
    with pytest.raises(Refused) as caught:
        check_body(payload, OP)
    assert caught.value.code == "body-refused"


@pytest.mark.parametrize("value", [None, 1, True, "opaque", [], {"model": "outside", "tools": ["server"],
    "source": {"type": "url", "url": "https://synthetic.invalid"}, "$ref": "https://synthetic.invalid/schema"}])
@pytest.mark.parametrize("position", ["input", "input_schema"])
def test_opaque_client_data_is_not_control(position, value):
    payload = block_body({**BLOCKS["tool_use"], "input": value}) if position == "input" else body(tools=[{**TOOL, position: value}])
    assert check_body(parse_body(json.dumps(payload).encode()), ALL_OP) is None


@pytest.mark.parametrize("position", ["input", "input_schema"])
@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'"\\ud800"'])
def test_opaque_client_data_is_still_strict_json(position, raw):
    payload = block_body({**BLOCKS["tool_use"], "input": "marker"}) if position == "input" else body(tools=[{**TOOL, position: "marker"}])
    data = json.dumps(payload).encode().replace(b'"marker"', raw)
    with pytest.raises(Refused) as caught:
        parse_body(data)
    assert caught.value.code == "request-malformed"


@pytest.mark.parametrize("model", [None, [], {}, "outside"])
def test_refusal_code_precedence(model):
    with pytest.raises(Refused) as caught:
        check_body({"model": model, "future_feature": {}}, OP)
    assert caught.value.code == "model-refused"


# Synthetic offline pi 1.1.0 / SDK 0.129.0 transport captures from autonomy-d0387e.
PI_CAPTURES = json.loads((Path(__file__).parent / "fixtures" / "pi-messages.json").read_text())


@pytest.mark.parametrize("captured", PI_CAPTURES, ids=[c["id"] for c in PI_CAPTURES])
def test_pinned_pi_payloads(captured):
    if captured["id"] in {"plain", "effort"}:
        assert check_body(captured["body"], OP) is None
    else:
        with pytest.raises(Refused) as caught:
            check_body(captured["body"], OP)
        assert caught.value.code == "body-refused"


def test_pinned_pi_deferred_placeholder():
    inline = next(c for c in PI_CAPTURES if c["id"] == "inline")
    placeholder = next(t for t in inline["body"]["tools"] if t["name"] == "__pi_deferred_placeholder__")
    assert placeholder["defer_loading"] is True
    assert check_body(parse_body(json.dumps(body(tools=[placeholder])).encode()), OP) is None
