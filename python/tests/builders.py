"""Readable evidence for the membership and closing tests: digests are short names,
because the pure check never validates their shape (the ledger reader does)."""

from autonomy.evidence import Chain, Intent, Registration, RunEvidence, Settlement
from autonomy.ledger import ActLine, Ledger
from autonomy.tiers import COORDINATION

SID = "a" * 32
RUN = f"session:{SID}"
LATER_SID = "b" * 32
LATER = f"session:{LATER_SID}"
PERMIT = COORDINATION.permit
INCOMPLETE = {"closed": False, "open_invocations": ("inv1",)}


def intent(digest, actor=RUN, act=None, location=None, kind="corpus-write"):
    return Intent(digest, actor, "holdings" if act else kind, act, location)


def reg(digest, fulfills=None, paths=()):
    return Registration(digest, f"tx-{digest}", fulfills, None, frozenset(paths))


def settle(digest, registration, committed=True):
    return Settlement(digest, f"tx-{registration}", registration, committed)


def corpus(*entries, on_chain=True):
    return Chain("c" * 32, "corpus", on_chain, tuple(entries))


def store(*entries):
    return Chain("s" * 32, "store", True, tuple(entries))


def act(entry, intent_digest, invocation="inv1"):
    return ActLine(invocation, "c" * 32, entry, intent_digest)


def ledger(*acts, closed=True, open_invocations=(), torn_tail=False, session_id=SID, permit=PERMIT):
    return Ledger(session_id, f"session:{session_id}", permit, tuple(acts), tuple(open_invocations), closed, torn_tail)


def evidence(chains=(), **overrides):
    fields = {
        "run_actor": RUN,
        "tier_permit": PERMIT,
        "baseline_available": True,
        "ledger": ledger(),
        "chains": tuple(chains),
        "sealed": True,
        "seal_timeout": False,
        "orchestrator_lost": False,
        "world_baseline": "w0",
        "world_closing": "w0",
        "mounts_baseline": {},
        "mounts_closing": {},
        "basis_open": "b0",
        "basis_seal": "b0",
        "later_ledgers": (),
    }
    fields.update(overrides)
    return RunEvidence(**fields)
