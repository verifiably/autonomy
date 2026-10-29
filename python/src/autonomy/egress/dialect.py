"""The `anthropic-messages` dialect (envelope design decision 13). The body is parsed
as strict JSON, so the proxy and the upstream read the same values from the same
bytes. Then every position where a provider feature can sit is checked against the
operation's closed lists. A `tool_use` block's `input` and a tool's `input_schema` are
the client's data and are not walked."""

from __future__ import annotations

import json
import math

from autonomy.egress.errors import Refused
from autonomy.egress.route import KNOWN_BLOCK_TYPES, KNOWN_FIELDS, KNOWN_SOURCE_TYPES, Operation

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


def _object(value: object, where: str, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise _refused(f"{where} must be an object")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing or extra:
        raise _refused(f"{where} has missing keys {sorted(missing)} and undefined keys {sorted(extra)}")
    return value


def _scalar(value: object, kind: type, where: str) -> None:
    if type(value) is not kind:
        raise _refused(f"{where} must be {kind.__name__}")


def _one_of(value: object, choices: tuple, where: str) -> None:
    if value not in choices:
        raise _refused(f"{where} must be one of {choices}")


def _cache(value: object, where: str) -> None:
    if value is None:
        return
    cache = _object(value, where, {"type"}, {"ttl"})
    _one_of(cache["type"], ("ephemeral",), f"{where}.type")
    if "ttl" in cache:
        _one_of(cache["ttl"], ("5m", "1h"), f"{where}.ttl")


def _effort(value: object, where: str) -> None:
    config = _object(value, where, set(), {"effort"})
    if "effort" in config:
        _one_of(config["effort"], ("low", "medium", "high", "xhigh", "max", None), f"{where}.effort")


def _thinking(value: object) -> None:
    if not isinstance(value, dict):
        raise _refused("thinking must be an object")
    kind = value.get("type")
    _one_of(kind, ("disabled", "between_tools", "enabled", "adaptive"), "thinking.type")
    active = kind in ("enabled", "adaptive")
    required = {"type", "budget_tokens"} if kind == "enabled" else {"type"}
    thinking = _object(value, "thinking", required, {"display", "block_binding"} if active else set())
    if kind == "enabled":
        _scalar(thinking["budget_tokens"], int, "thinking.budget_tokens")
    if "display" in thinking:
        _one_of(thinking["display"], ("summarized", "omitted", "updates", None), "thinking.display")
    if "block_binding" in thinking and thinking["block_binding"] is not None:
        binding = _object(thinking["block_binding"], "thinking.block_binding", set(), {"prefix_mismatch_behavior"})
        if "prefix_mismatch_behavior" in binding:
            _one_of(binding["prefix_mismatch_behavior"], ("error", "drop_block", None),
                    "thinking.block_binding.prefix_mismatch_behavior")


def _choice(value: object) -> None:
    if not isinstance(value, dict):
        raise _refused("tool_choice must be an object")
    kind = value.get("type")
    _one_of(kind, ("auto", "any", "tool", "none"), "tool_choice.type")
    choice = _object(value, "tool_choice", {"type", "name"} if kind == "tool" else {"type"},
                     {"disable_parallel_tool_use"} if kind != "none" else set())
    if kind == "tool":
        _scalar(choice["name"], str, "tool_choice.name")
    if "disable_parallel_tool_use" in choice:
        _scalar(choice["disable_parallel_tool_use"], bool, "tool_choice.disable_parallel_tool_use")


def _tool(value: object, op: Operation, where: str) -> None:
    tool = _object(value, where, {"name", "input_schema"},
                   {"type", "description", "cache_control", "eager_input_streaming", "strict", "defer_loading"})
    _scalar(tool["name"], str, f"{where}.name")
    if "type" in tool:
        _one_of(tool["type"], ("custom",), f"{where}.type")
        if tool["type"] not in op.tool_types:
            raise _refused(f"{where}.type is outside the route's tool_types")
    if "description" in tool:
        _scalar(tool["description"], str, f"{where}.description")
    if "cache_control" in tool:
        _cache(tool["cache_control"], f"{where}.cache_control")
    for key in ("strict", "defer_loading", "eager_input_streaming"):
        if key in tool and not (key == "eager_input_streaming" and tool[key] is None):
            _scalar(tool[key], bool, f"{where}.{key}")


def _source(value: object, op: Operation, where: str, parent: str) -> None:
    if not isinstance(value, dict):
        raise _refused(f"{where} must be an object")
    kind = value.get("type")
    if not isinstance(kind, str) or kind not in KNOWN_SOURCE_TYPES or kind not in op.source_types:
        raise _refused(f"{where} has an undefined or unlisted source type")
    if parent == "image" and kind not in {"base64", "url", "file"}:
        raise _refused(f"{where} is not an image source")
    if kind in {"base64", "text"}:
        source = _object(value, where, {"type", "media_type", "data"})
        media = ("image/jpeg", "image/png", "image/gif", "image/webp") if parent == "image" else (
            ("application/pdf",) if kind == "base64" else ("text/plain",))
        _one_of(source["media_type"], media, f"{where}.media_type")
        _scalar(source["data"], str, f"{where}.data")
    elif kind == "content":
        source = _object(value, where, {"type", "content"})
        _blocks(source["content"], op, f"{where}.content", {"text", "image"})
    else:
        key = "url" if kind == "url" else "file_id"
        source = _object(value, where, {"type", key})
        _scalar(source[key], str, f"{where}.{key}")


_BLOCK_KEYS = {
    "text": ({"type", "text"}, {"cache_control"}),
    "image": ({"type", "source"}, {"cache_control"}),
    "document": ({"type", "source"}, {"cache_control", "citations", "context", "title"}),
    "tool_use": ({"type", "id", "name", "input"}, {"cache_control"}),
    "tool_result": ({"type", "tool_use_id"}, {"cache_control", "content", "is_error"}),
    "thinking": ({"type", "thinking", "signature"}, set()),
    "redacted_thinking": ({"type", "data"}, set()),
}


def _blocks(blocks: object, op: Operation, where: str, allowed=KNOWN_BLOCK_TYPES) -> None:
    if isinstance(blocks, str):
        return
    if not isinstance(blocks, list):
        raise _refused(f"{where} must be a string or a list of blocks")
    for index, value in enumerate(blocks):
        here = f"{where}[{index}]"
        if not isinstance(value, dict):
            raise _refused(f"{here} must be an object")
        kind = value.get("type")
        if not isinstance(kind, str) or kind not in allowed or kind not in op.block_types:
            raise _refused(f"{here} has an undefined, misplaced or unlisted block type")
        required, optional = _BLOCK_KEYS[kind]
        block = _object(value, here, required, optional)
        if "cache_control" in block:
            _cache(block["cache_control"], f"{here}.cache_control")
        if kind == "text":
            _scalar(block["text"], str, f"{here}.text")
        elif kind in {"image", "document"}:
            _source(block["source"], op, f"{here}.source", kind)
            if kind == "document":
                for key in ("context", "title"):
                    if key in block and block[key] is not None:
                        _scalar(block[key], str, f"{here}.{key}")
                if "citations" in block and block["citations"] is not None:
                    citations = _object(block["citations"], f"{here}.citations", set(), {"enabled"})
                    if "enabled" in citations:
                        _scalar(citations["enabled"], bool, f"{here}.citations.enabled")
        elif kind == "tool_use":
            _scalar(block["id"], str, f"{here}.id")
            _scalar(block["name"], str, f"{here}.name")
        elif kind == "tool_result":
            _scalar(block["tool_use_id"], str, f"{here}.tool_use_id")
            if "content" in block:
                _blocks(block["content"], op, f"{here}.content", {"text", "image", "document"})
            if "is_error" in block:
                _scalar(block["is_error"], bool, f"{here}.is_error")
        elif kind == "thinking":
            _scalar(block["thinking"], str, f"{here}.thinking")
            _scalar(block["signature"], str, f"{here}.signature")
        else:
            _scalar(block["data"], str, f"{here}.data")


def _message(value: object, op: Operation, where: str) -> None:
    if not isinstance(value, dict):
        raise _refused(f"{where} must be an object")
    role = value.get("role")
    _one_of(role, ("user", "assistant", "system"), f"{where}.role")
    message = _object(value, where, {"role", "content"}, {"output_config"} if role == "system" else set())
    _blocks(message["content"], op, f"{where}.content")
    if "output_config" in message:
        if "output_config" not in op.fields:
            raise _refused(f"{where}.output_config is outside the route's fields")
        if message["output_config"] is not None:
            _effort(message["output_config"], f"{where}.output_config")


def check_body(body: dict, op: Operation) -> None:
    model = body.get("model")
    if not isinstance(model, str) or model not in op.models:
        raise Refused("model-refused", f"model {model!r} is not one the route allows: {sorted(op.models)}")
    extra = set(body) - op.fields
    if extra:
        raise _refused(f"fields {sorted(extra)} are outside the route's {sorted(op.fields)}")
    required = {"model", "messages", "max_tokens"}
    _object(body, "body", required, KNOWN_FIELDS - required)
    try:
        for key in ("max_tokens", "top_k"):
            if key in body:
                _scalar(body[key], int, key)
        for key in ("temperature", "top_p"):
            if key in body:
                value = body[key]
                if not (type(value) is int or (type(value) is float and math.isfinite(value))):
                    raise _refused(f"{key} must be a finite number")
        if "stream" in body:
            _scalar(body["stream"], bool, "stream")
        if "stop_sequences" in body:
            stops = body["stop_sequences"]
            _scalar(stops, list, "stop_sequences")
            for index, stop in enumerate(stops):
                _scalar(stop, str, f"stop_sequences[{index}]")
        if "metadata" in body:
            metadata = _object(body["metadata"], "metadata", set(), {"user_id"})
            if "user_id" in metadata and metadata["user_id"] is not None:
                _scalar(metadata["user_id"], str, "metadata.user_id")
        if "output_config" in body:
            _effort(body["output_config"], "output_config")
        if "thinking" in body:
            _thinking(body["thinking"])
        if "tool_choice" in body:
            _choice(body["tool_choice"])
        if "tools" in body:
            _scalar(body["tools"], list, "tools")
            for index, tool in enumerate(body["tools"]):
                _tool(tool, op, f"tools[{index}]")
        if "system" in body:
            _blocks(body["system"], op, "system", {"text"})
        _scalar(body["messages"], list, "messages")
        for index, message in enumerate(body["messages"]):
            _message(message, op, f"messages[{index}]")
    except RecursionError:
        raise _refused("the body's blocks nest too deeply") from None
