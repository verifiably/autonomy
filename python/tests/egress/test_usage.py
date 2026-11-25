import json

import pytest

from autonomy.egress.usage import StreamUsage


def event(kind, **data):
    payload = json.dumps({"type": kind, **data}).encode()
    return b"event: " + kind.encode() + b"\r\ndata: " + payload + b"\r\n\r\n"


@pytest.mark.parametrize(("cache", "expected"), [
    ({}, (0, 0, 0)),
    ({"cache_creation_input_tokens": 0}, (0, 0, 0)),
    ({"cache_read_input_tokens": 3, "cache_creation_input_tokens": 5,
      "cache_creation": {"ephemeral_5m_input_tokens": 1, "ephemeral_1h_input_tokens": 4}}, (3, 1, 4)),
    ({"cache_creation_input_tokens": 5}, (0, None, None)),
    ({"cache_creation_input_tokens": 5, "cache_creation": {"ephemeral_5m_input_tokens": 1,
      "ephemeral_1h_input_tokens": 5}}, (0, None, None)),
])
def test_usage_across_chunks(cache, expected):
    s = StreamUsage()
    data = (event("message_start", message={"id": "m1", "usage": {"input_tokens": 8, **cache}})
            + event("message_delta", usage={"output_tokens": 2})
            + event("message_delta", usage={"output_tokens": 3})
            + event("message_delta", usage={"output_tokens": 3}) + event("message_stop"))
    for byte in data:
        s.feed(bytes([byte]))
    assert s.message_id == "m1"
    assert s.usage == dict(input=8, output=3, cache_read=expected[0], cache_write_5m=expected[1], cache_write_1h=expected[2])
    assert s.complete == (None not in expected)


@pytest.mark.parametrize("events", [
    [event("message_start", message={"id": "m1", "usage": {}}), event("message_delta", usage={"output_tokens": 3}), event("message_stop")],
    [event("message_start", message={"id": "m1", "usage": {"input_tokens": 8}}), event("message_stop")],
    [event("message_start", message={"id": "m1", "usage": {"input_tokens": 8}}), event("message_delta", usage={"output_tokens": 3})],
])
def test_absent_mandatory_counts_or_stop_do_not_certify_the_stream(events):
    s = StreamUsage()
    for record in events:
        s.feed(record)
    assert not s.complete

