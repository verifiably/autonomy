"""The `anthropic-messages` dialect (envelope design decision 13). The body is parsed
as strict JSON, so the proxy and the upstream read the same values from the same
bytes. Then every position where a provider feature can sit is checked against the
operation's closed lists. A `tool_use` block's `input` and a tool's `input_schema` are
the client's data and are not walked."""

from __future__ import annotations

import json

from autonomy.egress.errors import Refused
from autonomy.egress.route import Operation

_BOM = b"\xef\xbb\xbf"


def _malformed(message: str) -> Refused:
    return Refused("request-malformed", message)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise _malformed(f"the body repeats the key {key!r}")
        seen[key] = value
    return seen


def _constant(name: str) -> object:
    raise _malformed(f"the body holds {name}, which JSON does not define")


def _strings_encode(value: object) -> None:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                raise _malformed("the body holds a lone surrogate escape") from None
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def parse_body(data: bytes) -> dict:
    if data.startswith(_BOM):
        raise _malformed("the body starts with a byte-order mark")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise _malformed("the body is not UTF-8") from None
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except RecursionError:
        raise _malformed("the body nests too deeply") from None
    except ValueError as caught:  # json.JSONDecodeError, and int's digit limit
        raise _malformed(f"the body is not JSON: {caught}") from None
    if not isinstance(value, dict):
        raise _malformed("the body is not a JSON object")
    _strings_encode(value)
    return value


def _refused(message: str) -> Refused:
    return Refused("body-refused", message)


def _source(source: object, op: Operation, where: str) -> None:
    if not isinstance(source, dict):
        raise _refused(f"{where} must be an object")
    kind = source.get("type")
    if not isinstance(kind, str) or kind not in op.source_types:
        raise _refused(f"{where} has source type {kind!r}; the route allows {sorted(op.source_types)}")
    if kind == "content":
        content = source.get("content")
        if not isinstance(content, str):
            _blocks(content, op, f"{where}.content")


def _blocks(blocks: object, op: Operation, where: str) -> None:
    if not isinstance(blocks, list):
        raise _refused(f"{where} must be a string or a list of blocks")
    for index, block in enumerate(blocks):
        here = f"{where}[{index}]"
        if not isinstance(block, dict):
            raise _refused(f"{here} must be an object")
        kind = block.get("type")
        if not isinstance(kind, str) or kind not in op.block_types:
            raise _refused(f"{here} has block type {kind!r}; the route allows {sorted(op.block_types)}")
        if kind == "tool_result":
            content = block.get("content")
            if content is not None and not isinstance(content, str):
                _blocks(content, op, f"{here}.content")
        if "source" in block:
            _source(block["source"], op, f"{here}.source")


def check_body(body: dict, op: Operation) -> None:
    model = body.get("model")
    if not isinstance(model, str) or model not in op.models:
        raise Refused("model-refused", f"model {model!r} is not one the route allows: {sorted(op.models)}")
    extra = set(body) - op.fields
    if extra:
        raise _refused(f"fields {sorted(extra)} are outside the route's {sorted(op.fields)}")
    try:
        tools = body.get("tools")
        if tools is not None:
            if not isinstance(tools, list):
                raise _refused("tools must be a list")
            for index, tool in enumerate(tools):
                if not isinstance(tool, dict):
                    raise _refused(f"tools[{index}] must be an object")
                if "type" in tool and (not isinstance(tool["type"], str) or tool["type"] not in op.tool_types):
                    raise _refused(f"tools[{index}] has type {tool['type']!r}; the route allows {sorted(op.tool_types)}")
        system = body.get("system")
        if system is not None and not isinstance(system, str):
            _blocks(system, op, "system")
        messages = body.get("messages")
        if messages is not None:
            if not isinstance(messages, list):
                raise _refused("messages must be a list")
            for index, message in enumerate(messages):
                if not isinstance(message, dict):
                    raise _refused(f"messages[{index}] must be an object")
                content = message.get("content")
                if not isinstance(content, str):
                    _blocks(content, op, f"messages[{index}].content")
    except RecursionError:
        raise _refused("the body's blocks nest too deeply") from None
