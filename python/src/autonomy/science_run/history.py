"""Read sealed member evidence using only protected host records."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from autonomy.allowance import AllowanceRefused
from autonomy.allowance import _contract as c
from autonomy.baseline import decode_object, read_events, read_record
from autonomy.endpoint import EndpointError
from autonomy.ledger import Ledger, load_ledger
from autonomy.run import read_disposition
from autonomy.science_run._recovery import _baseline, _session, trusted_seal


def _known(condition, message):
    c.require(condition, message, "allowance-unavailable")


def _sealed(runs, campaign, name, target, conversation, row):
    run = runs / c.hexadecimal(row["id"], 32)
    _known(run.resolve() == run and row["closed"], "predecessor is unsealed or substituted")
    _known(not row.get("disputes"), "predecessor has conflicting turn evidence")
    allowance = read_record(run / "allowance.json")
    _known((allowance["campaign_id"], allowance["member_id"], allowance["conversation_id"]) ==
           (campaign, name, conversation), "predecessor grant differs")
    disposition = read_disposition(run)
    _known(disposition and disposition[1] == 0, "predecessor requires recovery")
    terminal = decode_object(disposition[0])
    base = _baseline(run)
    _known(base.world_id == target["world_id"] and [h.chain_id for h in base.written] == [target["corpus_id"]],
           "predecessor target differs")
    events, torn = read_events(run)
    ops = Path(read_record(run / "run.json")["operations"])
    session = _session(events, ops)
    _known(not torn and session and row["actor"] == "session:" + session.session_id, "missing writer identity")
    ledger = load_ledger(session.ledger_path, session.session_id)
    _known(isinstance(ledger, Ledger) and not ledger.incomplete and ledger.actor == row["actor"]
           and ledger.world == base.world_id and ledger.permit == base.permit, "unusable predecessor ledger")
    _known(trusted_seal(run, base.written, session, ledger, events), "unconfirmed predecessor seal")
    invocations = []
    for invocation in ledger.invocations:
        acts = []
        for act in ledger.acts:
            if act.invocation == invocation.invocation:
                _known(act.entry in terminal["members"].get(act.corpus, []), "act outside closed interval")
                acts.append({"corpus": act.corpus, "entry": act.entry, "intent": act.intent, "records": list(act.records)})
        invocations.append({"session_id": session.session_id, **asdict(invocation), "acts": acts})
    return {"envelope_id": run.name, "session_id": session.session_id, "invocations": invocations}


def history(pool, name, runs, conversation, provider, *, current=None):
    c.uid(conversation)
    if provider is not None:
        c.uid(provider)
    snapshot = pool.snapshot(name)
    spec = snapshot["grant"]["members"][name]
    c.require(spec["caller"] == "band" and snapshot["conversation_id"] == conversation
              and snapshot["provider_session_id"] == provider, "different conversation or provider")
    prior = [row for row in snapshot["envelopes"] if row["id"] != current]
    c.require(provider is not None or (current is not None and not prior), "missing provider session")
    try:
        envelopes = [_sealed(runs, pool.name, name, spec["target"], conversation, row) for row in prior]
    except (OSError, ValueError, TypeError, KeyError, EndpointError, RecursionError) as exc:
        raise AllowanceRefused("allowance-unavailable", "cannot verify sealed member history") from exc
    return {"version": "member-history.v1", "conversation_id": conversation, "provider_session_id": provider,
            "envelopes": envelopes}


def resume_handoff(document):
    return {"sessions": [
        {"session_id": row["session_id"], "outcomes": [
            {"invocation": inv["invocation"], "command": inv["command"], "input_digest": inv["input_digest"],
             "records": inv["outcome"]["done"]} for inv in row["invocations"] if "done" in inv["outcome"]
        ]} for row in document["envelopes"]
    ]}
