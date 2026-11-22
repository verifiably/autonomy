"""Published CLI evidence crossing the process boundary."""

import json
from pathlib import Path
import sys

import pytest

from autonomy.closing import close
from autonomy.evidence import Intent, Registration, Settlement
from autonomy.ledger import LedgerUnusable
from builders import RUN, SID, evidence


FIXTURES = Path(__file__).parent / "fixtures" / "run_endpoint"
MARKER = "\n… truncated at 400 bytes; continue with cursor scur1.page2\n"


def _response(body, args, refusal=None):
    return {"body": body, "args": args, "refusal": refusal}


@pytest.fixture
def science(tmp_path):
    config = tmp_path / "science.toml"
    config.write_text("[world]\n")
    return tmp_path / "science", config


def _program(science, *responses):
    executable, config = science
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"responses = json.loads({json.dumps(responses, ensure_ascii=False)!r})\n"
        f"assert sys.argv[2:4] == ['--config', {str(config)!r}], sys.argv\n"
        "assert sys.stdin.read() == ''\n"
        "args = sys.argv[1:2] + sys.argv[4:]\n"
        "response = next(row for row in responses if row['args'] == args)\n"
        "sys.stdout.write(response['body'])\n"
        "payload = {'invocation_id': 'proof'}\n"
        "if response['refusal'] is not None:\n"
        "    payload['refusal'] = response['refusal']\n"
        "print(json.dumps(payload), file=sys.stderr)\n"
        "sys.exit(3 if 'refusal' in payload else 0)\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)


def _reader(science, env):
    from autonomy import science_reads

    return science_reads.ScienceReader(*science, env=env)


def _heads():
    return (FIXTURES / "heads.v1.jsonl").read_text()


def _log():
    return (FIXTURES / "log.v1.jsonl").read_text()


@pytest.fixture
def env(tmp_path):
    return {"HOME": str(tmp_path), "PATH": "/usr/bin"}


def _log_args(after="2" * 64, through="6" * 64):
    return ["log", "--chain", "store", "--after", after, "--through", through]


def test_heads_and_log_from_the_pinned_producer_examples(science, env):
    _program(science, _response(_heads(), ["heads", "--resolve"]), _response(_log(), _log_args()))
    reader = _reader(science, env)
    heads = reader.heads(resolve=True)
    assert (heads.world_genesis, heads.world_head, heads.world_pending) == ("f" * 64, "f" * 64, ())
    corpus, store = heads.chains
    assert (corpus.role, corpus.chain_id, corpus.root, corpus.genesis, corpus.tip, corpus.pending) == (
        "corpus", "a" * 32, Path("/run/example/corpus"), "1" * 64, "1" * 64, (),
    )
    assert (store.role, store.chain_id, store.root, store.genesis, store.tip, store.pending) == (
        "store", "b" * 32, Path("/run/example/store"), "2" * 64, "6" * 64, (),
    )
    chain = reader.interval(store, after=store.genesis, through=store.tip)
    assert chain.on_chain
    assert chain.entries == (
        Registration("5" * 64, "3" * 32, None, None, frozenset({"incoming/a"})),
        Settlement("6" * 64, "3" * 32, "5" * 64, False),
    )


@pytest.mark.parametrize("name", ["VERIFIABLY_ENDPOINT", "VERIFIABLY_TOKEN_FILE"])
def test_present_handle_refuses_before_invoking_science(science, env, name):
    from autonomy import science_reads

    executable, config = science
    marker = config.parent / "started"
    executable.write_text(f"#!{sys.executable}\nopen({str(marker)!r}, 'w').close()\n")
    executable.chmod(0o700)
    with pytest.raises(science_reads.ReadUnavailable, match="handle"):
        science_reads.ScienceReader(executable, config, env={**env, name: ""}).heads(resolve=True)
    assert not marker.exists()


@pytest.mark.parametrize("case", ["ok", "stale", "repeated"])
def test_log_restores_split_rows_and_discards_failed_pages(science, env, case):
    from autonomy import science_reads

    body = _log()
    split = body.index("incoming/a") + 4
    tail = body[split:]
    refusal = {"code": "stale-cursor", "message": "records changed", "data": {}} if case == "stale" else None
    if case == "repeated":
        tail += MARKER
    args = _log_args()
    _program(
        science, _response(_heads(), ["heads"]), _response(body[:split] + MARKER, args),
        _response(tail, args + ["--continue", "scur1.page2"], refusal),
    )
    reader = _reader(science, env)
    store = reader.heads(resolve=False).chains[1]
    if case == "ok":
        assert len(reader.interval(store, after=store.genesis, through=store.tip).entries) == 2
    else:
        with pytest.raises(science_reads.ReadUnavailable):
            reader.interval(store, after=store.genesis, through=store.tip)


@pytest.mark.parametrize("key,value", [
    ("root", "/different/path"), ("genesis", "e" * 64), ("through", "e" * 64), ("version", "log.v2"),
])
def test_log_refuses_a_mismatching_header(science, env, key, value):
    from autonomy import science_reads

    first, rest = _log().split("\n", 1)
    header = json.loads(first)
    header[key] = value
    _program(science, _response(_heads(), ["heads"]), _response(json.dumps(header) + "\n" + rest, _log_args()))
    reader = _reader(science, env)
    store = reader.heads(resolve=False).chains[1]
    with pytest.raises(science_reads.ReadUnavailable):
        reader.interval(store, after=store.genesis, through=store.tip)


def test_log_header_alone_can_prove_an_empty_interval(science, env):
    header = json.loads(_log().split("\n")[0])
    header["through"] = "2" * 64
    _program(science, _response(_heads(), ["heads"]), _response(json.dumps(header) + "\n", _log_args(through="2" * 64)))
    reader = _reader(science, env)
    store = reader.heads(resolve=False).chains[1]
    chain = reader.interval(store, after=store.genesis, through=store.genesis)
    assert chain.on_chain and chain.entries == ()


@pytest.mark.parametrize("reason", ["tip-not-on-chain", "through-not-on-chain"])
def test_log_distinguishes_the_two_missing_tips(science, env, reason):
    from autonomy import science_reads

    refusal = {"code": "tip-unknown", "message": reason, "data": {"reason": reason}}
    _program(science, _response(_heads(), ["heads"]), _response("", _log_args(), refusal))
    reader = _reader(science, env)
    store = reader.heads(resolve=False).chains[1]
    if reason == "tip-not-on-chain":
        assert not reader.interval(store, after=store.genesis, through=store.tip).on_chain
    else:
        with pytest.raises(science_reads.ReadUnavailable):
            reader.interval(store, after=store.genesis, through=store.tip)


@pytest.mark.parametrize("key,value", [
    ("consumer_tag", False), ("fulfills", False),
    ("initial", [["../outside", [["kind", "absent"]]]]),
    ("final", [["incoming/a", [["kind", "garbage"]]]]),
])
def test_log_refuses_malformed_registrations(science, env, key, value):
    from autonomy import science_reads

    header, reg, settle = _log().splitlines()
    reg = json.loads(reg)
    reg[key] = value
    _program(science, _response(_heads(), ["heads"]), _response("\n".join((header, json.dumps(reg), settle, "")), _log_args()))
    reader = _reader(science, env)
    store = reader.heads(resolve=False).chains[1]
    with pytest.raises(science_reads.ReadUnavailable):
        reader.interval(store, after=store.genesis, through=store.tip)


@pytest.mark.parametrize("committed", [False, True])
def test_store_cut_act_with_unreadable_ledger_is_unwired(science, env, committed):
    header, registration, settlement = (json.loads(row) for row in _log().splitlines())
    settlement["committed"] = committed
    corpus_head = json.loads(_heads())["chains"][0]
    corpus_header = {key: corpus_head[key] for key in ("role", "id", "root", "genesis")}
    corpus_header.update(version="log.v1", after="1" * 64, through="4" * 64)
    intent = {"type": "intent", "digest": "4" * 64, "actor": RUN, "kind": "holdings",
              "holdings_act": "write", "store_id": "b" * 32, "location": "incoming/a"}
    corpus_args = ["log", "--chain", "a" * 32, "--after", "1" * 64, "--through", "4" * 64]
    _program(
        science, _response(_heads(), ["heads"]),
        _response("".join(json.dumps(row) + "\n" for row in (corpus_header, intent)), corpus_args),
        _response("".join(json.dumps(row) + "\n" for row in (header, registration, settlement)), _log_args()),
    )
    reader = _reader(science, env)
    corpus, store = reader.heads(resolve=False).chains
    chains = [reader.interval(corpus, after=corpus.genesis, through="4" * 64),
              reader.interval(store, after=store.genesis, through=store.tip)]
    assert chains[0].entries == (Intent("4" * 64, RUN, "holdings", "write", "incoming/a"),)
    verdict = close(evidence(chains, ledger=LedgerUnusable(SID, "ledger-malformed", "partial")))
    assert verdict.disposition == "unwired"
    assert {f.ref for f in verdict.findings if f.code == "outcome-unknown"} == {ch * 64 for ch in "456"}


def test_pending_transactions_preserve_both_ids(science, env):
    heads = json.loads(_heads())
    heads["world_pending"] = [["world-tx", "a" * 64]]
    heads["chains"][0]["pending"] = [["corpus-tx", "b" * 64]]
    _program(science, _response(json.dumps(heads) + "\n", ["heads", "--resolve"]))
    actual = _reader(science, env).heads(resolve=True)
    assert actual.world_pending == (("world-tx", "a" * 64),)
    assert actual.chains[0].pending == (("corpus-tx", "b" * 64),)


def test_heads_refuses_duplicate_chain_identities(science, env):
    from autonomy import science_reads

    heads = json.loads(_heads())
    heads["chains"].append({**heads["chains"][0], "root": "/another/corpus"})
    _program(science, _response(json.dumps(heads) + "\n", ["heads"]))
    with pytest.raises(science_reads.ReadUnavailable, match="duplicate"):
        _reader(science, env).heads(resolve=False)


def test_unrecognized_intent_preserves_nulls(science, env):
    header = json.loads(_log().splitlines()[0])
    row = {"type": "intent", "kind": None, "actor": None, "digest": "6" * 64}
    _program(science, _response(_heads(), ["heads"]),
             _response("".join(json.dumps(item) + "\n" for item in (header, row)), _log_args()))
    reader = _reader(science, env)
    store = reader.heads(resolve=False).chains[1]
    actual = reader.interval(store, after=store.genesis, through=store.tip)
    assert actual.entries == (Intent("6" * 64, None, None, None, None),)


def test_tree_write_preserves_the_intent_kind(science, env):
    header = json.loads(_log().splitlines()[0])
    row = {"type": "intent", "kind": "holdings", "actor": RUN, "digest": "6" * 64,
           "holdings_act": "tree-write", "store_id": "b" * 32, "location": "incoming/tree"}
    _program(science, _response(_heads(), ["heads"]),
             _response("".join(json.dumps(item) + "\n" for item in (header, row)), _log_args()))
    reader = _reader(science, env)
    store = reader.heads(resolve=False).chains[1]
    actual = reader.interval(store, after=store.genesis, through=store.tip)
    assert actual.entries == (Intent("6" * 64, RUN, "holdings", "tree-write", "incoming/tree"),)
