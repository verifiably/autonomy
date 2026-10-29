"""Characterization, not a fix: assert the current verdict; retain proposed verdicts.

Run through just test-one with this file's path and -q -s. Sibling files are
route-example.toml and pi-payloads.json. No sockets, subprocesses or credentials.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from autonomy.egress.dialect import check_body, parse_body
from autonomy.egress.errors import Refused, RouteRefused
from autonomy.egress.route import parse_route

ROOT = Path(__file__).parent
ROUTE = (ROOT / "route-example.toml").read_text()
BASE = {"model": "claude-haiku-5-5", "max_tokens": 16,
        "messages": [{"role": "user", "content": "hi"}]}
TEXT = {"type": "text", "text": "hi"}
IMAGE = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}
TOOL = {"name": "local", "input_schema": {"type": "object"}}
REMOTE = {"type": "url", "url": "https://synthetic.invalid/source"}
SERVER_TOOL = {"type": "web_fetch_20250910", "name": "web_fetch"}
CASES = []


def case(name, extra=None, current="accept", proposed=None, route=ROUTE):
    CASES.append((name, {**deepcopy(BASE), **deepcopy(extra or {})}, route,
                  current, proposed or current))


def msg_case(name, message, **kwargs):
    case(name, {"messages": [message]}, **kwargs)


def block_case(name, block, **kwargs):
    msg_case(name, {"role": "user", "content": [block]}, **kwargs)


case("plain")
case("outside-model", {"model": "outside-route"}, "model-refused")
case("top-mcp", {"mcp_servers": [{"type": "url", "name": "remote", "url": REMOTE["url"]}]}, "body-refused")
case("top-server-tool", {"tools": [SERVER_TOOL]}, "body-refused")
case("client-tool", {"tools": [TOOL]})
case("client-schema-opaque", {"tools": [{**TOOL, "input_schema": {"model": "outside-route", "source": REMOTE, "tools": [SERVER_TOOL]}}]})
block_case("client-input-opaque", {"type": "tool_use", "id": "t", "name": "local", "input": {"model": "outside-route", "source": REMOTE, "tools": [SERVER_TOOL]}})
block_case("base64", IMAGE)
block_case("url-source", {"type": "image", "source": REMOTE}, current="body-refused")
block_case("nested-result-url", {"type": "tool_result", "tool_use_id": "t", "content": [{"type": "image", "source": REMOTE}]}, current="body-refused")
block_case("inline-server-tool", {"type": "tool_addition", "tool": {"type": "tool_definition", "definition": SERVER_TOOL}}, current="body-refused")
block_case("inline-client-tool", {"type": "tool_addition", "tool": {"type": "tool_definition", "definition": TOOL}}, current="body-refused")

for key, value in [("tools", [SERVER_TOOL]), ("source", REMOTE), ("model", "outside-route"), ("future_feature", {})]:
    msg_case("message-" + key, {"role": "user", "content": "hi", key: value}, proposed="body-refused")
    block_case("block-" + key, {**TEXT, key: value},
               current="body-refused" if key == "source" else "accept", proposed="body-refused")
msg_case("unknown-role", {"role": "future_role", "content": "hi"}, proposed="body-refused")
msg_case("missing-role", {"content": "hi"}, proposed="body-refused")
msg_case("system-effort", {"role": "system", "content": [], "output_config": {"effort": "high"}})
msg_case("system-config-only-missing-content", {"role": "system", "output_config": {"effort": "high"}}, current="body-refused")
msg_case("user-output-config", {"role": "user", "content": "hi", "output_config": {"effort": "high"}}, proposed="body-refused")
msg_case("system-output-extra", {"role": "system", "content": [], "output_config": {"effort": "high", "tools": [SERVER_TOOL]}}, proposed="body-refused")
msg_case("clear-at", {"role": "system", "content": "hi", "clear_at": "next_user_message"}, proposed="body-refused")
case("top-effort", {"output_config": {"effort": "high"}})
case("top-output-extra", {"output_config": {"tools": [SERVER_TOOL]}}, proposed="body-refused")
case("top-effort-unknown", {"output_config": {"effort": "future_effort"}}, proposed="body-refused")
case("output-format", {"output_config": {"format": {"type": "json_schema", "schema": {"type": "object"}}}}, proposed="body-refused")
case("output-task-budget", {"output_config": {"task_budget": {"type": "tokens", "total": 1000}}}, proposed="body-refused")
case("thinking-adaptive", {"thinking": {"type": "adaptive", "display": "summarized", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}})
case("thinking-extra", {"thinking": {"type": "adaptive", "model": "outside-route"}}, proposed="body-refused")
case("thinking-unknown-type", {"thinking": {"type": "future_mode"}}, proposed="body-refused")
case("binding-extra", {"thinking": {"type": "adaptive", "block_binding": {"source": REMOTE}}}, proposed="body-refused")
case("choice-tool", {"tools": [TOOL], "tool_choice": {"type": "tool", "name": "local"}})
case("choice-extra", {"tool_choice": {"type": "auto", "tools": [SERVER_TOOL]}}, proposed="body-refused")
case("choice-unknown-type", {"tool_choice": {"type": "future_tool"}}, proposed="body-refused")
case("metadata-user-id", {"metadata": {"user_id": "synthetic-id"}})
case("metadata-extra", {"metadata": {"source": REMOTE}}, proposed="body-refused")
case("tool-extra", {"tools": [{**TOOL, "source": REMOTE}]}, proposed="body-refused")
case("tool-server-caller", {"tools": [{**TOOL, "allowed_callers": ["code_execution_20260521"]}]}, proposed="body-refused")
case("tool-deferred-placeholder", {"tools": [{**TOOL, "defer_loading": True}]})
block_case("cache-extra", {**TEXT, "cache_control": {"type": "ephemeral", "source": REMOTE}}, proposed="body-refused")
block_case("source-extra", {**IMAGE, "source": {**IMAGE["source"], "url": REMOTE["url"]}}, proposed="body-refused")
block_case("text-citations", {**TEXT, "citations": [{"type": "web_search_result_location", "url": REMOTE["url"], "title": "synthetic", "encrypted_index": "x", "cited_text": "x"}]}, proposed="body-refused")
block_case("tool-use-caller", {"type": "tool_use", "id": "t", "name": "local", "input": {}, "caller": {"type": "code_execution_20260521", "tool_id": "x"}}, proposed="body-refused")
case("scalar-object", {"temperature": {"source": REMOTE}}, proposed="body-refused")

for name, value in [("fallback-array", [{"model": "outside-route"}]), ("fallback-default", "default")]:
    case(name, {"fallbacks": value}, "body-refused")
    case(name + "-listed", {"fallbacks": value}, proposed="route-invalid",
         route=ROUTE.replace('fields = ["model"', 'fields = ["fallbacks", "model"'))
case("unknown-field-listed", {"future_feature": {"source": REMOTE}}, proposed="route-invalid",
     route=ROUTE.replace('fields = ["model"', 'fields = ["future_feature", "model"'))
case("server-tool-listed", {"tools": [SERVER_TOOL]}, proposed="route-invalid",
     route=ROUTE + '\ntool_types = ["web_fetch_20250910"]\n')
case("inline-type-listed", current="route-invalid",
     route=ROUTE.replace('block_types = ["text"', 'block_types = ["tool_addition", "text"'))

DOC_ROUTE = ROUTE.replace('block_types = ["text"', 'block_types = ["document", "text"').replace('source_types = ["base64"]', 'source_types = ["base64", "content", "text", "url", "file"]')
for name, source in [("document-text", {"type": "text", "media_type": "text/plain", "data": "hi"}),
                     ("document-content", {"type": "content", "content": [TEXT, IMAGE]}),
                     ("document-url-authorized", REMOTE),
                     ("document-file-authorized", {"type": "file", "file_id": "synthetic"})]:
    block_case(name, {"type": "document", "source": source}, route=DOC_ROUTE)
block_case("document-source-extra", {"type": "document", "source": {"type": "content", "content": [TEXT], "tools": [SERVER_TOOL]}}, route=DOC_ROUTE, proposed="body-refused")
block_case("document-citation-extra", {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": "hi"}, "citations": {"enabled": True, "source": REMOTE}}, route=DOC_ROUTE, proposed="body-refused")
block_case("nested-document-url-denied", {"type": "document", "source": {"type": "content", "content": [{"type": "image", "source": REMOTE}]}}, route=DOC_ROUTE.replace(', "url", "file"', ''), current="body-refused")

for captured in json.loads((ROOT / "pi-payloads.json").read_text()):
    case("pi-" + captured["id"], captured["body"],
         current="body-refused" if captured["id"] in {"inline", "fallback"} else "accept")


@pytest.mark.parametrize("name,body,route,current,proposed", CASES, ids=[c[0] for c in CASES])
def test_current_verdict(name, body, route, current, proposed):
    try:
        op = parse_route(route.encode()).operations[0]
        check_body(parse_body(json.dumps(body).encode()), op)
        observed = "accept"
    except (Refused, RouteRefused) as error:
        observed = error.code
    assert observed == current
    print(f"{name}: current={observed}; proposed={proposed}")
