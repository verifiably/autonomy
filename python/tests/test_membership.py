from autonomy.membership import classify
from builders import INCOMPLETE, LATER, LATER_SID, RUN, act, corpus, intent, ledger, reg, settle, store


def run(chains, led, *, sealed=True, later=()):
    m = classify(chains, led, RUN, sealed=sealed, later_ledgers=later)
    return m, sorted((f.code, f.ref) for f in m.findings)


# --- the ordinary cases -------------------------------------------------------------

def test_a_normal_commit_is_three_members():
    m, found = run([corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"))], ledger(act("r1", "i1")))
    assert m.members == ("i1", "r1", "s1")  # without the settlement rule, s1 would be foreign
    assert found == []


def test_a_holdings_write_fully_recorded_is_members():
    chains = [
        corpus(intent("h1", act="write", location="x"), reg("p1", "h1"), settle("ps1", "p1")),
        store(reg("w1", paths={"x"}), settle("ws1", "w1")),
    ]
    m, found = run(chains, ledger(act("w1", "h1"), act("p1", "h1")))
    assert found == []
    assert set(m.members) == {"h1", "p1", "ps1", "w1", "ws1"}


def test_a_move_fully_recorded_is_members():
    chains = [
        corpus(intent("m1", act="move-source", location="a"), intent("m2", act="move-destination", location="b"),
               reg("pa", "m1"), settle("psa", "pa"), reg("pb", "m2"), settle("psb", "pb")),
        store(reg("mv", paths={"a", "b"}), settle("smv", "mv")),
    ]
    _, found = run(chains, ledger(act("mv", "m1"), act("pa", "m1"), act("pb", "m2")))
    assert found == []


# --- foreign writes -----------------------------------------------------------------

def test_a_forged_run_actor_triple_under_a_complete_ledger_is_foreign():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"),
                     intent("i9"), reg("r9", "i9"), settle("s9", "r9"))]
    _, found = run(chains, ledger(act("r1", "i1")))
    assert found == [("entry-foreign", "i9"), ("entry-foreign", "r9"), ("entry-foreign", "s9")]


def test_another_actor_is_foreign():
    _, found = run([corpus(intent("x1", actor="session:" + "9" * 32))], ledger())
    assert found == [("entry-foreign", "x1")]


# --- the crash allowance ------------------------------------------------------------

def test_a_crashed_corpus_act_is_outcome_unknown():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"),
                     intent("i2"), reg("r2", "i2"), settle("s2", "r2"))]
    _, found = run(chains, ledger(act("r1", "i1"), **INCOMPLETE))
    # without propagation to the intent, i2 would be entry-foreign and quarantine the run
    assert found == [("outcome-unknown", "i2"), ("outcome-unknown", "r2"), ("outcome-unknown", "s2")]


def test_a_forged_triple_under_an_incomplete_ledger_keeps_its_first_sequence_foreign():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"),
                     intent("i2"), reg("r2", "i2"), settle("s2", "r2"),
                     intent("i3"), reg("r3", "i3"), settle("s3", "r3"))]
    _, found = run(chains, ledger(act("r1", "i1"), **INCOMPLETE))
    # only the act in progress (i3) can be a crash; i2 has an effect a crash cannot explain
    assert ("entry-foreign", "i2") in found and ("entry-foreign", "r2") in found
    assert ("outcome-unknown", "r3") in found


def test_a_holdings_first_phase_crash_is_outcome_unknown():
    chains = [corpus(intent("h1", act="write", location="x")),
              store(reg("w1", paths={"x"}), settle("ws1", "w1"))]
    _, found = run(chains, ledger(**INCOMPLETE))
    assert found == [("outcome-unknown", "h1"), ("outcome-unknown", "w1"), ("outcome-unknown", "ws1")]


def test_a_holdings_second_phase_crash_is_outcome_unknown():
    chains = [corpus(intent("h1", act="write", location="x"), reg("p1", "h1"), settle("ps1", "p1")),
              store(reg("w1", paths={"x"}), settle("ws1", "w1"))]
    m, found = run(chains, ledger(act("w1", "h1"), **INCOMPLETE))
    # an allowance keyed to unnamed intents would make p1 foreign
    assert found == [("outcome-unknown", "p1"), ("outcome-unknown", "ps1")]
    assert {"h1", "w1", "ws1"} <= set(m.members)


def test_several_store_transactions_touching_one_location_are_foreign():
    chains = [corpus(intent("h1", act="write", location="x")),
              store(reg("w1", paths={"x"}), settle("ws1", "w1"), reg("w2", paths={"x"}), settle("ws2", "w2"))]
    _, found = run(chains, ledger(**INCOMPLETE))
    # an allowance keyed to one intent would make both unwired
    assert ("entry-foreign", "w1") in found and ("entry-foreign", "w2") in found
    assert not any(code == "outcome-unknown" for code, _ in found)


def test_a_recorded_write_then_a_failed_intent_for_the_same_location():
    chains = [corpus(intent("h1", act="write", location="x"), reg("p1", "h1"), settle("ps1", "p1"),
                     intent("h2", act="write", location="x")),
              store(reg("w1", paths={"x"}), settle("ws1", "w1"))]
    for led in (ledger(act("w1", "h1"), act("p1", "h1")), ledger(act("w1", "h1"), act("p1", "h1"), **INCOMPLETE)):
        m, found = run(chains, led)
        # location matching across the interval would quarantine this
        assert found == [("intent-unfulfilled", "h2")]
        assert {"h1", "p1", "ps1", "w1", "ws1"} <= set(m.members)


def test_a_move_crashed_after_its_store_move():
    chains = [corpus(intent("m1", act="move-source", location="a"), intent("m2", act="move-destination", location="b")),
              store(reg("mv", paths={"a", "b"}), settle("smv", "mv"))]
    _, found = run(chains, ledger(**INCOMPLETE))
    assert found == [("intent-unfulfilled", "m2"), ("outcome-unknown", "m1"),
                     ("outcome-unknown", "mv"), ("outcome-unknown", "smv")]


def test_a_move_crashed_between_its_publishes():
    chains = [corpus(intent("m1", act="move-source", location="a"), intent("m2", act="move-destination", location="b"),
                     reg("pa", "m1"), settle("psa", "pa"), reg("pb", "m2"), settle("psb", "pb")),
              store(reg("mv", paths={"a", "b"}), settle("smv", "mv"))]
    _, found = run(chains, ledger(act("mv", "m1"), act("pa", "m1"), **INCOMPLETE))
    assert found == [("outcome-unknown", "m2"), ("outcome-unknown", "pb"), ("outcome-unknown", "psb")]


def test_a_store_transaction_outside_the_act_in_progress_is_foreign():
    chains = [corpus(intent("h1", act="write", location="x")), store(reg("w9", paths={"y"}), settle("s9", "w9"))]
    _, found = run(chains, ledger(**INCOMPLETE))
    assert found == [("entry-foreign", "s9"), ("entry-foreign", "w9"), ("intent-unfulfilled", "h1")]


# --- cut acts, unverified acts, rewritten chains ------------------------------------

def test_a_cut_route_act_is_intent_unfulfilled():
    _, found = run([corpus(intent("rr", kind="run-attempt"))], ledger())
    assert found == [("intent-unfulfilled", "rr")]


def test_a_cut_holdings_act_with_only_its_store_line_is_intent_unfulfilled():
    chains = [corpus(intent("h1", act="write", location="x")), store(reg("w1", paths={"x"}), settle("ws1", "w1"))]
    _, found = run(chains, ledger(act("w1", "h1")))
    assert found == [("intent-unfulfilled", "h1")]


def test_an_act_line_missing_from_the_chain_is_unverified():
    _, found = run([corpus()], ledger(act("r1", "i1")))
    assert found == [("act-unverified", "r1")]


def test_an_uncommitted_settlement_leaves_the_act_unverified():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1", committed=False))]
    _, found = run(chains, ledger(act("r1", "i1")))
    assert ("act-unverified", "r1") in found


def test_a_rewritten_chain_is_discontinuous():
    _, found = run([corpus(on_chain=False)], ledger())
    assert found == [("chain-discontinuous", "c" * 32)]


# --- the orphan tail ------------------------------------------------------------------

def later_ledger(*acts):
    return ledger(*acts, session_id=LATER_SID)


def test_an_orphan_keeps_its_crash_commit_and_sets_aside_the_later_session():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"),
                     intent("i2"), reg("r2", "i2"), settle("s2", "r2"),
                     intent("L1", actor=LATER), reg("Lr1", "L1"), settle("Ls1", "Lr1"))]
    _, found = run(chains, ledger(act("r1", "i1"), **INCOMPLETE), sealed=False, later=(later_ledger(act("Lr1", "L1")),))
    # truncating the tail at the last member would hide r2
    assert found == [("after-run", "L1"), ("after-run", "Lr1"), ("after-run", "Ls1"),
                     ("outcome-unknown", "i2"), ("outcome-unknown", "r2"), ("outcome-unknown", "s2")]


def test_a_later_sessions_failure_before_its_first_commit_is_after_run():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"),
                     intent("F1", actor=LATER),
                     intent("L1", actor=LATER), reg("Lr1", "L1"), settle("Ls1", "Lr1"))]
    _, found = run(chains, ledger(act("r1", "i1"), **INCOMPLETE), sealed=False, later=(later_ledger(act("Lr1", "L1")),))
    assert found == [("after-run", "F1"), ("after-run", "L1"), ("after-run", "Lr1"), ("after-run", "Ls1")]


def test_a_failure_only_later_session_is_after_run():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"),
                     intent("F1", actor=LATER), intent("F2", actor=LATER))]
    _, found = run(chains, ledger(act("r1", "i1"), **INCOMPLETE), sealed=False, later=(later_ledger(),))
    # a boundary found only through act lines would leave F1 and F2 foreign
    assert found == [("after-run", "F1"), ("after-run", "F2")]


def test_an_orphan_tail_with_no_later_ledger_stays_foreign():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"),
                     intent("x1", actor="session:" + "9" * 32), reg("xr", "x1"), settle("xs", "xr"))]
    _, found = run(chains, ledger(act("r1", "i1"), **INCOMPLETE), sealed=False)
    assert found == [("entry-foreign", "x1"), ("entry-foreign", "xr"), ("entry-foreign", "xs")]


def test_a_sealed_run_never_sets_entries_aside():
    chains = [corpus(intent("L1", actor=LATER), reg("Lr1", "L1"), settle("Ls1", "Lr1"))]
    _, found = run(chains, ledger(), sealed=True, later=(later_ledger(act("Lr1", "L1")),))
    assert found == [("entry-foreign", "L1"), ("entry-foreign", "Lr1"), ("entry-foreign", "Ls1")]
