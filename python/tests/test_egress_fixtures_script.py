import json
import socket
import ssl

from egress_fixtures import FakeUpstream, TextTurn, ToolTurn, message, tls  # noqa: F401  (tls is a fixture)


def _post(upstream, cert, body: dict) -> bytes:
    context = ssl.create_default_context(cafile=str(cert))
    with socket.create_connection(("127.0.0.1", upstream.port), timeout=10) as raw, \
            context.wrap_socket(raw, server_hostname="localhost") as conn:
        data = json.dumps(body).encode()
        conn.sendall(b"POST /v1/messages?beta=true HTTP/1.1\r\nhost: localhost\r\ncontent-type: application/json\r\n"
                     b"content-length: %d\r\n\r\n" % len(data) + data)
        received = b""
        while chunk := conn.recv(65536):
            received += chunk
    return received


def events_of(answer: bytes) -> list[dict]:
    body = answer.split(b"\r\n\r\n", 1)[1]
    # decode chunked framing, then parse "data:" lines
    out, rest = b"", body
    while rest:
        size, _, rest = rest.partition(b"\r\n")
        n = int(size, 16)
        if n == 0:
            break
        out += rest[:n]
        rest = rest[n + 2:]
    return [json.loads(line[6:]) for line in out.split(b"\n") if line.startswith(b"data: ")]


def test_a_tool_turn_streams_a_tool_use_and_records_the_result(tls):
    upstream = FakeUpstream(tls, mode="script")
    upstream.script = [ToolTurn("read", {"path": "/x"}), TextTurn("done")]
    try:
        events = events_of(_post(upstream, tls.cert, message()))
        assert [e["type"] for e in events] == ["message_start", "content_block_start", "content_block_delta",
                                               "content_block_stop", "message_delta", "message_stop"]
        assert events[1]["content_block"]["name"] == "read"
        assert json.loads(events[2]["delta"]["partial_json"]) == {"path": "/x"}
        assert events[4]["delta"]["stop_reason"] == "tool_use"
        tool_use_id = events[1]["content_block"]["id"]
        follow_up = message(messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": tool_use_id, "name": "read", "input": {"path": "/x"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use_id,
                                          "content": [{"type": "text", "text": "ENOENT"}], "is_error": True}]},
        ])
        events = events_of(_post(upstream, tls.cert, follow_up))
        assert events[4]["delta"]["stop_reason"] == "end_turn" and events[2]["delta"]["text"] == "done"
        assert upstream.tool_results() == [{"tool_use_id": tool_use_id, "content": "ENOENT", "is_error": True}]
        assert upstream.tool_uses[0][0] == tool_use_id and upstream.tool_uses[0][1].name == "read"
        assert events_of(_post(upstream, tls.cert, message()))[4]["delta"]["stop_reason"] == "end_turn"  # exhausted
    finally:
        upstream.stop()
