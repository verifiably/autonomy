from contextlib import contextmanager


import pytest

from autonomy.allowance.protocol import HostPeer, PeerClient
from autonomy.allowance import AllowanceRefused
from test_store import issued, R


def test_grant_peer_lifetime_and_late_settle(tmp_path):
    pool = issued(tmp_path)
    pool.register_actor("action", R, "c"*32)
    with HostPeer(pool, "action", R, "job") as peer:
        client = PeerClient(peer.take_socket())
        try:
            args = {"invocation_id": "pi-t11", "phase": "original"}
            assert client.call("reserve-job", args)["result"] == "admitted"
            assert client.call("reserve-job", args)["result"] == "already-recorded"
            pool.seal("action", R)
            with pytest.raises(AllowanceRefused, match="allowance-closed"):
                client.call("reserve-job", args | {"invocation_id": "pi-t12"})
            assert client.call("settle-job", args | {"status":"unknown", "ledger_ref":None})["result"] == "settled"
        finally:
            client.close()


def test_peer_cannot_reserve_for_other_role(tmp_path):
    pool = issued(tmp_path)
    with HostPeer(pool, "action", R, "model") as peer:
        client = PeerClient(peer.take_socket())
        try:
            with pytest.raises(AllowanceRefused, match="allowance-scope"):
                client.call("reserve-job", {"invocation_id":"pi-t2","phase":"replay"})
        finally:
            client.close()
    assert not pool.snapshot("action")["reservations"]


@pytest.mark.parametrize("lost", [None, "model", "job"])
def test_finish_closes_both_reservation_paths_before_either_child_drains(tmp_path, monkeypatch, lost):
    from contextlib import ExitStack, closing
    from threading import Barrier
    from types import SimpleNamespace

    from autonomy.science_run import _supervisor

    pool = issued(tmp_path)
    pool.register_actor("action", R, "c" * 32)
    member = SimpleNamespace(pool=pool, name="action")
    run_dir = tmp_path / R
    run_dir.mkdir()
    rendezvous = Barrier(2)
    with ExitStack() as stack:
        clients = {}
        for role in ("job", "model"):
            peer = stack.enter_context(HostPeer(pool, "action", R, role))
            clients[role] = stack.enter_context(closing(PeerClient(peer.take_socket())))
        job = {"invocation_id": "pi-t7", "phase": "replay"}
        model = {"seq": 1, "model": "fixture", "max_tokens": 80, "billing_mode": "standard"}
        assert clients["job"].call("reserve-job", job) == {"result": "admitted"}
        assert clients["model"].call("reserve-model", model) == {"result": "admitted"}

        def drain(role):
            rendezvous.wait(timeout=2)
            if role == lost:
                clients[role].close()
                return ()
            if role == "job":
                reserve = job | {"invocation_id": "pi-t8"}
                settle = job | {"status": "unknown", "ledger_ref": None}
            else:
                reserve = model | {"seq": 2}
                settle = dict(seq=1, status="unknown", request_id=None, message_id=None,
                              usage=dict.fromkeys(("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")))
            with pytest.raises(AllowanceRefused, match="allowance-closed"):
                clients[role].call("reserve-" + role, reserve)
            assert clients[role].call("settle-" + role, settle) == {"result": "settled"}
            return ()

        monkeypatch.setattr(_supervisor, "_seal", lambda *_: drain("job"))
        monkeypatch.setattr(_supervisor, "_close_proxy", lambda *_: drain("model"))
        assert _supervisor.finish(run_dir, object(), object(), None, (), "stop", member=member) == ()
    rows = pool.snapshot("action")["reservations"]
    assert len(rows) == 2
    for row in rows:
        assert (row["settlement"] is None) == (row["role"] == lost)


def test_foreign_ledger_ref_cannot_settle_a_reserved_job(tmp_path):
    pool = issued(tmp_path)
    pool.register_actor("action", R, "c" * 32)
    with HostPeer(pool, "action", R, "job") as peer:
        client = PeerClient(peer.take_socket())
        try:
            job = dict(invocation_id="pi-t8", phase="original")
            assert client.call("reserve-job", job) == {"result":"admitted"}
            ref = dict(session_id="d"*32, invocation_id="pi-t8", entry="e"*64)
            with pytest.raises(AllowanceRefused, match="allowance-scope"):
                client.call("settle-job", job | dict(status="completed",ledger_ref=ref))
            assert pool.snapshot("action")["reservations"][0]["settlement"] is None
        finally:
            client.close()


def test_published_wire_bytes_round_trip_through_production_peers(tmp_path):
    import json
    from pathlib import Path

    fixtures = Path(__file__).parents[1] / "fixtures" / "allowance"
    pool = issued(tmp_path)
    pool.register_actor("action", R, "c" * 32)
    for role in ("model", "job"):
        with HostPeer(pool, "action", R, role) as peer, peer.take_socket() as sock:
            def exchange(op, correlation):
                packet = (fixtures / (op + "-" + role + ".json")).read_bytes().strip()
                packet = packet.replace(b'"id":1,', f'"id":{correlation},'.encode(), 1)
                sock.sendall(packet)
                return sock.recv(16384)

            for i, (op, name) in enumerate((("reserve","admitted"),("reserve","already-recorded"),("settle","settled")),1):
                expected = (fixtures / (name + ".json")).read_bytes().strip().replace(b'"id":1,',f'"id":{i},'.encode(),1)
                assert exchange(op, i) == expected
    from autonomy.allowance._contract import digest
    launch = json.loads((fixtures / "research-launch.json").read_bytes())
    opened = json.loads((fixtures / "research-open.json").read_bytes())
    assert opened["research_action_digest"] == digest(launch["research_action"])


@pytest.mark.parametrize("response", [
    b'{"version":"allowance.v1","id":2,"result":"admitted"}',
    b'{"version":"allowance.v1","id":1,"result":"settled"}',
    b'{"version":"allowance.v1","id":1,"result":"admitted","extra":true}',
    b'{"version":"allowance.v1","id":1,"id":1,"result":"admitted"}',
    b'{"version":"allowance.v1","id":1,"result":"refused","code":"allowance-exhausted"}',
    b'{"version":"allowance.v1","id":1,"result":"admitted"}'.ljust(16385),
    '{"version":"allowance.v1","id":1,"result":"admitted"}'.encode("utf-16"),
])
def test_malformed_reply_never_admits(response):
    with _reply_peer(response) as client:
        with pytest.raises(AllowanceRefused, match="allowance-unavailable"):
            client.call("reserve-model", {})



@contextmanager
def _reply_peer(response):
    import socket
    sender, receiver = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    with sender, receiver:
        sender.sendall(response)
        yield PeerClient(receiver)


def test_exact_packet_limit_and_refusal_fixtures():
    from pathlib import Path
    fixtures = Path(__file__).parents[1] / "fixtures" / "allowance"
    packet = (fixtures / "admitted.json").read_bytes().ljust(16384)
    with _reply_peer(packet) as client:
        assert client.call("reserve-job", {}) == {"result": "admitted"}
    for name in ("closed", "exhausted"):
        with _reply_peer((fixtures / (name + ".json")).read_bytes()) as client:
            with pytest.raises(AllowanceRefused, match="allowance-" + name):
                client.call("reserve-job", {})
