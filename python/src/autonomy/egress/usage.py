"""Incremental, bounded Messages SSE accounting; response bytes are forwarded separately."""
from __future__ import annotations

import json

_CLASSES = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
_EVENT_LIMIT = 1 << 20


def _count(value):
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def _cache(usage):
    total = _count(usage.get("cache_creation_input_tokens", 0))
    split = usage.get("cache_creation")
    if split is None:
        return (0, 0) if total == 0 else (None, None)
    if type(split) is not dict or set(split) - {"ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"}:
        return None, None
    short = _count(split.get("ephemeral_5m_input_tokens", 0))
    long = _count(split.get("ephemeral_1h_input_tokens", 0))
    if short is None or long is None or ("cache_creation_input_tokens" in usage and total != short + long):
        return None, None
    return short, long


class StreamUsage:
    def __init__(self):
        self.message_id = None
        self.usage = dict.fromkeys(_CLASSES)
        self._buffer = bytearray()
        self._data = bytearray()
        self._event = b""
        self._stopped = False
        self._invalid = False

    @property
    def complete(self):
        return (self._stopped and not self._invalid and not self._data and not self._buffer
                and all(v is not None for v in self.usage.values()))

    def feed(self, piece: bytes):
        if self._invalid:
            return
        self._buffer.extend(piece)
        start = 0
        try:
            while (end := self._buffer.find(b"\n", start)) >= 0:
                line = self._buffer[start:end].removesuffix(b"\r")
                start = end + 1
                if len(line) + len(self._data) > _EVENT_LIMIT:
                    raise ValueError("oversized event")
                if not line:
                    if self._data:
                        self._record()
                    self._data.clear()
                    self._event = b""
                elif line.startswith(b"data:"):
                    self._data.extend(line[5:].removeprefix(b" ") + b"\n")
                elif line.startswith(b"event:"):
                    self._event = bytes(line[6:].strip())
            del self._buffer[:start]
            if len(self._buffer) + len(self._data) > _EVENT_LIMIT:
                raise ValueError("oversized partial event")
        except (TypeError, ValueError, KeyError, RecursionError):
            self._invalid = True
            self._buffer.clear()
            self._data.clear()

    def _record(self):
        row = json.loads(self._data)
        kind = row["type"]
        if not isinstance(kind, str) or self._event and self._event != kind.encode():
            raise ValueError("invalid event type")
        if kind == "ping":
            return
        if self._stopped:
            raise ValueError("event after stop")
        if kind == "message_start":
            message = row["message"]
            mid = message["id"]
            if self.message_id is not None or not isinstance(mid, str) or not mid:
                raise ValueError("invalid message identity")
            self.message_id = mid
            usage = message["usage"]
            if not isinstance(usage, dict) or usage.get("service_tier", "standard") != "standard":
                raise ValueError("unsupported usage")
            if set(usage) - {"input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
                             "cache_creation", "service_tier"}:
                raise ValueError("unsupported billing fields")
            self.usage["input"] = _count(usage.get("input_tokens"))
            self.usage["cache_read"] = _count(usage.get("cache_read_input_tokens", 0))
            self.usage["cache_write_5m"], self.usage["cache_write_1h"] = _cache(usage)
        elif kind == "message_delta":
            if self.message_id is None:
                raise ValueError("delta before start")
            usage = row["usage"]
            if not isinstance(usage, dict) or set(usage) != {"output_tokens"}:
                raise ValueError("unsupported delta usage")
            output = _count(usage["output_tokens"])
            if output is None or output < (self.usage["output"] or 0):
                raise ValueError("invalid cumulative output")
            self.usage["output"] = output
        elif kind == "message_stop":
            self._stopped = self.message_id is not None
        elif kind not in ("content_block_start", "content_block_delta", "content_block_stop"):
            raise ValueError("unsupported SSE event")
