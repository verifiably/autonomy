"""Interval membership (envelope design §9, *Transactions and the crash allowance*).

Every entry after a written chain's baseline tip is a member, part of the one crash
transaction (`outcome-unknown`), a foreign write, or, for an orphan with no seal, a
later session's write (`after-run`). Pure: typed evidence in, findings out.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from autonomy.evidence import Chain, Intent, Registration, Settlement
from autonomy.ledger import ActLine, Ledger

_STORE_OWNING_ACTS = ("write", "delete", "move-source")


@dataclass(frozen=True)
class Finding:
    code: str
    ref: str
    message: str


@dataclass(frozen=True)
class Membership:
    members: tuple[str, ...]
    findings: tuple[Finding, ...]


def classify(
    chains: Iterable[Chain],
    ledger: Ledger,
    run_actor: str,
    *,
    sealed: bool,
    later_ledgers: Iterable[Ledger] = (),
) -> Membership:
    findings: list[Finding] = []
    live: list[Chain] = []
    for chain in chains:
        if chain.on_chain:
            live.append(chain)
        else:
            findings.append(Finding("chain-discontinuous", chain.chain_id, "the baseline tip is not on this chain"))

    later = tuple(other for other in later_ledgers if f"session:{other.session_id}" != run_actor)
    after: set[str] = set()
    if not sealed:
        for chain in live:
            after |= _after_run(chain, run_actor, later)

    act_by_entry = {line.entry: line for line in ledger.acts}
    named = {line.intent for line in ledger.acts}
    intents = {e.digest: e for c in live for e in c.entries if isinstance(e, Intent) and e.digest not in after}
    in_progress = _act_in_progress(live, run_actor, after)
    member_intents = {d for d, i in intents.items() if d in named and i.actor == run_actor}

    owner: dict[str, str | None] = {}
    member_regs: set[str] = set()
    qualifiers: list[str] = []
    for chain in live:
        regs = [(i, e) for i, e in enumerate(chain.entries) if isinstance(e, Registration) and e.digest not in after]
        last_recorded = max((i for i, e in regs if e.digest in act_by_entry), default=-1)
        for i, e in regs:
            owner[e.digest] = _owner(e, chain, act_by_entry, intents, in_progress)
            line = act_by_entry.get(e.digest)
            if line is not None:
                fits = e.fulfills == line.intent or (chain.role == "store" and e.fulfills is None)
                if line.intent in member_intents and fits:
                    member_regs.add(e.digest)
            elif ledger.incomplete and owner[e.digest] in in_progress and i > last_recorded:
                qualifiers.append(e.digest)
    crash = qualifiers[0] if len(qualifiers) == 1 else None
    owning = {o for o in owner.values() if o is not None}
    fulfilled = {
        e.fulfills
        for c in live
        for e in c.entries
        if isinstance(e, Registration) and e.fulfills is not None and (e.digest in member_regs or e.digest == crash)
    }

    members: list[str] = []
    for chain in live:
        for e in chain.entries:
            if e.digest in after:
                findings.append(Finding("after-run", e.digest, "written by a later session once the run's claim was gone"))
            elif isinstance(e, Intent):
                if e.digest in member_intents:
                    members.append(e.digest)
                    if e.digest not in fulfilled:
                        findings.append(
                            Finding("intent-unfulfilled", e.digest, "a member intent with no fulfilling registration: a cut act")
                        )
                elif e.actor == run_actor and e.digest not in named:
                    if crash is not None and owner[crash] == e.digest:
                        findings.append(Finding("outcome-unknown", e.digest, "the intent of the act a crash interrupted"))
                    elif e.digest not in owning:
                        findings.append(
                            Finding("intent-unfulfilled", e.digest, "a run-actor intent that no act line names and nothing answers")
                        )
                    else:
                        findings.append(
                            Finding("entry-foreign", e.digest, "a run-actor intent owning a transaction no crash explains")
                        )
                else:
                    findings.append(Finding("entry-foreign", e.digest, "an intent neither the ledger nor the run's actor explains"))
            elif isinstance(e, Registration):
                if e.digest in member_regs:
                    members.append(e.digest)
                elif e.digest == crash:
                    findings.append(Finding("outcome-unknown", e.digest, "the crash transaction's registration"))
                else:
                    findings.append(Finding("entry-foreign", e.digest, "a registration the ledger does not explain"))
            else:
                if e.registration in member_regs:
                    members.append(e.digest)
                elif e.registration == crash:
                    findings.append(Finding("outcome-unknown", e.digest, "the crash transaction's settlement"))
                else:
                    findings.append(Finding("entry-foreign", e.digest, "a settlement the ledger does not explain"))

    findings.extend(_unverified(ledger.acts, live))
    return Membership(tuple(members), tuple(findings))


def _act_in_progress(live: list[Chain], run_actor: str, after: set[str]) -> frozenset[str]:
    """The last run-actor intent on the corpus chain, with its move-source when it is
    a move-destination: the kernel's `move` appends the two back to back."""
    run_intents = [
        e
        for c in live
        if c.role == "corpus"
        for e in c.entries
        if isinstance(e, Intent) and e.actor == run_actor and e.digest not in after
    ]
    if not run_intents:
        return frozenset()
    last = run_intents[-1]
    if last.holdings_act == "move-destination" and len(run_intents) > 1 and run_intents[-2].holdings_act == "move-source":
        return frozenset({last.digest, run_intents[-2].digest})
    return frozenset({last.digest})


def _owner(
    reg: Registration,
    chain: Chain,
    act_by_entry: dict[str, ActLine],
    intents: dict[str, Intent],
    in_progress: frozenset[str],
) -> str | None:
    line = act_by_entry.get(reg.digest)
    if line is not None:
        return line.intent
    if reg.fulfills is not None:
        return reg.fulfills
    if chain.role != "store":
        return None
    for digest in sorted(in_progress):
        candidate = intents[digest]
        if candidate.holdings_act in _STORE_OWNING_ACTS and candidate.location in reg.registered_paths:
            return digest
    return None


def _after_run(chain: Chain, run_actor: str, later: tuple[Ledger, ...]) -> set[str]:
    later_actors = {f"session:{other.session_id}" for other in later}
    later_named = {d for other in later for line in other.acts for d in (line.entry, line.intent)}
    fulfilled = {e.fulfills for e in chain.entries if isinstance(e, Registration) and e.fulfills is not None}

    def evidence(e: object) -> bool:
        return getattr(e, "digest", None) in later_named or (isinstance(e, Intent) and e.actor in later_actors)

    last_run = max(
        (i for i, e in enumerate(chain.entries) if isinstance(e, Intent) and e.actor == run_actor),
        default=-1,
    )
    start = next((i for i, e in enumerate(chain.entries) if i > last_run and evidence(e)), None)
    if start is None:
        return set()
    after: set[str] = set()
    for e in chain.entries[start:]:
        if e.digest in later_named:
            after.add(e.digest)
        elif isinstance(e, Intent) and e.actor in later_actors and e.digest not in fulfilled:
            after.add(e.digest)
        elif isinstance(e, Settlement) and e.registration in after:
            after.add(e.digest)
    return after


def _unverified(acts: tuple[ActLine, ...], live: list[Chain]) -> list[Finding]:
    entries = {e.digest: e for c in live for e in c.entries}
    committed = {e.registration for c in live for e in c.entries if isinstance(e, Settlement) and e.committed}
    out: list[Finding] = []
    for line in acts:
        registration, intent = entries.get(line.entry), entries.get(line.intent)
        if not isinstance(registration, Registration) or not isinstance(intent, Intent) or line.entry not in committed:
            out.append(Finding("act-unverified", line.entry, f"an act line of {line.invocation} is not verified in the interval"))
    return out
