import pytest

from autonomy.tiers import (
    COMMAND_REACHABLE_FAMILIES,
    COORDINATION,
    REPORT_ONLY,
    Permit,
    TierRefused,
    mints,
    tier,
)

COORD_KINDS = ["decision", "hypothesis", "note", "project", "question", "task", "theme", "topic"]


def test_report_only_is_the_empty_permit():
    assert REPORT_ONLY.permit.to_json() == {"kinds": [], "act_families": [], "ungoverned": False}


def test_coordination_permit():
    assert COORDINATION.permit.to_json() == {
        "kinds": COORD_KINDS,
        "act_families": ["corpus-write"],
        "ungoverned": False,
    }


def test_mints_adds_named_kinds_and_their_routes():
    t = mints({"proposition": "corpus-write"})
    assert t.permit.to_json() == {
        "kinds": sorted([*COORD_KINDS, "proposition"]),
        "act_families": ["corpus-write"],
        "ungoverned": False,
    }
    assert t.to_json() == {"name": "mints", "routes": {"proposition": "corpus-write"}}
    assert not t.writes_store


def test_mints_with_run_and_holdings_writes_the_store():
    t = mints({"run": "run", "holdings-observation": "holdings"})
    assert t.permit.to_json()["act_families"] == ["corpus-write", "holdings", "run"]
    assert t.writes_store


@pytest.mark.parametrize(
    ("routes", "code"),
    [
        ({}, "mints-empty"),
        ({"nonsense": "corpus-write"}, "unknown-kind"),
        ({"proposition": "run"}, "route-not-admitted"),
        ({"publication": "publish"}, "family-unreachable"),
    ],
)
def test_mints_refusals(routes, code):
    with pytest.raises(TierRefused) as caught:
        mints(routes)
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("name", "routes", "code"),
    [
        ("publishes", None, "publishes-unattended"),
        ("report-only", {"proposition": "corpus-write"}, "routes-unexpected"),
        ("coordination", {"proposition": "corpus-write"}, "routes-unexpected"),
        ("mints", None, "mints-empty"),
        ("bogus", None, "unknown-tier"),
    ],
)
def test_tier_refusals(name, routes, code):
    with pytest.raises(TierRefused) as caught:
        tier(name, routes)
    assert caught.value.code == code


def test_tier_by_name():
    assert tier("report-only") is REPORT_ONLY
    assert tier("coordination") is COORDINATION
    assert tier("mints", {"proposition": "corpus-write"}) == mints({"proposition": "corpus-write"})


@pytest.mark.parametrize(
    "t",
    [
        REPORT_ONLY,
        COORDINATION,
        mints({"proposition": "corpus-write"}),
        mints({"run": "run", "act-report": "run", "holdings-observation": "holdings"}),
    ],
)
def test_no_tier_exceeds_command_reachable_families_or_is_ungoverned(t):
    # A tier built from the kernel's full permit would fail here: E1's negative.
    assert t.permit.act_families <= COMMAND_REACHABLE_FAMILIES
    assert t.permit.ungoverned is False


def test_permit_json_round_trip():
    p = mints({"proposition": "corpus-write"}).permit
    assert Permit.from_json(p.to_json()) == p


@pytest.mark.parametrize(
    "value",
    [
        None,
        {"kinds": [], "act_families": []},
        {"kinds": "x", "act_families": [], "ungoverned": False},
        {"kinds": [], "act_families": [1], "ungoverned": False},
        {"kinds": [], "act_families": [], "ungoverned": "no"},
        {"kinds": [], "act_families": [], "ungoverned": False, "extra": 1},
    ],
)
def test_permit_from_json_refuses_malformed(value):
    with pytest.raises(ValueError):
        Permit.from_json(value)
