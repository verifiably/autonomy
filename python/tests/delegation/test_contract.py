"""Validation and resource bounds for operator-issued development delegations."""
import os
import time
from dataclasses import replace

import pytest

from autonomy.delegation import (
    KIND,
    TERMINATION_SECONDS,
    Ceiling,
    definition,
    identifier,
    memory_floor,
    peak_memory,
    within,
)
from autonomy.run import RunRefused

MIB = 1 << 20
GIB = 1 << 30
PAGE = os.sysconf("SC_PAGE_SIZE")
CEILING = Ceiling(
    prepared_bytes=96 * MIB,
    storage_bytes=GIB,
    storage_inodes=131_072,
    receiver_bytes=768 * MIB,
    prepare_seconds=60,
)


def valid_grant(repo_path):
    writable = 96 * MIB
    return {
        "kind": KIND,
        "delegation_id": "grant-01",
        "source": "autonomy-e6771b decision c625235c: Approve.",
        "expires": int(time.time()) + 3600,
        "orchestrator": {"name": "band", "unit": "band-dev.service"},
        "repositories": {"autonomy": {"path": str(repo_path), "ref": "refs/heads/main"}},
        "actors": {"regen": ["/usr/bin/python3", "-I", "-c", "pass"]},
        "limits": {
            "starts": 3,
            "deadline_seconds": 120,
            "writable_bytes": writable,
            "memory_bytes": memory_floor(writable, CEILING),
            "tasks": 64,
        },
        "model": None,
    }


def test_valid_definition_and_constants(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    parsed = definition(valid_grant(repo), CEILING)
    assert parsed["kind"] == "development-delegation.v1"
    assert TERMINATION_SECONDS == 15
    assert identifier("grant_01-A") == "grant_01-A"


@pytest.mark.parametrize("bad_id", ["", "bad/id", "bad.id", "a" * 65, 12, None])
def test_identifier_refuses_malformed_values(bad_id):
    with pytest.raises(RunRefused) as caught:
        identifier(bad_id)
    assert caught.value.code == "delegation-invalid"


def test_largest_pool_floor():
    assert memory_floor(GIB, CEILING) == 1344 * MIB
    assert memory_floor(96 * MIB, CEILING) == 416 * MIB
    limits = {"writable_bytes": 96 * MIB, "memory_bytes": 416 * MIB, "starts": 1, "deadline_seconds": 10, "tasks": 16}
    assert peak_memory(limits, CEILING) == (416 + 96 + 768) * MIB


@pytest.mark.parametrize(
    ("case", "mutate"),
    [
        ("not-dict", lambda _g, _t: []),
        ("missing-key", lambda g, _t: {k: v for k, v in g.items() if k != "source"}),
        ("extra-key", lambda g, _t: {**g, "extra": 1}),
        ("bad-kind", lambda g, _t: {**g, "kind": "other.v1"}),
        ("bad-id", lambda g, _t: {**g, "delegation_id": "bad/id"}),
        ("empty-source", lambda g, _t: {**g, "source": "   "}),
        ("bool-expires", lambda g, _t: {**g, "expires": True}),
        ("zero-expires", lambda g, _t: {**g, "expires": 0}),
        ("orch-keys", lambda g, _t: {**g, "orchestrator": {"name": "band"}}),
        ("orch-name", lambda g, _t: {**g, "orchestrator": {**g["orchestrator"], "name": ""}}),
        ("unit-no-suffix", lambda g, _t: {**g, "orchestrator": {**g["orchestrator"], "unit": "band"}}),
        ("unit-scope", lambda g, _t: {**g, "orchestrator": {**g["orchestrator"], "unit": "band.scope"}}),
        ("unit-empty-stem", lambda g, _t: {**g, "orchestrator": {**g["orchestrator"], "unit": ".service"}}),
        ("unit-slash", lambda g, _t: {**g, "orchestrator": {**g["orchestrator"], "unit": "a/b.service"}}),
        ("unit-too-long", lambda g, _t: {**g, "orchestrator": {**g["orchestrator"], "unit": "x" * 248 + ".service"}}),
        ("repos-empty", lambda g, _t: {**g, "repositories": {}}),
        ("repo-bad-name", lambda g, _t: {**g, "repositories": {"bad/name": g["repositories"]["autonomy"]}}),
        ("repo-missing-path", lambda g, t: {**g, "repositories": {"autonomy": {"path": str(t / "absent"), "ref": "refs/heads/main"}}}),
        ("repo-relative-path", lambda g, _t: {**g, "repositories": {"autonomy": {"path": "rel/repo", "ref": "refs/heads/main"}}}),
        ("repo-file-path", lambda g, t: ((t / "f").write_text("x"), {**g, "repositories": {"autonomy": {"path": str(t / "f"), "ref": "refs/heads/main"}}})[1]),
        ("repo-symlink-path", lambda g, t: ((t / "sym").symlink_to(t / "repo"), {**g, "repositories": {"autonomy": {"path": str(t / "sym"), "ref": "refs/heads/main"}}})[1]),
        ("repo-duplicate-path", lambda g, _t: {**g, "repositories": {**g["repositories"], "dup": g["repositories"]["autonomy"]}}),
        ("ref-empty-branch", lambda g, _t: {**g, "repositories": {"autonomy": {**g["repositories"]["autonomy"], "ref": "refs/heads/"}}}),
        ("ref-double-dot", lambda g, _t: {**g, "repositories": {"autonomy": {**g["repositories"]["autonomy"], "ref": "refs/heads/a..b"}}}),
        ("ref-lock", lambda g, _t: {**g, "repositories": {"autonomy": {**g["repositories"]["autonomy"], "ref": "refs/heads/a.lock"}}}),
        ("ref-dot-component", lambda g, _t: {**g, "repositories": {"autonomy": {**g["repositories"]["autonomy"], "ref": "refs/heads/.a"}}}),
        ("ref-tag", lambda g, _t: {**g, "repositories": {"autonomy": {**g["repositories"]["autonomy"], "ref": "refs/tags/a"}}}),
        ("ref-empty-component", lambda g, _t: {**g, "repositories": {"autonomy": {**g["repositories"]["autonomy"], "ref": "refs/heads/a//b"}}}),
        ("ref-trailing-slash", lambda g, _t: {**g, "repositories": {"autonomy": {**g["repositories"]["autonomy"], "ref": "refs/heads/a/"}}}),
        ("ref-trailing-dot", lambda g, _t: {**g, "repositories": {"autonomy": {**g["repositories"]["autonomy"], "ref": "refs/heads/a."}}}),
        ("ref-at-brace", lambda g, _t: {**g, "repositories": {"autonomy": {**g["repositories"]["autonomy"], "ref": "refs/heads/a@{0}"}}}),
        ("ref-space", lambda g, _t: {**g, "repositories": {"autonomy": {**g["repositories"]["autonomy"], "ref": "refs/heads/a b"}}}),
        ("ref-reserved", lambda g, _t: {**g, "repositories": {"autonomy": {**g["repositories"]["autonomy"], "ref": "refs/heads/a~1"}}}),
        ("ref-control", lambda g, _t: {**g, "repositories": {"autonomy": {**g["repositories"]["autonomy"], "ref": "refs/heads/a\x1fb"}}}),
        ("actors-empty", lambda g, _t: {**g, "actors": {}}),
        ("actor-empty-argv", lambda g, _t: {**g, "actors": {"regen": []}}),
        ("actor-empty-exe", lambda g, _t: {**g, "actors": {"regen": [""]}}),
        ("actor-non-str", lambda g, _t: {**g, "actors": {"regen": [1]}}),
        ("actor-nul", lambda g, _t: {**g, "actors": {"regen": ["/usr/bin/true\x00"]}}),
        ("actor-duplicate-argv", lambda g, _t: {**g, "actors": {**g["actors"], "dup": list(g["actors"]["regen"])}}),
        ("limits-keys", lambda g, _t: {**g, "limits": {"starts": 1}}),
        ("starts-zero", lambda g, _t: {**g, "limits": {**g["limits"], "starts": 0}}),
        ("deadline-bool", lambda g, _t: {**g, "limits": {**g["limits"], "deadline_seconds": True}}),
        ("writable-below", lambda g, _t: {**g, "limits": {**g["limits"], "writable_bytes": 96 * MIB - PAGE}}),
        ("writable-above", lambda g, _t: {**g, "limits": {**g["limits"], "writable_bytes": GIB + PAGE, "memory_bytes": 2 * GIB}}),
        ("writable-unaligned", lambda g, _t: {**g, "limits": {**g["limits"], "writable_bytes": 105_000_000, "memory_bytes": 512 * MIB}}),
        ("memory-below-floor", lambda g, _t: {**g, "limits": {**g["limits"], "memory_bytes": memory_floor(g["limits"]["writable_bytes"], CEILING) - 1}}),
        ("tasks-below-floor", lambda g, _t: {**g, "limits": {**g["limits"], "tasks": 15}}),
        ("model-dict", lambda g, _t: {**g, "model": {}}),
        ("model-str", lambda g, _t: {**g, "model": "haiku"}),
    ],
)
def test_definition_refuses(tmp_path, case, mutate):
    repo = tmp_path / "repo"
    repo.mkdir()
    candidate = mutate(valid_grant(repo), tmp_path)
    with pytest.raises(RunRefused) as caught:
        definition(candidate, CEILING)
    assert caught.value.code == "delegation-invalid", case


def test_within_refuses_a_grant_above_a_lowered_ceiling(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    grant = definition(valid_grant(repo) | {
        "limits": {
            "starts": 1,
            "deadline_seconds": 30,
            "writable_bytes": 256 * MIB,
            "memory_bytes": memory_floor(256 * MIB, CEILING),
            "tasks": 16,
        }
    }, CEILING)
    within(grant["limits"], CEILING)
    for tightened in (
        replace(CEILING, storage_bytes=128 * MIB),
        replace(CEILING, prepared_bytes=512 * MIB),
        replace(CEILING, storage_inodes=CEILING.storage_inodes + 1),
    ):
        with pytest.raises(RunRefused) as caught:
            within(grant["limits"], tightened)
        assert caught.value.code == "delegation-bounds"
    with pytest.raises(RunRefused) as caught:
        within({**grant["limits"], "writable_bytes": 105_000_000}, CEILING)
    assert caught.value.code == "delegation-bounds"
