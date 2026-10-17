"""Shared fixtures for the egress tests: route documents and files, and (Task 6) a
fake TLS upstream."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

PI_FIELDS = [
    "model", "messages", "system", "max_tokens", "stream", "tools", "tool_choice", "thinking",
    "temperature", "metadata", "stop_sequences", "top_p", "top_k",
]
PI_BLOCKS = ["text", "image", "tool_use", "tool_result", "thinking", "redacted_thinking"]
PI_BETAS = ["fine-grained-tool-streaming-2025-05-14", "interleaved-thinking-2025-05-14"]
MODEL = "claude-haiku-5-5"


def pi_route(*, credential: Path, upstream: str = "https://api.anthropic.com", ca_file: Path | None = None) -> dict:
    """The route pi needs: POST /v1/messages?beta=true, client tools only, base64 sources."""
    doc: dict = {
        "api": "anthropic-messages",
        "upstream": upstream,
        "max_request_bytes": 8_000_000,
        "forward_headers": ["anthropic-version", "anthropic-beta", "content-type", "accept", "user-agent"],
        "header_tokens": {"anthropic-version": ["2023-06-01"], "anthropic-beta": list(PI_BETAS)},
        "credential": {"file": str(credential), "header": "x-api-key"},
        "operations": [
            {
                "method": "POST",
                "path": "/v1/messages",
                "queries": ["beta=true"],
                "models": [MODEL],
                "fields": list(PI_FIELDS),
                "tool_types": [],
                "block_types": list(PI_BLOCKS),
                "source_types": ["base64"],
            }
        ],
    }
    if ca_file is not None:
        doc["ca_file"] = str(ca_file)
    return doc


def _key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key)


def _value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    raise TypeError(f"no TOML form for {value!r}")


def to_toml(doc: dict) -> str:
    """Enough TOML for a route: scalars and lists, then tables, then arrays of tables."""
    lines: list[str] = []
    tables, arrays = [], []
    for key, value in doc.items():
        if isinstance(value, dict):
            tables.append((key, value))
        elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            arrays.append((key, value))
        else:
            lines.append(f"{_key(key)} = {_value(value)}")
    for key, table in tables:
        lines.append(f"[{_key(key)}]")
        lines += [f"{_key(k)} = {_value(v)}" for k, v in table.items()]
    for key, items in arrays:
        for table in items:
            lines.append(f"[[{_key(key)}]]")
            lines += [f"{_key(k)} = {_value(v)}" for k, v in table.items()]
    return "\n".join(lines) + "\n"


def write_route(config: Path, name: str, doc: dict) -> Path:
    path = config / "routes" / f"{name}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_toml(doc))
    return path


def write_credential(path: Path, value: str = "sk-canary") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(value + "\n")
    os.chmod(path, 0o600)
    return path
