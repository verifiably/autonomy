"""Shared fixtures for the egress tests: route documents and files, and (Task 6) a
fake TLS upstream."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import ssl
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

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


@dataclass(frozen=True)
class Tls:
    cert: Path
    key: Path


@pytest.fixture(scope="session")
def tls(tmp_path_factory) -> Tls:
    """A self-signed certificate for localhost, `other` and 127.0.0.1. The tests need
    the openssl CLI and fail without it: skipping would hide the egress rows."""
    if shutil.which("openssl") is None:
        pytest.fail("the egress tests need the openssl CLI to make their test certificate")
    directory = tmp_path_factory.mktemp("tls")
    cert, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
         "-keyout", str(key), "-out", str(cert), "-days", "2", "-subj", "/CN=localhost",
         "-addext", "subjectAltName=DNS:localhost,DNS:other,IP:127.0.0.1"],
        check=True, capture_output=True, stdin=subprocess.DEVNULL,
    )
    return Tls(cert, key)


@dataclass
class Seen:
    method: str
    target: str
    headers: dict[str, list[str]]
    body: bytes


class FakeUpstream:
    """A TLS server on 127.0.0.1 standing in for the provider. `mode` picks the answer:
    - `json`: 200 with a small JSON body and a Content-Length;
    - `sse`: 200, chunked, `events` server-sent events `gap` seconds apart;
    - `close`: 200 with a body delimited by closing the connection;
    - `continue`: a 100 Continue, then as `json`;
    - `redirect`: 302 to `location`;
    - `stall`: read the head, then never read again (the body fills the buffers);
    - `reset`: read the head, then reset the connection (an abortive close);
    - `silent`: send a streaming head, then nothing; `peer_closed` is set when the
      proxy closes the connection;
    - `nohandshake`: accept TCP and never answer TLS; `peer_closed` as for `silent`;
    - `garbage`, `hugehead`, `badchunk`: malformed answers.
    Every request it reads is in `seen`, and `connections` counts every accept."""

    def __init__(self, tls: Tls, *, mode: str = "json") -> None:
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(tls.cert, tls.key)
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # A small receive buffer (inherited by accepted sockets), so a stalled upload
        # fills the buffers whatever the host's tcp_rmem/tcp_wmem allow.
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 * 1024)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(64)
        self.port = self.listener.getsockname()[1]
        self.mode = mode
        self.events = 5
        self.gap = 0.2
        self.location = ""
        self.seen: list[Seen] = []
        self.connections = 0
        self.last_event_at: float | None = None
        self.peer_closed = threading.Event()
        self._stalled: list[tuple[Seen, ssl.SSLSocket]] = []
        self._lock = threading.Lock()
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def origin(self) -> str:
        return f"https://localhost:{self.port}"

    def stop(self) -> None:
        self.listener.close()

    def _accept(self) -> None:
        while True:
            try:
                raw, _ = self.listener.accept()
            except OSError:
                return
            with self._lock:
                self.connections += 1
            target = self._hold_raw if self.mode == "nohandshake" else self._serve
            threading.Thread(target=target, args=(raw,), daemon=True).start()

    def _hold_raw(self, raw: socket.socket) -> None:
        try:
            while raw.recv(65536):  # the ClientHello, which nobody answers, until the proxy closes
                pass
        except OSError:
            pass
        self.peer_closed.set()
        raw.close()

    def _serve(self, raw: socket.socket) -> None:
        try:
            conn = self.context.wrap_socket(raw, server_side=True)
        except (ssl.SSLError, OSError):
            raw.close()
            return
        keep = False
        try:
            conn.settimeout(10)
            buffer = b""
            while b"\r\n\r\n" not in buffer:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buffer += chunk
            head, _, body = buffer.partition(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            headers: dict[str, list[str]] = {}
            for line in lines[1:]:
                name, _, value = line.partition(":")
                headers.setdefault(name.strip().lower(), []).append(value.strip())
            seen = Seen(method, target, headers, body)
            if self.mode == "reset":
                with self._lock:
                    self.seen.append(seen)
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                return
            if self.mode == "stall":
                with self._lock:
                    self.seen.append(seen)
                    self._stalled.append((seen, conn))
                keep = True
                return
            length = int(headers.get("content-length", ["0"])[0])
            while len(seen.body) < length:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                seen.body += chunk
            with self._lock:
                self.seen.append(seen)
            self._answer(conn)
        except OSError:
            pass
        finally:
            if not keep:
                conn.close()

    def _answer(self, conn: ssl.SSLSocket) -> None:
        json_body = b'{"ok":true}'
        if self.mode == "continue":
            conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
        if self.mode in ("json", "continue"):
            conn.sendall(
                b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\nrequest-id: req_json\r\n"
                b"set-cookie: s=1\r\ncontent-length: %d\r\n\r\n" % len(json_body) + json_body
            )
        elif self.mode == "close":
            conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n\r\n" + json_body)
        elif self.mode == "sse":
            conn.sendall(
                b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\nrequest-id: req_sse\r\n"
                b"retry-after: 1\r\ntransfer-encoding: chunked\r\nconnection: keep-alive\r\n\r\n"
            )
            for index in range(self.events):
                if index:
                    time.sleep(self.gap)
                if index == self.events - 1:
                    self.last_event_at = time.monotonic()
                event = b"event: message\ndata: {\"n\": %d}\n\n" % index
                conn.sendall(b"%x\r\n%s\r\n" % (len(event), event))
            conn.sendall(b"0\r\n\r\n")
        elif self.mode == "silent":
            conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\ntransfer-encoding: chunked\r\n\r\n")
            conn.settimeout(None)
            try:
                conn.recv(1)  # returns when the proxy closes its side
            except (OSError, ssl.SSLError):
                pass
            self.peer_closed.set()
        elif self.mode == "redirect":
            conn.sendall(b"HTTP/1.1 302 Found\r\nlocation: %s\r\ncontent-length: 0\r\n\r\n" % self.location.encode())
        elif self.mode == "garbage":
            conn.sendall(b"NOT HTTP AT ALL\r\n\r\n")
        elif self.mode == "hugehead":
            conn.sendall(b"HTTP/1.1 200 OK\r\nx-a: " + b"a" * 70_000 + b"\r\n\r\n")
        elif self.mode == "badchunk":
            conn.sendall(b"HTTP/1.1 200 OK\r\ntransfer-encoding: chunked\r\n\r\nzz\r\nhello\r\n0\r\n\r\n")

    def stalled_bytes(self) -> int:
        """Drain every stalled connection now and count the body bytes it ever received."""
        total = 0
        for seen, conn in self._stalled:
            received = len(seen.body)
            conn.settimeout(2)
            try:
                while chunk := conn.recv(65536):
                    received += len(chunk)
            except (OSError, ssl.SSLError):
                pass
            conn.close()
            total += received
        return total
