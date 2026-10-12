"""Tiers as permits (envelope design §5).

A tier is data: a closed write permit in the serialized shape the kernel's
`session-open` ledger line records (sorted kind and family lists). autonomy imports
no kernel, so `KIND_FAMILIES` duplicates `beliefs.permit.KIND_ACTS`; the run's step-5
check compares the endpoint's recorded permit with these values, so a drift is
caught at the first run, not trusted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

COMMAND_REACHABLE_FAMILIES: frozenset[str] = frozenset({"corpus-write", "run", "holdings"})
ORDINARY_COORDINATION_KINDS: tuple[str, ...] = (
    "project", "question", "hypothesis", "topic", "theme", "task", "decision", "note",
)
_CORPUS_WRITE = frozenset({"corpus-write"})

KIND_FAMILIES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "proposition": _CORPUS_WRITE,
        "source-assertion": _CORPUS_WRITE,
        "assessment": _CORPUS_WRITE,
        "analysis-spec": _CORPUS_WRITE,
        "run": frozenset({"run", "corpus-write"}),
        "verification": _CORPUS_WRITE,
        "dataset": _CORPUS_WRITE,
        "source": _CORPUS_WRITE,
        "holdings-observation": frozenset({"holdings"}),
        "retraction": _CORPUS_WRITE,
        "instrument-certification": _CORPUS_WRITE,
        "coreference-attestation": _CORPUS_WRITE,
        "act-report": frozenset({"corpus-write", "run"}),
        "composite": _CORPUS_WRITE,
        **{kind: _CORPUS_WRITE for kind in ORDINARY_COORDINATION_KINDS},
        "publication": frozenset({"publish"}),
        "publication-binding": frozenset({"publish"}),
    }
)


class TierRefused(ValueError):
    """A tier that may not be opened unattended, or is not a tier at all."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Permit:
    kinds: frozenset[str]
    act_families: frozenset[str]
    ungoverned: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "kinds": sorted(self.kinds),
            "act_families": sorted(self.act_families),
            "ungoverned": self.ungoverned,
        }

    @classmethod
    def from_json(cls, value: object) -> Permit:
        if not isinstance(value, dict) or set(value) != {"kinds", "act_families", "ungoverned"}:
            raise ValueError("a permit carries exactly kinds, act_families and ungoverned")
        for what in ("kinds", "act_families"):
            items = value[what]
            if type(items) is not list or any(type(item) is not str for item in items):
                raise ValueError(f"permit {what} must be a list of strings")
        if type(value["ungoverned"]) is not bool:
            raise ValueError("permit ungoverned must be a boolean")
        return cls(frozenset(value["kinds"]), frozenset(value["act_families"]), value["ungoverned"])


@dataclass(frozen=True)
class Tier:
    name: str
    routes: Mapping[str, str]
    permit: Permit

    @property
    def writes_store(self) -> bool:
        """A tier minting holdings observations makes the store root a written chain."""
        return "holdings-observation" in self.routes

    def to_json(self) -> dict[str, object]:
        return {"name": self.name, "routes": dict(sorted(self.routes.items()))}


REPORT_ONLY = Tier("report-only", MappingProxyType({}), Permit(frozenset(), frozenset()))
COORDINATION = Tier(
    "coordination",
    MappingProxyType({}),
    Permit(frozenset(ORDINARY_COORDINATION_KINDS), _CORPUS_WRITE),
)


def mints(routes: Mapping[str, str]) -> Tier:
    if not routes:
        raise TierRefused("mints-empty", "a mints tier names at least one kind; an empty one is coordination")
    for kind, route in sorted(routes.items()):
        if kind not in KIND_FAMILIES:
            raise TierRefused("unknown-kind", f"{kind!r} is not a kernel kind")
        if route not in KIND_FAMILIES[kind]:
            raise TierRefused("route-not-admitted", f"{kind!r} is not written through {route!r}")
        if route not in COMMAND_REACHABLE_FAMILIES:
            raise TierRefused("family-unreachable", f"{route!r} is not a command-reachable family")
    permit = Permit(
        frozenset(ORDINARY_COORDINATION_KINDS) | frozenset(routes),
        _CORPUS_WRITE | frozenset(routes.values()),
    )
    return Tier("mints", MappingProxyType(dict(routes)), permit)


def tier(name: str, routes: Mapping[str, str] | None = None) -> Tier:
    if name == "publishes":
        raise TierRefused("publishes-unattended", "publishes is never granted unattended")
    if name in ("report-only", "coordination"):
        if routes:
            raise TierRefused("routes-unexpected", f"{name} takes no kind routes")
        return REPORT_ONLY if name == "report-only" else COORDINATION
    if name == "mints":
        return mints(routes or {})
    raise TierRefused("unknown-tier", f"{name!r} is not a tier")
