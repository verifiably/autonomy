"""The typed evidence the closing check reads (envelope design §9). Plan B fills it
from `science log`/`heads` output (`log.v1`) and the run directory; the check itself
does no I/O."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, TypeAlias

from autonomy.ledger import Ledger, LedgerUnusable
from autonomy.tiers import Permit


@dataclass(frozen=True)
class Intent:
    digest: str
    actor: str | None
    kind: str | None
    holdings_act: str | None
    location: str | None


@dataclass(frozen=True)
class Registration:
    digest: str
    txid: str
    fulfills: str | None
    consumer_tag: str | None
    registered_paths: frozenset[str]


@dataclass(frozen=True)
class Settlement:
    digest: str
    txid: str
    registration: str
    committed: bool


Entry: TypeAlias = Intent | Registration | Settlement


@dataclass(frozen=True)
class Chain:
    """A written chain's interval: the entries after the baseline tip, through the
    sealed tip (or the closing head for an orphan), in chain order."""

    chain_id: str
    role: Literal["corpus", "store"]
    on_chain: bool
    entries: tuple[Entry, ...]


@dataclass(frozen=True)
class RunEvidence:
    run_actor: str
    tier_permit: Permit
    baseline_available: bool
    ledger: Ledger | LedgerUnusable | None
    chains: tuple[Chain, ...] | None
    sealed: bool
    seal_timeout: bool
    orchestrator_lost: bool
    world_baseline: str
    world_closing: str | None
    mounts_baseline: Mapping[str, str]
    mounts_closing: Mapping[str, str] | None
    basis_open: str | None
    basis_seal: str | None
    later_ledgers: tuple[Ledger, ...] = ()
