"""Join protected envelope, ledger and allowance evidence for a bounded member."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import time
from pathlib import Path
import re

from autonomy.baseline import decode_object, read_events, read_private_bytes, read_record
from autonomy.endpoint import EndpointError
from autonomy.ledger import Ledger, load_ledger
from autonomy.run import read_disposition
from autonomy.science_run._recovery import _baseline, _session, trusted_seal


__all__ = ["report"]


def independent_failure(directory, seal, ledger, findings, jobs):
    if seal is None or ledger is None:
        return None
    path = directory / "job-stop.json"
    try:
        row = read_record(path, strict_private=True)
    except (ValueError, OSError):
        return None
    if (
        set(row)
        != {"version", "session_id", "invocation_id", "phase", "intent", "seal_cause", "observation", "returncode"}
        or row["version"] != "job-stop.v1"
        or row["observation"] != "independent-failure"
        or row["session_id"] != ledger.session_id
        or row["seal_cause"] != seal["cause"]
        or row["phase"] not in ("original", "replay")
        or type(row["intent"]) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", row["intent"])
        or type(row["returncode"]) is not int
        or row["returncode"] == 0
    ):
        return None
    iid = row["invocation_id"]
    command = "run" if row["phase"] == "original" else "verify"
    matched = [
        job
        for job in jobs
        if job["actor"] == "session:" + row["session_id"]
        and job["role"] == "job"
        and job["request"] == {"invocation_id": iid, "phase": row["phase"]}
    ]
    if (
        len(matched) != 1
        or any(act.intent == row["intent"] for act in ledger.acts)
        or not any(inv.invocation == iid and inv.command == command for inv in ledger.invocations)
        or not any(f["code"] == "intent-unfulfilled" and f["ref"] == row["intent"] for f in findings)
    ):
        return None
    settlement = matched[0]["settlement"]
    if settlement is not None and (settlement["status"] != "unknown" or settlement.get("ledger_ref") is not None):
        return None
    return row


def model_evidence(reservation, receipts, claims, rates, *, require_claim):
    seq = reservation["request"]["seq"]
    bound = reservation["debit"]["micro_usd"]
    result = {"seq": seq, "status": "unknown", "reserved_micro_usd": bound, "actual_micro_usd": None}
    settled = reservation["settlement"]
    if not settled or settled["status"] != "complete":
        return result
    message = settled["message_id"]
    result["message_id"] = message
    matching = [r for r in receipts if r.get("envelope_id") == reservation["envelope"] and r.get("seq") == seq]
    if len(matching) != 1 or not message:
        return result
    receipt = matching[0]
    usage = settled["usage"]
    actual = (sum(rates[k] * count for k, count in usage.items()) + 999_999) // 1_000_000
    if (
        receipt.get("usage_status") != "complete"
        or receipt.get("usage") != usage
        or receipt.get("message_id") != message
        or receipt.get("upstream_request_id") != settled["request_id"]
        or receipt.get("reserved_micro_usd") != bound
        or receipt.get("actual_micro_usd") != actual
        or actual > bound
    ):
        return result
    if require_claim:
        found = [claim for claim in claims if claim["responseId"] == message]
        expected = dict(
            input=usage["input"],
            output=usage["output"],
            cacheRead=usage["cache_read"],
            cacheWrite=usage["cache_write_5m"] + usage["cache_write_1h"],
        )
        if len(found) != 1 or found[0]["usage"] != expected:
            return result
        result["claim"] = found[0]
    return dict(result, status="complete", actual_micro_usd=actual, usage=usage)


def _science(directory, actor, jobs, target):
    base = _baseline(directory)
    if target and (
        base.world_id != target["world_id"] or [h.chain_id for h in base.written] != [target["corpus_id"]]
    ):
        raise ValueError("baseline target differs")
    events, torn = read_events(directory)
    session = _session(events, Path(read_record(directory / "run.json")["operations"]))
    if session is None or actor != "session:" + session.session_id:
        raise ValueError("missing bound session")
    ledger = load_ledger(session.ledger_path, session.session_id)
    if (
        not isinstance(ledger, Ledger)
        or ledger.actor != actor
        or ledger.world != base.world_id
        or ledger.permit != base.permit
    ):
        raise ValueError("unusable bound ledger")
    seal = trusted_seal(directory, base.written, session, ledger, events, torn=torn)
    if seal is None or seal != read_record(directory / "seal.json"):
        raise ValueError("missing or inconsistent durable seal")
    disposition = read_disposition(directory)
    if not disposition:
        raise ValueError("missing disposition")
    terminal = decode_object(disposition[0])
    findings = terminal["findings"]
    acts = [act for act in ledger.acts if act.entry in terminal["members"].get(act.corpus, [])]

    def job_result(job):
        settled = job["settlement"] or {}
        ref = settled.get("ledger_ref")
        if (
            not ref
            or ref["session_id"] != session.session_id
            or job["actor"] != actor
            or not any(
                act.entry == ref["entry"] and act.invocation == job["request"]["invocation_id"] for act in acts
            )
        ):
            return dict(job["request"], status="unknown")
        return dict(job["request"], status=settled["status"], ledger_ref=ref)

    selection = None
    selection_path = directory / "selection.json"
    if selection_path.exists():
        selected = read_record(selection_path, strict_private=True)
        if (
            set(selected) != {"session_id", "proposition", "class"}
            or selected["session_id"] != session.session_id
            or selected["proposition"] != target["proposition"]
            or selected["class"]
            not in ("ready", "not-ready", "assessed-unevaluated", "assessed-not-admitted", "admitted")
        ):
            raise ValueError("queue receipt differs from bound target")
        selection = selected["class"]
    readback = None
    if terminal["disposition"] == "clean" and (directory / "readback.json").exists():
        value = read_record(directory / "readback.json")
        local = {address for act in acts for _, address in act.records}
        if (
            value["version"] != "research-readback.v1"
            or value["verification"] not in local
            or not all(value[k] == target[k] for k in ("world_id", "corpus_id", "spec", "proposition"))
        ):
            raise ValueError("readback differs from bound records")
        readback = value
    return {
        "session_id": session.session_id,
        "selection": selection,
        "disposition": terminal["disposition"],
        "findings": findings,
        "readback": readback,
        "opened_at": ledger.opened_at,
        "closed_at": terminal["closed_at"],
        "refusals": [
            inv.outcome["refusal"] for inv in ledger.invocations if inv.outcome and "refusal" in inv.outcome
        ],
        "seal_cause": seal["cause"],
        "stop": next((e["cause"] for e in events if e["event"] == "close-start"), None),
        "jobs": [job_result(j) for j in jobs],
        "independent_failure": independent_failure(directory, seal, ledger, findings, jobs),
        "records": [pair for act in acts for pair in act.records],
    }


def action_summary(last, scientific, waiting, closed, jobs):
    science = last and last["science"]
    if not science or not last["closed"] or last["science_error"]:
        return "recovery required", "recover the last envelope"
    if science["disposition"] != "clean":
        return "recovery required", "reconcile the last envelope"
    if any(j["status"] == "unknown" for j in jobs):
        return "recovery required", "reconcile the admitted job with its writer ledger"
    if scientific and scientific.get("scope") == "clean-environment" and scientific.get("verdict") == "passed":
        return "proved", None
    if scientific:
        return "recovery required", "inspect the independent verification verdict"
    if closed:
        return "recovery required", "review closed or exhausted authority"
    if waiting:
        return "approval requested", "answer the open question"
    if (
        not jobs
        and not science["refusals"]
        and science["selection"] in ("not-ready", "assessed-not-admitted", "admitted")
    ):
        return "nothing needed", None
    if science["refusals"]:
        return "recovery required", "review the scientific refusal against the bound inputs and rule"
    return "recovery required", "inspect incomplete scientific evidence"


def report(pool, member, state):
    snapshot = pool.snapshot(member)
    issued = pool.receipt()
    grant = snapshot["grant"]
    policy = grant["members"][member]
    band = policy["caller"] == "band"
    rates = grant["tariff"]["rates_micro_usd_per_mtok"]
    reservations = snapshot["reservations"]
    envelope_rows = []
    claimed = Counter(
        claim["responseId"] for row in snapshot["envelopes"] if row["report"] for claim in row["report"]["responses"]
    )
    settled_ids = Counter(
        item["settlement"]["message_id"] for item in reservations if item["role"] == "model" and item["settlement"]
    )
    for row in snapshot["envelopes"]:
        rid = row["id"]
        directory = state / ("analyst" if policy["caller"] == "analyst" else "runs") / rid
        reserved = [item for item in reservations if item["envelope"] == rid]
        turn = row["report"]
        claims = turn["responses"] if turn else []
        errors = []
        receipts = []
        science = None
        custody = {}
        science_error = None
        try:
            if directory.resolve() != directory:
                raise ValueError("envelope directory substituted")
            binding = read_record(directory / "allowance.json")
            if (binding["campaign_id"], binding["member_id"], binding["grant_digest"]) != (
                pool.name,
                member,
                issued["grant_digest"],
            ):
                raise ValueError("envelope grant differs")
            if band and binding["conversation_id"] != snapshot["conversation_id"]:
                raise ValueError("conversation differs")
            for filename in (
                "run.json",
                "baseline.json",
                "allowance.json",
                "disposition.json",
                "egress.jsonl",
                "seal.json",
                "selection.json",
                "job-stop.json",
                "readback.json",
                "events.jsonl",
            ):
                path = directory / filename
                if path.exists():
                    try:
                        custody[filename] = hashlib.sha256(read_private_bytes(path)).hexdigest()
                    except (ValueError, OSError):
                        custody[filename] = None
            if band:
                try:
                    science = _science(
                        directory, row["actor"], [r for r in reserved if r["role"] == "job"], policy["target"]
                    )
                except (ValueError, KeyError, TypeError, OSError, EndpointError) as exc:
                    science_error = str(exc)
            receipts = [decode_object(line) for line in read_private_bytes(directory / "egress.jsonl").splitlines()]
        except (ValueError, KeyError, TypeError, OSError, EndpointError) as exc:
            errors.append(str(exc))
        models = []
        for item in reserved:
            if item["role"] != "model":
                continue
            evidence = model_evidence(item, receipts, claims, rates, require_claim=band)
            mid = evidence.get("message_id")
            if mid and (claimed[mid] > 1 or settled_ids[mid] != 1):
                evidence.update(status="unknown", actual_micro_usd=None)
            models.append(evidence)
        if band and not turn:
            errors.append("missing validated turn")
        if any(c["responseId"] not in {m.get("message_id") for m in models} for c in claims):
            errors.append("unmatched response claim")
        if any(
            r.get("reserved_micro_usd") is not None and r.get("seq") not in {m["seq"] for m in models}
            for r in receipts
        ):
            errors.append("unmatched egress receipt")
        envelope_rows.append(
            {
                "envelope_id": rid,
                "closed": bool(row["closed"]),
                "turn": turn,
                "science": science,
                "models": models,
                "errors": errors,
                "science_error": science_error,
                "evidence_sha256": custody,
            }
        )
    models = [m for row in envelope_rows for m in row["models"]]
    unknown = [m for m in models if m["status"] != "complete"]
    known = sum(m["actual_micro_usd"] for m in models if m["status"] == "complete")
    sciences = [r["science"] for r in envelope_rows if r["science"]]
    scientific = next((s["readback"] for s in reversed(sciences) if s["readback"]), None)
    last = envelope_rows[-1] if envelope_rows else None
    terminal = last and last["science"]
    waiting = last and last["turn"] and last["turn"]["question_id"]
    expired = int(time.time()) >= grant["expires"]
    jobs = [j for science in sciences for j in science["jobs"]]
    job_starts = sum(r["role"] == "job" for r in reservations)
    jobs_complete = len(jobs) == job_starts and all(j["status"] != "unknown" for j in jobs)
    model_complete = not unknown and not any(row["errors"] for row in envelope_rows)
    exhausted = any(snapshot["remaining"][k] == 0 for k in ("attempts", "micro_usd"))
    outcome, decision = action_summary(last, scientific, waiting, expired or snapshot["closed"] or exhausted, jobs)
    if not model_complete and (not decision or outcome in ("proved", "nothing needed")):
        decision = "reconcile incomplete model accounting"
    usage = {k: sum(m["usage"][k] for m in models if m["status"] == "complete") for k in rates}
    elapsed = None
    if sciences:
        elapsed = (
            datetime.fromisoformat(sciences[-1]["closed_at"]) - datetime.fromisoformat(sciences[0]["opened_at"])
        ).total_seconds()
    return {
        "version": "allowance-report.v1",
        "elapsed_wall_seconds": elapsed,
        "action_outcome": outcome,
        "disposition": terminal["disposition"] if terminal else None,
        "scientific_outcome": scientific,
        "proposition": policy["target"].get("proposition"),
        "known_usage_tokens": usage,
        "next_decision": decision,
        "campaign_id": pool.name,
        "member_id": member,
        "wall_limit_seconds": grant["expires"] - issued["issued"],
        "expired": expired,
        "issued": issued["issued"],
        "expires": grant["expires"],
        "closed": snapshot["closed"],
        "campaign_limits": grant["limits"],
        "member_limits": policy["limits"],
        "remaining": snapshot["remaining"],
        "reserved": {k: sum(r["debit"][k] for r in reservations) for k in grant["limits"]},
        "conversation_id": snapshot["conversation_id"],
        "provider_session_id": snapshot["provider_session_id"],
        "attempts": len(models),
        "job_starts": job_starts,
        "job_accounting_complete": jobs_complete,
        "model_accounting_complete": model_complete,
        "known_micro_usd": known,
        "unknown_reserved_micro_usd": sum(m["reserved_micro_usd"] for m in unknown),
        "accounting_complete": model_complete and jobs_complete,
        "envelopes": envelope_rows,
    }
