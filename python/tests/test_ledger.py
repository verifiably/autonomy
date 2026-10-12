import json

import pytest

from autonomy.ledger import ActLine, Ledger, LedgerUnusable, load_ledger, read_ledger

SID = "a" * 32
CORPUS = "c" * 32
ENTRY = "e" * 64
INTENT = "f" * 64
PERMIT = {"kinds": ["note"], "act_families": ["corpus-write"], "ungoverned": False}


def line(**fields) -> bytes:
    return (json.dumps(fields, sort_keys=True, separators=(",", ":")) + "\n").encode()


def opening(session=SID) -> bytes:
    return line(line="session-open", session=session, actor=f"session:{session}", world="d" * 32,
                permit=PERMIT, at="2026-10-12T00:00:00Z", project=None)


def inv_open(inv="inv1") -> bytes:
    return line(line="invocation-open", invocation=inv, command="note", input_digest="0" * 64,
                at="2026-10-12T00:00:01Z")


def act(inv="inv1") -> bytes:
    return line(line="act", invocation=inv, corpus=CORPUS, entry=ENTRY, intent=INTENT, records=[["u", "note:1"]])


def inv_close(inv="inv1") -> bytes:
    return line(line="invocation-close", invocation=inv, outcome={"done": [["u", "note:1"]]})


def closing() -> bytes:
    return line(line="session-close", at="2026-10-12T00:00:02Z")


def test_a_complete_ledger():
    got = read_ledger(SID, opening() + inv_open() + act() + inv_close() + closing())
    assert isinstance(got, Ledger)
    assert got.actor == f"session:{SID}"
    assert got.permit.to_json() == PERMIT
    assert got.acts == (ActLine("inv1", CORPUS, ENTRY, INTENT),)
    assert got.closed and not got.torn_tail and got.open_invocations == ()
    assert not got.incomplete


def test_a_torn_tail_is_kept_and_marks_the_ledger_incomplete():
    got = read_ledger(SID, opening() + inv_open() + act()[:-5])
    assert isinstance(got, Ledger)
    assert got.torn_tail and got.incomplete
    assert got.acts == ()
    assert got.open_invocations == ("inv1",)


def test_an_open_invocation_marks_the_ledger_incomplete():
    got = read_ledger(SID, opening() + inv_open() + act())
    assert isinstance(got, Ledger) and got.incomplete and not got.closed


def malformed(raw: bytes) -> LedgerUnusable:
    got = read_ledger(SID, raw)
    assert isinstance(got, LedgerUnusable), got
    assert got.code == "ledger-malformed"
    return got


def test_empty_is_malformed():
    malformed(b"")


def test_unknown_line_kind_is_malformed():
    malformed(opening() + line(line="mystery", at="x"))


@pytest.mark.parametrize("discriminator", [[], {}, 1, None, True])
def test_a_non_string_discriminator_is_malformed_not_raised(discriminator):
    malformed(opening() + line(line=discriminator, at="x"))
    malformed(line(line=discriminator, at="x"))


def test_act_under_an_unopened_invocation_is_malformed():
    malformed(opening() + act())


def test_a_line_after_session_close_is_malformed():
    malformed(opening() + closing() + inv_open())


def test_extra_keys_are_malformed():
    malformed(opening() + line(line="session-close", at="x", extra=1))


def test_a_session_id_that_does_not_match_is_malformed():
    malformed(opening(session="b" * 32))


def test_first_line_not_session_open_is_malformed():
    malformed(inv_open() + opening())


def test_non_utf8_bytes_are_malformed_not_raised():  # Review Focus 1
    malformed(opening() + b"\xff\xfe\n")


def test_a_crlf_line_is_malformed_not_raised():  # Review Focus 1
    malformed(opening() + inv_open()[:-1] + b"\r\n" + closing())


def test_a_bad_digest_is_malformed():
    bad = line(line="act", invocation="inv1", corpus=CORPUS, entry="E" * 64, intent=INTENT, records=[])
    malformed(opening() + inv_open() + bad)


def test_a_missing_file_is_unavailable(tmp_path):
    got = load_ledger(tmp_path / "ledger.v1", SID)
    assert isinstance(got, LedgerUnusable) and got.code == "ledger-unavailable"


def test_load_reads_a_file(tmp_path):
    path = tmp_path / "ledger.v1"
    path.write_bytes(opening() + closing())
    got = load_ledger(path, SID)
    assert isinstance(got, Ledger) and got.closed


def test_deeply_nested_json_is_malformed_not_raised():
    # json.loads raises RecursionError, not ValueError, past the interpreter's depth
    malformed(opening() + b"[" * 200_000 + b"\n")
