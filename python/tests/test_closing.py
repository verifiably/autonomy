import itertools

import pytest

from autonomy.closing import SEVERITY, close, disposition_of
from autonomy.ledger import LedgerUnusable
from autonomy.membership import Finding
from autonomy.tiers import REPORT_ONLY
from builders import INCOMPLETE, LATER, LATER_SID, act, corpus, evidence, intent, ledger, reg, settle

SPEC_ROWS = {
    "baseline-unavailable": "unwired", "ledger-unavailable": "unwired", "read-unavailable": "unwired",
    "ledger-malformed": "unwired", "seal-missing": "unwired", "chain-discontinuous": "quarantined",
    "entry-foreign": "quarantined", "outcome-unknown": "unwired", "intent-unfulfilled": "unwired",
    "seal-timeout": "unwired", "act-unverified": "unwired", "world-moved": "quarantined",
    "basis-moved": "quarantined", "session-unclosed": "unwired", "permit-mismatch": "unwired",
    "orchestrator-lost": "unwired", "mount-moved": None, "after-run": None,
    "egress-unproven": "unwired", "egress-lost": None, "egress-close-timeout": None,
}


def codes(verdict):
    return sorted({f.code for f in verdict.findings})


def test_severity_is_the_spec_table():
    assert dict(SEVERITY) == SPEC_ROWS


def test_an_idle_run_is_clean():  # Review Focus 2
    v = close(evidence())
    assert (v.disposition, v.findings, v.members) == ("clean", (), ())


def test_a_normal_run_is_clean_with_its_members():
    v = close(evidence([corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"))], ledger=ledger(act("r1", "i1"))))
    assert v.disposition == "clean" and v.members == ("i1", "r1", "s1")


@pytest.mark.parametrize(
    ("overrides", "code", "disposition"),
    [
        ({"baseline_available": False}, "baseline-unavailable", "unwired"),
        ({"ledger": None}, "ledger-unavailable", "unwired"),
        ({"ledger": LedgerUnusable("a" * 32, "ledger-malformed", "line 2: bad")}, "ledger-malformed", "unwired"),
        ({"ledger": ledger(torn_tail=True)}, "ledger-malformed", "unwired"),
        ({"chains": None}, "read-unavailable", "unwired"),
        ({"world_closing": None}, "read-unavailable", "unwired"),
        ({"mounts_closing": None}, "read-unavailable", "unwired"),
        ({"basis_seal": None}, "read-unavailable", "unwired"),
        ({"sealed": False, "basis_seal": None}, "seal-missing", "unwired"),
        ({"seal_timeout": True}, "seal-timeout", "unwired"),
        ({"orchestrator_lost": True}, "orchestrator-lost", "unwired"),
        ({"ledger": ledger(**INCOMPLETE)}, "session-unclosed", "unwired"),
        ({"ledger": ledger(permit=REPORT_ONLY.permit)}, "permit-mismatch", "unwired"),
        ({"world_closing": "w1"}, "world-moved", "quarantined"),
        ({"basis_seal": "b1"}, "basis-moved", "quarantined"),
    ],
)
def test_each_row(overrides, code, disposition):
    v = close(evidence(**overrides))
    assert code in codes(v)
    assert v.disposition == disposition


def test_a_moved_mount_is_reported_and_stays_clean():
    v = close(evidence(mounts_baseline={"m" * 32: "t0"}, mounts_closing={"m" * 32: "t1"}))
    assert codes(v) == ["mount-moved"] and v.disposition == "clean"


def test_a_vanished_mount_is_reported():
    v = close(evidence(mounts_baseline={"m" * 32: "t0"}, mounts_closing={}))
    assert codes(v) == ["mount-moved"]


def test_an_unsealed_run_skips_the_basis_comparison():
    v = close(evidence(sealed=False, basis_seal=None))
    assert "read-unavailable" not in codes(v) and "basis-moved" not in codes(v)


UNUSABLE = [None, LedgerUnusable("a" * 32, "ledger-malformed", "line 2: bad")]


@pytest.mark.parametrize("unusable", UNUSABLE)
def test_a_rewritten_chain_quarantines_even_without_a_usable_ledger(unusable):
    v = close(evidence([corpus(on_chain=False)], ledger=unusable))
    assert "chain-discontinuous" in codes(v)
    assert v.disposition == "quarantined"  # not hidden behind the ledger's unwired


@pytest.mark.parametrize("unusable", UNUSABLE)
def test_another_actors_intent_quarantines_even_without_a_usable_ledger(unusable):
    v = close(evidence([corpus(intent("i1"), intent("x1", actor="session:" + "9" * 32))], ledger=unusable))
    assert [f.ref for f in v.findings if f.code == "entry-foreign"] == ["x1"]
    assert v.disposition == "quarantined"


@pytest.mark.parametrize("unusable", UNUSABLE)
def test_without_a_usable_ledger_the_runs_own_entries_stay_unwired(unusable):
    v = close(evidence([corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"))], ledger=unusable))
    assert v.disposition == "unwired" and "entry-foreign" not in codes(v)


@pytest.mark.parametrize("unusable", UNUSABLE)
def test_an_intent_with_no_actor_is_foreign_with_or_without_a_ledger(unusable):
    chains = [corpus(intent("i1"), intent("n1", actor=None))]
    assert close(evidence(chains, ledger=unusable)).disposition == "quarantined"
    assert close(evidence(chains, ledger=ledger())).disposition == "quarantined"


@pytest.mark.parametrize("unusable", UNUSABLE)
def test_a_registration_fulfilling_a_foreign_intent_quarantines_without_a_ledger(unusable):
    # an intent outside the interval, or one under another actor, is never the run's
    for chains in ([corpus(intent("i1"), reg("r9", "outside"))],
                   [corpus(intent("x1", actor="session:" + "9" * 32), reg("r9", "x1"))]):
        v = close(evidence(chains, ledger=unusable))
        assert "r9" in [f.ref for f in v.findings if f.code == "entry-foreign"]
        assert v.disposition == "quarantined"


def test_without_a_usable_ledger_an_orphans_later_session_is_not_foreign():
    later = ledger(session_id=LATER_SID)
    v = close(evidence([corpus(intent("L1", actor=LATER))], ledger=None, sealed=False, basis_seal=None,
                       later_ledgers=(later,)))
    assert "entry-foreign" not in codes(v) and v.disposition == "unwired"


def test_membership_findings_reach_the_verdict():
    v = close(evidence([corpus(intent("x1", actor="session:" + "9" * 32))]))
    assert codes(v) == ["entry-foreign"] and v.disposition == "quarantined"


def test_quarantine_beats_unwired():
    assert disposition_of([Finding("seal-missing", "a", ""), Finding("entry-foreign", "b", "")]) == "quarantined"
    assert disposition_of([Finding("entry-foreign", "b", ""), Finding("seal-missing", "a", "")]) == "quarantined"


def test_unwired_beats_clean_and_reported_findings_do_not_count():
    assert disposition_of([Finding("mount-moved", "m", ""), Finding("act-unverified", "r", "")]) == "unwired"
    assert disposition_of([Finding("mount-moved", "m", ""), Finding("after-run", "e", "")]) == "clean"
    assert disposition_of([]) == "clean"


RANK = ["clean", "unwired", "quarantined"]


@pytest.mark.parametrize(("a", "b"), list(itertools.combinations(sorted(SPEC_ROWS), 2)))
def test_every_pair_takes_the_stronger(a, b):
    expected = max(SPEC_ROWS[a] or "clean", SPEC_ROWS[b] or "clean", key=RANK.index)
    assert disposition_of([Finding(a, "x", ""), Finding(b, "y", "")]) == expected


def test_egress_findings_are_reported_and_unproven_is_unwired():
    from autonomy.closing import SEVERITY

    assert SEVERITY["egress-unproven"] == "unwired"
    assert SEVERITY["egress-lost"] is None and SEVERITY["egress-close-timeout"] is None
