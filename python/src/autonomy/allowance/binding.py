"""Select an already issued member by its immutable caller and route bindings."""
from dataclasses import dataclass

from . import _contract as c
from ._configuration import resolve
from ._store import Campaign


@dataclass(frozen=True)
class Member:
    pool: Campaign
    name: str
    caller: str
    target: dict
    route_digest: str
    tariff: dict
    expires: int
    conversation_id: str | None
    provider_session_id: str | None

    def open(self, envelope):
        return self.pool.open(self.name, envelope, caller=self.caller, target=self.target, route_digest=self.route_digest,
                              conversation_id=self.conversation_id, provider_session_id=self.provider_session_id)

    def check(self):
        receipt = self.pool.receipt()
        self.pool._active(receipt["closed"])


def select(config, reference, route_reference, caller, route_digest, conversation_id=None, provider_session_id=None):
    c.require(not (reference and route_reference and reference != route_reference), "route and caller name different grants")
    pool, name = resolve(config, reference or route_reference)
    receipt = pool.receipt()
    pool._active(receipt["closed"])
    grant = receipt["grant"]
    spec = grant["members"].get(name)
    c.require(spec and spec["caller"] == caller and spec["route_digest"] == route_digest, "caller or route differs")
    if caller == "e21":
        c.require(spec["limits"]["attempts"] <= 1 and spec["limits"]["job_starts"] == 0,
                  "smoke member exceeds one call or enables jobs")
    if caller == "band":
        c.uid(conversation_id)
    else:
        c.require(conversation_id is None and provider_session_id is None, "unexpected conversation identity")
    pool.check_open(name, caller=caller, target=spec["target"], route_digest=route_digest,
                    conversation_id=conversation_id, provider_session_id=provider_session_id)
    return Member(pool, name, caller, spec["target"], route_digest, grant["tariff"], grant["expires"],
                  conversation_id, provider_session_id)
