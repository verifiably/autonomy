import pytest

from autonomy.allowance import AllowanceRefused
from autonomy.egress.meter import ModelMeter


class Calls:
    def __init__(self):
        self.requests = []

    def call(self, op, args):
        self.requests.append((op, args))
        return {"result": "admitted"}


@pytest.mark.parametrize("change", [
    {"stream": False}, {"stream": None}, {"max_tokens": 0}, {"max_tokens": True}, {"max_tokens": -3},
    {"max_tokens": 2049}, {"thinking": {"type":"enabled","budget_tokens":0}},
    {"thinking": {"type":"enabled","budget_tokens":2048}},
])
def test_bad_body_never_contacts_authority(change):
    peer = Calls()
    meter = ModelMeter(peer, {"model":"test","billing_mode":"standard","output_cap":2048})
    with pytest.raises(AllowanceRefused, match="body-refused"):
        meter.admit("env", 1, {"model":"test","max_tokens":2048,"stream":True} | change, 0, 1)
    assert peer.requests == []
