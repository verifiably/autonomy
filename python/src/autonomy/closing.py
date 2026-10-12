"""The closing check (envelope design §9): every row of the table, membership, and
the precedence `quarantined` > `unwired` > `clean`. Pure: `RunEvidence` in,
`Verdict` out."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from autonomy.evidence import Intent, Registration, RunEvidence
from autonomy.ledger import LedgerUnusable
from autonomy.membership import Finding, classify

Disposition = Literal["clean", "unwired", "quarantined"]

SEVERITY: Mapping[str, Literal["unwired", "quarantined"] | None] = MappingProxyType(
    {
        "baseline-unavailable": "unwired",
        "ledger-unavailable": "unwired",
        "read-unavailable": "unwired",
        "ledger-malformed": "unwired",
        "seal-missing": "unwired",
        "chain-discontinuous": "quarantined",
        "entry-foreign": "quarantined",
        "outcome-unknown": "unwired",
        "intent-unfulfilled": "unwired",
        "seal-timeout": "unwired",
        "act-unverified": "unwired",
        "world-moved": "quarantined",
        "basis-moved": "quarantined",
        "session-unclosed": "unwired",
        "permit-mismatch": "unwired",
        "orchestrator-lost": "unwired",
        "mount-moved": None,
        "after-run": None,
    }
)
_RANK: Mapping[str, int] = MappingProxyType({"clean": 0, "unwired": 1, "quarantined": 2})


@dataclass(frozen=True)
class Verdict:
    disposition: Disposition
    findings: tuple[Finding, ...]
    members: tuple[str, ...]


def disposition_of(findings: Iterable[Finding]) -> Disposition:
    worst: Disposition = "clean"
    for finding in findings:
        severity = SEVERITY[finding.code]
        if severity is not None and _RANK[severity] > _RANK[worst]:
            worst = severity
    return worst


def close(evidence: RunEvidence) -> Verdict:
    findings: list[Finding] = []
    members: tuple[str, ...] = ()

    def add(code: str, ref: str, message: str) -> None:
        findings.append(Finding(code, ref, message))

    if not evidence.baseline_available:
        add("baseline-unavailable", "baseline.json", "the baseline record is unavailable")
    if evidence.orchestrator_lost:
        add("orchestrator-lost", "events.jsonl", "the orchestrator died; supervision was absent for an unknown interval")
    if not evidence.sealed:
        add("seal-missing", "seal.json", "the endpoint wrote no seal; the intervals run to the closing heads")
    if evidence.seal_timeout:
        add("seal-timeout", "events.jsonl", "the endpoint could not drain the act in flight in time")

    if evidence.world_closing is None:
        add("read-unavailable", "world", "the closing world head could not be read")
    elif evidence.world_closing != evidence.world_baseline:
        add("world-moved", "world", f"the world head moved from {evidence.world_baseline} to {evidence.world_closing}")

    if evidence.mounts_closing is None:
        add("read-unavailable", "mounts", "the closing heads of the read mounts could not be read")
    else:
        for corpus_id, tip in sorted(evidence.mounts_baseline.items()):
            if evidence.mounts_closing.get(corpus_id) != tip:
                add("mount-moved", corpus_id, "a read-mounted corpus moved during the run")

    if evidence.sealed:
        if evidence.basis_open is None or evidence.basis_seal is None:
            add("read-unavailable", "basis", "the endpoint did not report the basis at open and at seal")
        elif evidence.basis_open != evidence.basis_seal:
            add("basis-moved", "basis", "the derivation context changed between open and seal")

    if evidence.chains is None:
        add("read-unavailable", "chains", "a written chain's interval could not be read")

    ledger = evidence.ledger
    if ledger is None or isinstance(ledger, LedgerUnusable):
        if ledger is None:
            add("ledger-unavailable", "ledger.v1", "the session ledger is unavailable")
        else:
            add(ledger.code, ledger.session_id, ledger.message)
        if evidence.chains is not None:
            # membership needs the ledger, but some quarantine evidence does not:
            # an unusable ledger must never hide it behind `unwired`
            findings.extend(_ledgerless(evidence))
    else:
        if ledger.torn_tail:
            add("ledger-malformed", ledger.session_id, "a torn tail: the last line has no newline")
        if not ledger.closed or ledger.open_invocations:
            add("session-unclosed", ledger.session_id, "the ledger has no session-close, or an open invocation")
        if ledger.permit != evidence.tier_permit:
            add("permit-mismatch", ledger.session_id, "session-open's permit differs from the tier's")
        if evidence.chains is not None:
            result = classify(
                evidence.chains,
                ledger,
                evidence.run_actor,
                sealed=evidence.sealed,
                later_ledgers=evidence.later_ledgers,
            )
            findings.extend(result.findings)
            members = result.members

    return Verdict(disposition_of(findings), tuple(findings), members)


def _ledgerless(evidence: RunEvidence) -> list[Finding]:
    """The quarantine evidence that needs no ledger:

    - a rewritten chain;
    - an intent whose actor is not the run's (an undecodable actor included), unless,
      for an orphan with no seal, it is a later session's;
    - a registration fulfilling an intent that is outside the interval or is not the
      run's (or, for an orphan, a later session's).

    Every other entry needs the ledger to classify, and the ledger finding already
    makes the run `unwired`."""
    assert evidence.chains is not None
    later_actors = {f"session:{other.session_id}" for other in evidence.later_ledgers}

    def admissible(actor: str | None) -> bool:
        return actor == evidence.run_actor or (not evidence.sealed and actor in later_actors)

    live = [chain for chain in evidence.chains if chain.on_chain]
    intents = {e.digest: e for chain in live for e in chain.entries if isinstance(e, Intent)}
    out = [
        Finding("chain-discontinuous", chain.chain_id, "the baseline tip is not on this chain")
        for chain in evidence.chains
        if not chain.on_chain
    ]
    for chain in live:
        for entry in chain.entries:
            if isinstance(entry, Intent) and not admissible(entry.actor):
                out.append(Finding("entry-foreign", entry.digest, "an intent under another actor"))
            elif isinstance(entry, Registration) and entry.fulfills is not None:
                target = intents.get(entry.fulfills)
                if target is None or not admissible(target.actor):
                    out.append(Finding("entry-foreign", entry.digest, "a registration fulfilling an intent the run did not write"))
    return out
