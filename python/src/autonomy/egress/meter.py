"""Validate metered Messages requests before remote admission and settle their SSE usage."""
from autonomy.allowance import AllowanceRefused
from autonomy.allowance._contract import debit
from autonomy.egress.usage import StreamUsage


class ModelMeter:
    def __init__(self, client, tariff):
        self.client = client
        self.tariff = tariff

    def admit(self, run, seq, body, request_bytes, in_flight):
        output = body["max_tokens"]
        if body.get("stream") is not True or type(output) is not int or not 1 <= output <= self.tariff["output_cap"]:
            raise AllowanceRefused("body-refused", "a streaming request needs a positive, bounded max_tokens")
        thinking = body.get("thinking")
        if isinstance(thinking, dict) and "budget_tokens" in thinking:
            budget = thinking["budget_tokens"]
            if type(budget) is not int or not 0 < budget < output:
                raise AllowanceRefused("body-refused", "invalid thinking budget")
        if self.tariff["billing_mode"] != "standard":
            raise AllowanceRefused("allowance-unpriced", "unsupported billing profile")
        args = dict(seq=seq, model=body["model"], max_tokens=output, billing_mode="standard")
        reserved = debit("model", args, self.tariff)["micro_usd"]
        reply = self.client.call("reserve-model", args)
        if reply["result"] != "admitted":
            raise AllowanceRefused("allowance-unavailable", "attempt already recorded; reconcile its receipt")
        return reserved

    def settle(self, seq, request_id, stream: StreamUsage):
        self.client.call("settle-model", dict(seq=seq, request_id=request_id, message_id=stream.message_id,
                         usage=stream.usage, status="complete" if stream.complete else "unknown"))
        if stream.complete:
            rates = self.tariff["rates_micro_usd_per_mtok"]
            return (sum(rates[k] * v for k, v in stream.usage.items()) + 999999) // 1000000
        return None
