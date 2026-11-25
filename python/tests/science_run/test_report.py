"""Protected closing evidence cannot turn an unfulfilled intent into a completed job."""

import json
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "different-cause",
        "no-seal",
        "terminal-act",
        "foreign-job",
        "no-finding",
        "symlink",
        "other-mode",
        "duplicate",
        "bool",
        "zero",
    ],
)
def test_independent_failure_requires_all_trusted_joins(tmp_path, change):
    from autonomy.science_run.report import independent_failure

    sid, intent = "f" * 32, "b" * 64
    record = {
        "version": "job-stop.v1",
        "session_id": sid,
        "invocation_id": "A",
        "intent": intent,
        "phase": "original",
        "seal_cause": "lease",
        "observation": "independent-failure",
        "returncode": 17,
    }
    job = {
        "role": "job",
        "actor": "session:" + sid,
        "request": {"invocation_id": "A", "phase": "original"},
        "settlement": {"status": "unknown", "ledger_ref": None},
    }
    seal = {"cause": "lease"}
    findings = [{"code": "intent-unfulfilled", "ref": intent}]
    ledger = SimpleNamespace(session_id=sid, invocations=[SimpleNamespace(invocation="A", command="run")], acts=())
    if change == "different-cause":
        seal = {"cause": "stop"}
    if change == "no-seal":
        seal = None
    if change == "terminal-act":
        job["settlement"] = {"status": "execution-failed", "ledger_ref": {"entry": "a" * 64}}
    if change == "foreign-job":
        job["actor"] = "session:" + "1" * 32
    if change == "no-finding":
        findings.clear()
    if change in ("bool", "zero"):
        record["returncode"] = True if change == "bool" else 0
    path = tmp_path / "job-stop.json"
    text = json.dumps(record)
    path.write_text(text if change != "duplicate" else text.replace('"phase":', '"phase":"replay","phase":'))
    path.chmod(0o644 if change == "other-mode" else 0o600)
    if change == "symlink":
        path.rename(tmp_path / "other")
        path.symlink_to(tmp_path / "other")
    assert independent_failure(tmp_path, seal, ledger, findings, [job]) == (record if change == "none" else None)


@pytest.mark.parametrize("fault", [None, "cache-conflict", "duplicate", "no-egress", "foreign-envelope"])
def test_response_join_requires_bijective_protected_evidence(fault):
    from autonomy.science_run.report import model_evidence

    envelope = "a" * 32
    usage = dict(input=2, output=3, cache_read=0, cache_write_5m=2, cache_write_1h=1)
    settled = dict(seq=1, request_id="request", message_id="msg1", status="complete", usage=usage)
    debit = dict(envelope=envelope, request={"seq": 1}, debit={"micro_usd": 100}, settlement=settled)
    receipt = dict(
        seq=1,
        envelope_id=envelope,
        upstream_request_id="request",
        message_id="msg1",
        usage=usage,
        usage_status="complete",
        actual_micro_usd=8,
        reserved_micro_usd=100,
    )
    claim = dict(
        conversationId=1, submissionId=0, responseId="msg1", usage=dict(input=2, output=3, cacheRead=0, cacheWrite=3)
    )
    if fault == "cache-conflict":
        claim["usage"]["cacheWrite"] = 0
    if fault == "foreign-envelope":
        receipt["envelope_id"] = "b" * 32
    row = model_evidence(
        debit,
        [] if fault == "no-egress" else [receipt],
        [claim] * (2 if fault == "duplicate" else 1),
        {k: 1000000 for k in usage},
        require_claim=True,
    )
    assert row["status"] == ("complete" if fault is None else "unknown")
    assert row["reserved_micro_usd"] == 100
    assert row["actual_micro_usd"] == (8 if fault is None else None)


@pytest.mark.parametrize(
    ("disposition", "queue", "jobs", "waiting", "closed", "expected"),
    [
        ("clean", "not-ready", [], False, None, "nothing needed"),
        ("clean", "assessed-unevaluated", [], False, None, "recovery required"),
        ("clean", "ready", [], True, None, "approval requested"),
        ("clean", "ready", ["run-cancelled"], False, "revoked", "recovery required"),
        ("clean", "ready", ["unknown"], False, None, "recovery required"),
        ("clean", "ready", ["execution-failed"], False, None, "recovery required"),
        ("quarantined", "not-ready", [], False, None, "recovery required"),
        ("unwired", "ready", [], False, None, "recovery required"),
    ],
)
def test_action_summary_preserves_distinct_scientific_and_kernel_outcomes(
    disposition, queue, jobs, waiting, closed, expected
):
    from autonomy.science_run.report import action_summary

    science = dict(disposition=disposition, selection=queue, refusals=[], jobs=[dict(status=s) for s in jobs])
    last = dict(science=science, closed=True, science_error=None)
    assert action_summary(last, None, waiting, closed, science["jobs"])[0] == expected
