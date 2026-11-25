import json

import pytest

from autonomy.allowance import AllowanceRefused, Campaign
from autonomy.baseline import append_event, publish_json
from autonomy.run import write_disposition
from autonomy.science_run.history import history, resume_handoff
from autonomy.tiers import REPORT_ONLY
from test_store import C, P, R, ROUTE, definition


def original(tmp_path):
    conf = definition()
    world, corpus, sid = "d" * 32, "c" * 32, "a" * 32
    target = {"world_id": world, "corpus_id": corpus}
    conf["members"]["action"]["target"] = target
    pool = Campaign.issue(tmp_path, conf)
    pool.open("action", R, caller="band", target=target, route_digest=ROUTE, conversation_id=C)
    pool.register_actor("action", R, sid)
    pool.seal("action", R)
    pool.record_turn("action", R, C, dict(version="band-turn.v1",provider_session_id=P,settlement=None,
                     submission_id=None,question_id=None,answer_id=None,responses=[]))
    run = tmp_path / R
    run.mkdir()
    publish_json(run / "allowance.json", dict(campaign_id="pool",member_id="action",conversation_id=C))
    ops = tmp_path / "ops"
    publish_json(run / "run.json", {"operations": str(ops)})
    publish_json(run / "baseline.json", dict(version=1,run=R,world=dict(root=str(tmp_path),id=world,
        genesis="1"*64,tip="1"*64), permit=REPORT_ONLY.permit.to_json(), mounts={},
        written={corpus:dict(root=str(tmp_path/"corpus"),role="corpus",genesis="1"*64,tip="1"*64)}))
    path = ops / "sessions" / sid / "ledger.v1"
    path.parent.mkdir(parents=True)
    append_event(run,"session-open",session_id=sid,ledger_path=str(path),basis_open="b"*64)
    append_event(run,"sealed",seal={"cause":"stop","sealed_tips":[dict(role="corpus",id=corpus,genesis="1"*64,tip="3"*64)],
                                     "basis_seal": "b"*64})
    records = [["u", "assessment:result"]]
    rows = [dict(line="session-open", session=sid,actor="session:"+sid,permit=REPORT_ONLY.permit.to_json(),world=world,at="t"),
            dict(line="invocation-open",invocation="pi-t6",command="assess",input_digest="9"*64,at="t"),
            dict(line="act",invocation="pi-t6",corpus=corpus,intent="2"*64,entry="3"*64,records=records),
            dict(line="invocation-close",invocation="pi-t6",outcome={"done":records}), dict(line="session-close",at="t")]
    path.write_text("".join(json.dumps(row,sort_keys=True,separators=(",",":"))+"\n" for row in rows))
    write_disposition(run,R,"clean",(),members={corpus:["3"*64]})
    return pool, path


def test_prior_history_joins_the_member_to_sealed_ordered_acts(tmp_path):
    pool, path = original(tmp_path)
    doc = history(pool, "action", tmp_path, C, P)
    row, = doc["envelopes"]
    assert row["session_id"] == path.parent.name
    invocation, = row["invocations"]
    assert invocation["command"] == "assess"
    assert invocation["acts"][0]["entry"] == "3" * 64
    outcome, = resume_handoff(doc)["sessions"][0]["outcomes"]
    assert outcome["records"] == [["u", "assessment:result"]]


@pytest.mark.parametrize("change", ["identity", "torn", "missing", "cross-member"])
def test_damaged_or_unrelated_history_refuses_the_whole_export(tmp_path, change):
    pool, path = original(tmp_path)
    if change == "torn":
        path.write_bytes(path.read_bytes()[:-1])
    elif change == "missing":
        path.unlink()
    elif change == "cross-member":
        (tmp_path/R/"allowance.json").write_text(json.dumps(dict(campaign_id="pool",member_id="smoke",conversation_id=C)))
    with pytest.raises(AllowanceRefused, match="allowance-scope" if change=="identity" else "allowance-unavailable"):
        history(pool, "action", tmp_path, C, C if change == "identity" else P)
