# Envelope Plan A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the parts of the envelope that need nothing from `science` or
`beliefs`:

- the `verifiably-autonomy` package and its test front door;
- tiers as permits;
- an independent `ledger.v1` reader;
- the pure closing check (interval membership, the crash allowance, the orphan
  tail, every disposition row);
- the `bwrap` sandbox, with its static bind check, denial probe, launch and kill.

**Architecture:** One stdlib-only Python package under `python/src/autonomy/`, laid
out like the sibling repositories.

- **The closing check is pure.** It takes typed evidence (`evidence.py`) and returns a
  `Verdict`, so every row of spec §9 is a unit test over constructed evidence. Plan B
  fills that evidence from `science` reads and the run directory.
- **The sandbox is three small modules:** a data spec, a static check, and the
  `bwrap` driver. They are tested against the real `bwrap` on this host.

**Tech Stack:** Python ≥ 3.11 (stdlib only at runtime), hatchling, uv, pytest,
pytest-testmon, bubblewrap ≥ 0.13, Linux.

**Spec:** `docs/specs/2026-10-12-envelope-design.md`. This plan is §13 item 1 and
covers rows E1–E6 and E17. E1's CLI arm (`run --tier publishes` exits 2) belongs to
Plan B, which builds the CLI.

## Global Constraints

- No kernel import: the package depends on neither `verifiably-beliefs` nor
  `verifiably-science`, at runtime or in tests (AGENTS.md *Rules*; spec decision 1).
- Runtime is the stdlib only. The dev group is `pytest>=8` and `pytest-testmon>=2.2.0`.
- `requires-python = ">=3.11"`.
- Tests run through the front door: `just test-one <pytest args>` while working, then
  `just test-fast` before each commit. Never call `pytest` directly.
- Tests that need `bwrap` carry `@pytest.mark.bwrap`. They are not skipped when
  `bwrap` is present, and this host has it (bubblewrap 0.13.0).
- Finding codes, dispositions and precedence are exactly spec §9's table:
  `quarantined` > `unwired` > `clean`, and `mount-moved` and `after-run` are reported
  with no disposition.
- Every tier's `ungoverned` is `false`, and no tier names a family outside
  `{"corpus-write", "run", "holdings"}` (spec §5).
- The sandbox's fixed in-sandbox paths are `/run/va/endpoint.sock` and
  `/run/va/token` (spec §7).
- A process is launched into the sandbox only from the main thread. `--die-with-parent`
  is `PR_SET_PDEATHSIG`, which fires when the spawning thread exits (spec §8).
- Paths shown in docs and commit messages are repository-relative, never absolute
  machine paths.

## Review Focus

These five inputs are implied by the spec but exercised by no E row. Each has a test
in the task named:

1. **A ledger with non-UTF-8 bytes or a CRLF line** must come back as
   `LedgerUnusable("ledger-malformed")`, never as an exception (Task 2).
2. **An idle run**, with no entries in any interval and no act lines, must be
   `clean` (Task 4).
3. **A bind source that does not exist, or a dangling symlink,** must be
   `SandboxUnproven("bind-missing")`, not a crash (Task 5).
4. **A denied path that does not exist**, such as an unconfigured store root, must
   not fail the static check or the probe (Tasks 5 and 6).
5. **An actor argv whose binary is not in the sandbox** must make `launch` report
   `launch-failed`, or the process exit non-zero promptly, never hang (Task 7).

---

## File structure

| path | responsibility |
|---|---|
| `python/pyproject.toml` | package metadata, dev group, pytest marker |
| `python/src/autonomy/__init__.py` | package marker |
| `python/src/autonomy/tiers.py` | `Permit`, `Tier`, the tier constants, `mints`, `tier`, `TierRefused` |
| `python/src/autonomy/ledger.py` | `ActLine`, `Ledger`, `LedgerUnusable`, `read_ledger`, `load_ledger` |
| `python/src/autonomy/evidence.py` | `Intent`, `Registration`, `Settlement`, `Chain`, `RunEvidence` |
| `python/src/autonomy/membership.py` | `Finding`, `Membership`, `classify` (spec §9 membership) |
| `python/src/autonomy/closing.py` | `SEVERITY`, `Verdict`, `disposition_of`, `close` (spec §9 rows) |
| `python/src/autonomy/sandbox/__init__.py` | package marker |
| `python/src/autonomy/sandbox/spec.py` | `SandboxSpec` and the fixed system binds and paths |
| `python/src/autonomy/sandbox/static.py` | `SandboxUnproven`, `check_binds` |
| `python/src/autonomy/sandbox/bwrap.py` | `preflight`, `build_argv`, `probe`, `prove`, `launch`, `Sandboxed` |
| `python/tests/builders.py` | evidence builders shared by the membership and closing tests |
| `python/tests/test_*.py` | one test module per source module |
| `justfile` | real test, fast, one and setup commands |
| `.gitignore` | `.venv`, `__pycache__/`, `python/.testmondata` |
| `AGENTS.md` | the gates and the layout, now that a suite exists |

---

### Task 1: Package, front door, and tiers (E1)

**Files:**
- Create: `python/pyproject.toml`, `python/src/autonomy/__init__.py`, `python/src/autonomy/tiers.py`, `python/tests/test_tiers.py`
- Modify: `justfile` (the `fast_cmd`, `test_cmd`, `one_cmd`, `push_fast_cmd` and `setup_cmd` definitions), `.gitignore`, `AGENTS.md` (*Gates* and *Layout*)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Permit(kinds: frozenset[str], act_families: frozenset[str], ungoverned: bool = False)`,
    with `.to_json() -> dict` and `Permit.from_json(value: object) -> Permit`, which
    raises `ValueError`.
  - `Tier(name: str, routes: Mapping[str, str], permit: Permit)`, with
    `.writes_store -> bool` and `.to_json() -> dict`.
  - `REPORT_ONLY`, `COORDINATION`.
  - `mints(routes: Mapping[str, str]) -> Tier` and
    `tier(name: str, routes: Mapping[str, str] | None = None) -> Tier`.
  - `TierRefused(code, message)`, a `ValueError` with `.code`.
  - `ORDINARY_COORDINATION_KINDS`, `KIND_FAMILIES`, `COMMAND_REACHABLE_FAMILIES`.

- [ ] **Step 1: Create the package metadata**

`python/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "verifiably-autonomy"
version = "0.1.0"
description = "The envelope of verifiably: what may run unattended."
license = "MIT"
requires-python = ">=3.11"
dependencies = []

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-testmon>=2.2.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/autonomy"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["bwrap: needs bubblewrap and unprivileged user namespaces"]
```

`python/src/autonomy/__init__.py`:

```python
"""The envelope: what may run unattended (docs/specs/2026-10-12-envelope-design.md)."""
```

- [ ] **Step 2: Wire the front door**

In `justfile`, replace these definitions, keeping every comment above them:

```just
fast_cmd := "cd python && uv run pytest --testmon"
test_cmd := "cd python && uv run pytest"
```

```just
push_fast_cmd := fast_cmd
```

with the comment above `push_fast_cmd` reduced to:
`# testmon's own selection (form 2): fast_cmd serves.`

```just
one_cmd := "cd python && uv run pytest"
```

```just
setup_cmd := "just work-link python/.venv && cd python && uv sync"
```

Append to `.gitignore`:

```gitignore
# The package's virtual environment (a work-link symlink) and bytecode.
.venv
__pycache__/
# pytest-testmon selection data for `just test-fast`; per checkout, never committed.
python/.testmondata
```

In `AGENTS.md`, replace the *Gates* paragraph's sentence "Every test recipe is `true`
until the envelope is built; replace them in `justfile` with the first suite." with:

```markdown
The suite is pytest under `python/`: `just setup` once per worktree (uv sync), then
`just test-one <path | path::test | -k expr>` while working and `just test-fast`
(pytest-testmon) before committing. Tests marked `bwrap` need bubblewrap and
unprivileged user namespaces.
```

Replace the *Layout* bullet "docs/ — designs (specs) and plans for this layer, once
written; empty today." with:

```markdown
- `docs/specs/`, `docs/plans/` — this layer's designs and plans; the envelope's is
  `docs/specs/2026-10-12-envelope-design.md`.
- `python/` — the `verifiably-autonomy` package (`src/autonomy/`) and its tests.
```

- [ ] **Step 3: Run setup**

Run: `just setup`

Expected: `uv sync` creates `python/.venv` behind a work-link and writes
`python/uv.lock`. If `work-link` refuses the nested name `python/.venv`, stop and
report the error: do not drop the work-link step.

- [ ] **Step 4: Write the failing tier tests**

`python/tests/test_tiers.py`:

```python
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
```

- [ ] **Step 5: Run the tests to see them fail**

Run: `just test-one tests/test_tiers.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.tiers'`.

- [ ] **Step 6: Implement `tiers.py`**

`python/src/autonomy/tiers.py`:

```python
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
```

- [ ] **Step 7: Run the tests to see them pass**

Run: `just test-one tests/test_tiers.py`
Expected: PASS (every test).

- [ ] **Step 8: Run the fast loop and the gate, then commit**

Run: `just test-fast` (PASS), then `just check` (silent, exit 0).

```bash
git add python/pyproject.toml python/uv.lock python/src/autonomy/__init__.py python/src/autonomy/tiers.py python/tests/test_tiers.py justfile .gitignore AGENTS.md
git commit -m "feat(tiers): autonomy package, test front door, tiers as permits"
```

---

### Task 2: The `ledger.v1` reader (E3)

**Files:**
- Create: `python/src/autonomy/ledger.py`, `python/tests/test_ledger.py`

**Interfaces:**
- Consumes: `Permit.from_json` (Task 1).
- Produces:
  - `ActLine(invocation: str, corpus: str, entry: str, intent: str)`.
  - `Ledger(session_id: str, actor: str, permit: Permit, acts: tuple[ActLine, ...], open_invocations: tuple[str, ...], closed: bool, torn_tail: bool)`,
    with `.incomplete -> bool`.
  - `LedgerUnusable(session_id: str, code: str, message: str)`, where `code` is
    `ledger-malformed` or `ledger-unavailable`.
  - `read_ledger(session_id: str, raw: bytes) -> Ledger | LedgerUnusable`.
  - `load_ledger(path: Path, session_id: str) -> Ledger | LedgerUnusable`.

- [ ] **Step 1: Write the failing tests**

`python/tests/test_ledger.py`:

```python
import json

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
```

A CRLF line is malformed because `json.loads` accepts the trailing `\r` as
whitespace, so the reader must refuse it explicitly. The kernel's writer never emits
it.

- [ ] **Step 2: Run the tests to see them fail**

Run: `just test-one tests/test_ledger.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.ledger'`.

- [ ] **Step 3: Implement `ledger.py`**

`python/src/autonomy/ledger.py`:

```python
"""An independent reader of the kernel's session ledger, `ledger.v1` (envelope
design §4, §9; decision 10).

autonomy imports no kernel, so this reads the published format itself: canonical
JSON lines, `session-open` first, nothing after `session-close`. It never raises on
ledger content: a ledger it cannot use comes back as `LedgerUnusable`, which the
closing check turns into a finding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from autonomy.tiers import Permit

_KEYS: dict[str, frozenset[str]] = {
    "session-open": frozenset({"line", "session", "actor", "world", "permit", "at"}),
    "invocation-open": frozenset({"line", "invocation", "command", "input_digest", "at"}),
    "act": frozenset({"line", "invocation", "corpus", "entry", "intent", "records"}),
    "invocation-close": frozenset({"line", "invocation", "outcome"}),
    "session-close": frozenset({"line", "at"}),
    "select": frozenset({"line", "invocation", "project"}),
}
_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class ActLine:
    invocation: str
    corpus: str
    entry: str
    intent: str


@dataclass(frozen=True)
class Ledger:
    session_id: str
    actor: str
    permit: Permit
    acts: tuple[ActLine, ...]
    open_invocations: tuple[str, ...]
    closed: bool
    torn_tail: bool

    @property
    def incomplete(self) -> bool:
        """Spec §9: only an incomplete ledger can explain a missing act line."""
        return self.torn_tail or bool(self.open_invocations) or not self.closed


@dataclass(frozen=True)
class LedgerUnusable:
    session_id: str
    code: str
    message: str


class _Malformed(Exception):
    pass


def _hex(value: object, width: int, what: str) -> str:
    if type(value) is not str or len(value) != width or not set(value) <= _HEX:
        raise _Malformed(f"{what} must be {width} lowercase hexadecimal characters")
    return value


def _text(value: object, what: str) -> str:
    if type(value) is not str or not value:
        raise _Malformed(f"{what} must be a non-empty string")
    return value


def read_ledger(session_id: str, raw: bytes) -> Ledger | LedgerUnusable:
    try:
        return _parse(session_id, raw)
    except _Malformed as caught:
        return LedgerUnusable(session_id, "ledger-malformed", str(caught))


def load_ledger(path: Path, session_id: str) -> Ledger | LedgerUnusable:
    try:
        raw = path.read_bytes()
    except OSError as caught:
        return LedgerUnusable(session_id, "ledger-unavailable", f"{path.name}: {caught.strerror}")
    return read_ledger(session_id, raw)


def _parse(session_id: str, raw: bytes) -> Ledger:
    if not raw:
        raise _Malformed("the ledger is empty; no session-open")
    torn_tail = not raw.endswith(b"\n")
    chunks = raw.split(b"\n")[:-1]  # the last piece is empty after a newline, or the torn tail
    if not chunks:
        raise _Malformed("no complete line; no session-open")
    head: dict[str, object] | None = None
    acts: list[ActLine] = []
    opened: list[str] = []
    closed_invocations: set[str] = set()
    session_closed = False
    for number, chunk in enumerate(chunks, start=1):
        if chunk.endswith(b"\r"):
            raise _Malformed(f"line {number}: a CRLF line ending")
        try:
            parsed = json.loads(chunk.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as caught:
            raise _Malformed(f"line {number}: not JSON: {caught}") from caught
        if not isinstance(parsed, dict):
            raise _Malformed(f"line {number}: not a JSON object")
        kind = parsed.get("line")
        if kind not in _KEYS:
            raise _Malformed(f"line {number}: unknown line kind {kind!r}")
        expected = _KEYS[kind] | ({"project"} if kind == "session-open" and "project" in parsed else set())
        if set(parsed) != expected:
            raise _Malformed(f"line {number}: {kind} carries exactly {sorted(expected)}")
        if session_closed:
            raise _Malformed(f"line {number}: a line after session-close")
        if number == 1:
            if kind != "session-open":
                raise _Malformed("line 1 is not session-open")
            if _hex(parsed["session"], 32, "session id") != session_id:
                raise _Malformed(f"line 1 names session {parsed['session']}, not {session_id}")
            head = parsed
            continue
        if kind == "session-open":
            raise _Malformed(f"line {number}: a second session-open")
        if kind == "session-close":
            session_closed = True
            continue
        invocation = _text(parsed["invocation"], f"line {number}: invocation")
        if kind == "invocation-open":
            if invocation in opened:
                raise _Malformed(f"line {number}: invocation {invocation!r} is already open")
            opened.append(invocation)
            continue
        if invocation not in opened:
            raise _Malformed(f"line {number}: {kind} names invocation {invocation!r}, never opened")
        if invocation in closed_invocations:
            raise _Malformed(f"line {number}: {kind} names invocation {invocation!r}, already closed")
        if kind == "invocation-close":
            closed_invocations.add(invocation)
        elif kind == "act":
            acts.append(
                ActLine(
                    invocation,
                    _hex(parsed["corpus"], 32, f"line {number}: corpus id"),
                    _hex(parsed["entry"], 64, f"line {number}: entry digest"),
                    _hex(parsed["intent"], 64, f"line {number}: intent digest"),
                )
            )
    assert head is not None  # line 1 was checked above
    try:
        permit = Permit.from_json(head["permit"])
    except ValueError as caught:
        raise _Malformed(f"line 1: {caught}") from caught
    return Ledger(
        session_id=session_id,
        actor=_text(head["actor"], "line 1: actor"),
        permit=permit,
        acts=tuple(acts),
        open_invocations=tuple(i for i in opened if i not in closed_invocations),
        closed=session_closed,
        torn_tail=torn_tail,
    )
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `just test-one tests/test_ledger.py`
Expected: PASS.

- [ ] **Step 5: Run the fast loop, then commit**

Run: `just test-fast` (PASS).

```bash
git add python/src/autonomy/ledger.py python/tests/test_ledger.py
git commit -m "feat(ledger): independent ledger.v1 reader that never raises on content"
```

---

### Task 3: Evidence types and interval membership (E2 entry types, E17)

**Files:**
- Create: `python/src/autonomy/evidence.py`, `python/src/autonomy/membership.py`, `python/tests/builders.py`, `python/tests/test_membership.py`

**Interfaces:**
- Consumes: `Ledger`, `ActLine` (Task 2); `Permit` (Task 1).
- Produces:
  - `Intent(digest, actor: str | None, kind: str | None, holdings_act: str | None, location: str | None)`.
  - `Registration(digest, txid, fulfills: str | None, consumer_tag: str | None, registered_paths: frozenset[str])`.
  - `Settlement(digest, txid, registration: str, committed: bool)`.
  - `Chain(chain_id: str, role: Literal["corpus", "store"], on_chain: bool, entries: tuple[Intent | Registration | Settlement, ...])`.
  - `RunEvidence`, whose fields are listed in Step 3.
  - `Finding(code: str, ref: str, message: str)`.
  - `Membership(members: tuple[str, ...], findings: tuple[Finding, ...])`.
  - `classify(chains, ledger, run_actor, *, sealed, later_ledgers=()) -> Membership`.

- [ ] **Step 1: Write the shared builders**

`python/tests/builders.py`:

```python
"""Readable evidence for the membership and closing tests: digests are short names,
because the pure check never validates their shape (the ledger reader does)."""

from autonomy.evidence import Chain, Intent, Registration, RunEvidence, Settlement
from autonomy.ledger import ActLine, Ledger
from autonomy.tiers import COORDINATION

SID = "a" * 32
RUN = f"session:{SID}"
LATER_SID = "b" * 32
LATER = f"session:{LATER_SID}"
PERMIT = COORDINATION.permit
INCOMPLETE = {"closed": False, "open_invocations": ("inv1",)}


def intent(digest, actor=RUN, act=None, location=None, kind="corpus-write"):
    return Intent(digest, actor, "holdings" if act else kind, act, location)


def reg(digest, fulfills=None, paths=()):
    return Registration(digest, f"tx-{digest}", fulfills, None, frozenset(paths))


def settle(digest, registration, committed=True):
    return Settlement(digest, f"tx-{registration}", registration, committed)


def corpus(*entries, on_chain=True):
    return Chain("c" * 32, "corpus", on_chain, tuple(entries))


def store(*entries):
    return Chain("s" * 32, "store", True, tuple(entries))


def act(entry, intent_digest, invocation="inv1"):
    return ActLine(invocation, "c" * 32, entry, intent_digest)


def ledger(*acts, closed=True, open_invocations=(), torn_tail=False, session_id=SID, permit=PERMIT):
    return Ledger(session_id, f"session:{session_id}", permit, tuple(acts), tuple(open_invocations), closed, torn_tail)


def evidence(chains=(), **overrides):
    fields = {
        "run_actor": RUN,
        "tier_permit": PERMIT,
        "baseline_available": True,
        "ledger": ledger(),
        "chains": tuple(chains),
        "sealed": True,
        "seal_timeout": False,
        "orchestrator_lost": False,
        "world_baseline": "w0",
        "world_closing": "w0",
        "mounts_baseline": {},
        "mounts_closing": {},
        "basis_open": "b0",
        "basis_seal": "b0",
        "later_ledgers": (),
    }
    fields.update(overrides)
    return RunEvidence(**fields)
```

- [ ] **Step 2: Write the failing membership tests**

`python/tests/test_membership.py`:

```python
from autonomy.membership import classify
from builders import INCOMPLETE, LATER, LATER_SID, RUN, act, corpus, intent, ledger, reg, settle, store


def run(chains, led, *, sealed=True, later=()):
    m = classify(chains, led, RUN, sealed=sealed, later_ledgers=later)
    return m, sorted((f.code, f.ref) for f in m.findings)


# --- the ordinary cases -------------------------------------------------------------

def test_a_normal_commit_is_three_members():
    m, found = run([corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"))], ledger(act("r1", "i1")))
    assert m.members == ("i1", "r1", "s1")  # without the settlement rule, s1 would be foreign
    assert found == []


def test_a_holdings_write_fully_recorded_is_members():
    chains = [
        corpus(intent("h1", act="write", location="x"), reg("p1", "h1"), settle("ps1", "p1")),
        store(reg("w1", paths={"x"}), settle("ws1", "w1")),
    ]
    m, found = run(chains, ledger(act("w1", "h1"), act("p1", "h1")))
    assert found == []
    assert set(m.members) == {"h1", "p1", "ps1", "w1", "ws1"}


def test_a_move_fully_recorded_is_members():
    chains = [
        corpus(intent("m1", act="move-source", location="a"), intent("m2", act="move-destination", location="b"),
               reg("pa", "m1"), settle("psa", "pa"), reg("pb", "m2"), settle("psb", "pb")),
        store(reg("mv", paths={"a", "b"}), settle("smv", "mv")),
    ]
    _, found = run(chains, ledger(act("mv", "m1"), act("pa", "m1"), act("pb", "m2")))
    assert found == []


# --- foreign writes -----------------------------------------------------------------

def test_a_forged_run_actor_triple_under_a_complete_ledger_is_foreign():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"),
                     intent("i9"), reg("r9", "i9"), settle("s9", "r9"))]
    _, found = run(chains, ledger(act("r1", "i1")))
    assert found == [("entry-foreign", "i9"), ("entry-foreign", "r9"), ("entry-foreign", "s9")]


def test_another_actor_is_foreign():
    _, found = run([corpus(intent("x1", actor="session:" + "9" * 32))], ledger())
    assert found == [("entry-foreign", "x1")]


# --- the crash allowance ------------------------------------------------------------

def test_a_crashed_corpus_act_is_outcome_unknown():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"),
                     intent("i2"), reg("r2", "i2"), settle("s2", "r2"))]
    _, found = run(chains, ledger(act("r1", "i1"), **INCOMPLETE))
    # without propagation to the intent, i2 would be entry-foreign and quarantine the run
    assert found == [("outcome-unknown", "i2"), ("outcome-unknown", "r2"), ("outcome-unknown", "s2")]


def test_a_forged_triple_under_an_incomplete_ledger_keeps_its_first_sequence_foreign():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"),
                     intent("i2"), reg("r2", "i2"), settle("s2", "r2"),
                     intent("i3"), reg("r3", "i3"), settle("s3", "r3"))]
    _, found = run(chains, ledger(act("r1", "i1"), **INCOMPLETE))
    # only the act in progress (i3) can be a crash; i2 has an effect a crash cannot explain
    assert ("entry-foreign", "i2") in found and ("entry-foreign", "r2") in found
    assert ("outcome-unknown", "r3") in found


def test_a_holdings_first_phase_crash_is_outcome_unknown():
    chains = [corpus(intent("h1", act="write", location="x")),
              store(reg("w1", paths={"x"}), settle("ws1", "w1"))]
    _, found = run(chains, ledger(**INCOMPLETE))
    assert found == [("outcome-unknown", "h1"), ("outcome-unknown", "w1"), ("outcome-unknown", "ws1")]


def test_a_holdings_second_phase_crash_is_outcome_unknown():
    chains = [corpus(intent("h1", act="write", location="x"), reg("p1", "h1"), settle("ps1", "p1")),
              store(reg("w1", paths={"x"}), settle("ws1", "w1"))]
    m, found = run(chains, ledger(act("w1", "h1"), **INCOMPLETE))
    # an allowance keyed to unnamed intents would make p1 foreign
    assert found == [("outcome-unknown", "p1"), ("outcome-unknown", "ps1")]
    assert {"h1", "w1", "ws1"} <= set(m.members)


def test_several_store_transactions_touching_one_location_are_foreign():
    chains = [corpus(intent("h1", act="write", location="x")),
              store(reg("w1", paths={"x"}), settle("ws1", "w1"), reg("w2", paths={"x"}), settle("ws2", "w2"))]
    _, found = run(chains, ledger(**INCOMPLETE))
    # an allowance keyed to one intent would make both unwired
    assert ("entry-foreign", "w1") in found and ("entry-foreign", "w2") in found
    assert not any(code == "outcome-unknown" for code, _ in found)


def test_a_recorded_write_then_a_failed_intent_for_the_same_location():
    chains = [corpus(intent("h1", act="write", location="x"), reg("p1", "h1"), settle("ps1", "p1"),
                     intent("h2", act="write", location="x")),
              store(reg("w1", paths={"x"}), settle("ws1", "w1"))]
    for led in (ledger(act("w1", "h1"), act("p1", "h1")), ledger(act("w1", "h1"), act("p1", "h1"), **INCOMPLETE)):
        m, found = run(chains, led)
        # location matching across the interval would quarantine this
        assert found == [("intent-unfulfilled", "h2")]
        assert {"h1", "p1", "ps1", "w1", "ws1"} <= set(m.members)


def test_a_move_crashed_after_its_store_move():
    chains = [corpus(intent("m1", act="move-source", location="a"), intent("m2", act="move-destination", location="b")),
              store(reg("mv", paths={"a", "b"}), settle("smv", "mv"))]
    _, found = run(chains, ledger(**INCOMPLETE))
    assert found == [("intent-unfulfilled", "m2"), ("outcome-unknown", "m1"),
                     ("outcome-unknown", "mv"), ("outcome-unknown", "smv")]


def test_a_move_crashed_between_its_publishes():
    chains = [corpus(intent("m1", act="move-source", location="a"), intent("m2", act="move-destination", location="b"),
                     reg("pa", "m1"), settle("psa", "pa"), reg("pb", "m2"), settle("psb", "pb")),
              store(reg("mv", paths={"a", "b"}), settle("smv", "mv"))]
    _, found = run(chains, ledger(act("mv", "m1"), act("pa", "m1"), **INCOMPLETE))
    assert found == [("outcome-unknown", "m2"), ("outcome-unknown", "pb"), ("outcome-unknown", "psb")]


def test_a_store_transaction_outside_the_act_in_progress_is_foreign():
    chains = [corpus(intent("h1", act="write", location="x")), store(reg("w9", paths={"y"}), settle("s9", "w9"))]
    _, found = run(chains, ledger(**INCOMPLETE))
    assert found == [("entry-foreign", "s9"), ("entry-foreign", "w9"), ("intent-unfulfilled", "h1")]


# --- cut acts, unverified acts, rewritten chains ------------------------------------

def test_a_cut_route_act_is_intent_unfulfilled():
    _, found = run([corpus(intent("rr", kind="run-attempt"))], ledger())
    assert found == [("intent-unfulfilled", "rr")]


def test_a_cut_holdings_act_with_only_its_store_line_is_intent_unfulfilled():
    chains = [corpus(intent("h1", act="write", location="x")), store(reg("w1", paths={"x"}), settle("ws1", "w1"))]
    _, found = run(chains, ledger(act("w1", "h1")))
    assert found == [("intent-unfulfilled", "h1")]


def test_an_act_line_missing_from_the_chain_is_unverified():
    _, found = run([corpus()], ledger(act("r1", "i1")))
    assert found == [("act-unverified", "r1")]


def test_an_uncommitted_settlement_leaves_the_act_unverified():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1", committed=False))]
    _, found = run(chains, ledger(act("r1", "i1")))
    assert ("act-unverified", "r1") in found


def test_a_rewritten_chain_is_discontinuous():
    _, found = run([corpus(on_chain=False)], ledger())
    assert found == [("chain-discontinuous", "c" * 32)]


# --- the orphan tail ------------------------------------------------------------------

def later_ledger(*acts):
    return ledger(*acts, session_id=LATER_SID)


def test_an_orphan_keeps_its_crash_commit_and_sets_aside_the_later_session():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"),
                     intent("i2"), reg("r2", "i2"), settle("s2", "r2"),
                     intent("L1", actor=LATER), reg("Lr1", "L1"), settle("Ls1", "Lr1"))]
    _, found = run(chains, ledger(act("r1", "i1"), **INCOMPLETE), sealed=False, later=(later_ledger(act("Lr1", "L1")),))
    # truncating the tail at the last member would hide r2
    assert found == [("after-run", "L1"), ("after-run", "Lr1"), ("after-run", "Ls1"),
                     ("outcome-unknown", "i2"), ("outcome-unknown", "r2"), ("outcome-unknown", "s2")]


def test_a_later_sessions_failure_before_its_first_commit_is_after_run():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"),
                     intent("F1", actor=LATER),
                     intent("L1", actor=LATER), reg("Lr1", "L1"), settle("Ls1", "Lr1"))]
    _, found = run(chains, ledger(act("r1", "i1"), **INCOMPLETE), sealed=False, later=(later_ledger(act("Lr1", "L1")),))
    assert found == [("after-run", "F1"), ("after-run", "L1"), ("after-run", "Lr1"), ("after-run", "Ls1")]


def test_a_failure_only_later_session_is_after_run():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"),
                     intent("F1", actor=LATER), intent("F2", actor=LATER))]
    _, found = run(chains, ledger(act("r1", "i1"), **INCOMPLETE), sealed=False, later=(later_ledger(),))
    # a boundary found only through act lines would leave F1 and F2 foreign
    assert found == [("after-run", "F1"), ("after-run", "F2")]


def test_an_orphan_tail_with_no_later_ledger_stays_foreign():
    chains = [corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"),
                     intent("x1", actor="session:" + "9" * 32), reg("xr", "x1"), settle("xs", "xr"))]
    _, found = run(chains, ledger(act("r1", "i1"), **INCOMPLETE), sealed=False)
    assert found == [("entry-foreign", "x1"), ("entry-foreign", "xr"), ("entry-foreign", "xs")]


def test_a_sealed_run_never_sets_entries_aside():
    chains = [corpus(intent("L1", actor=LATER), reg("Lr1", "L1"), settle("Ls1", "Lr1"))]
    _, found = run(chains, ledger(), sealed=True, later=(later_ledger(act("Lr1", "L1")),))
    assert found == [("entry-foreign", "L1"), ("entry-foreign", "Lr1"), ("entry-foreign", "Ls1")]
```

Each expected list is sorted by `(code, ref)`, because `run` sorts the findings.

- [ ] **Step 3: Implement `evidence.py`**

`python/src/autonomy/evidence.py`:

```python
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
```

- [ ] **Step 4: Implement `membership.py`**

`python/src/autonomy/membership.py`:

```python
"""Interval membership (envelope design §9, *Transactions and the crash allowance*).

Every entry after a written chain's baseline tip is a member, part of the one crash
transaction (`outcome-unknown`), a foreign write, or, for an orphan with no seal, a
later session's write (`after-run`). Pure: typed evidence in, findings out.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from autonomy.evidence import Chain, Intent, Registration, Settlement
from autonomy.ledger import ActLine, Ledger

_STORE_OWNING_ACTS = ("write", "delete", "move-source")


@dataclass(frozen=True)
class Finding:
    code: str
    ref: str
    message: str


@dataclass(frozen=True)
class Membership:
    members: tuple[str, ...]
    findings: tuple[Finding, ...]


def classify(
    chains: Iterable[Chain],
    ledger: Ledger,
    run_actor: str,
    *,
    sealed: bool,
    later_ledgers: Iterable[Ledger] = (),
) -> Membership:
    findings: list[Finding] = []
    live: list[Chain] = []
    for chain in chains:
        if chain.on_chain:
            live.append(chain)
        else:
            findings.append(Finding("chain-discontinuous", chain.chain_id, "the baseline tip is not on this chain"))

    later = tuple(other for other in later_ledgers if f"session:{other.session_id}" != run_actor)
    after: set[str] = set()
    if not sealed:
        for chain in live:
            after |= _after_run(chain, run_actor, later)

    act_by_entry = {line.entry: line for line in ledger.acts}
    named = {line.intent for line in ledger.acts}
    intents = {e.digest: e for c in live for e in c.entries if isinstance(e, Intent) and e.digest not in after}
    in_progress = _act_in_progress(live, run_actor, after)
    member_intents = {d for d, i in intents.items() if d in named and i.actor == run_actor}

    owner: dict[str, str | None] = {}
    member_regs: set[str] = set()
    qualifiers: list[str] = []
    for chain in live:
        regs = [(i, e) for i, e in enumerate(chain.entries) if isinstance(e, Registration) and e.digest not in after]
        last_recorded = max((i for i, e in regs if e.digest in act_by_entry), default=-1)
        for i, e in regs:
            owner[e.digest] = _owner(e, chain, act_by_entry, intents, in_progress)
            line = act_by_entry.get(e.digest)
            if line is not None:
                fits = e.fulfills == line.intent or (chain.role == "store" and e.fulfills is None)
                if line.intent in member_intents and fits:
                    member_regs.add(e.digest)
            elif ledger.incomplete and owner[e.digest] in in_progress and i > last_recorded:
                qualifiers.append(e.digest)
    crash = qualifiers[0] if len(qualifiers) == 1 else None
    owning = {o for o in owner.values() if o is not None}
    fulfilled = {
        e.fulfills
        for c in live
        for e in c.entries
        if isinstance(e, Registration) and e.fulfills is not None and (e.digest in member_regs or e.digest == crash)
    }

    members: list[str] = []
    for chain in live:
        for e in chain.entries:
            if e.digest in after:
                findings.append(Finding("after-run", e.digest, "written by a later session once the run's claim was gone"))
            elif isinstance(e, Intent):
                if e.digest in member_intents:
                    members.append(e.digest)
                    if e.digest not in fulfilled:
                        findings.append(
                            Finding("intent-unfulfilled", e.digest, "a member intent with no fulfilling registration: a cut act")
                        )
                elif e.actor == run_actor and e.digest not in named:
                    if crash is not None and owner[crash] == e.digest:
                        findings.append(Finding("outcome-unknown", e.digest, "the intent of the act a crash interrupted"))
                    elif e.digest not in owning:
                        findings.append(
                            Finding("intent-unfulfilled", e.digest, "a run-actor intent that no act line names and nothing answers")
                        )
                    else:
                        findings.append(
                            Finding("entry-foreign", e.digest, "a run-actor intent owning a transaction no crash explains")
                        )
                else:
                    findings.append(Finding("entry-foreign", e.digest, "an intent neither the ledger nor the run's actor explains"))
            elif isinstance(e, Registration):
                if e.digest in member_regs:
                    members.append(e.digest)
                elif e.digest == crash:
                    findings.append(Finding("outcome-unknown", e.digest, "the crash transaction's registration"))
                else:
                    findings.append(Finding("entry-foreign", e.digest, "a registration the ledger does not explain"))
            else:
                if e.registration in member_regs:
                    members.append(e.digest)
                elif e.registration == crash:
                    findings.append(Finding("outcome-unknown", e.digest, "the crash transaction's settlement"))
                else:
                    findings.append(Finding("entry-foreign", e.digest, "a settlement the ledger does not explain"))

    findings.extend(_unverified(ledger.acts, live))
    return Membership(tuple(members), tuple(findings))


def _act_in_progress(live: list[Chain], run_actor: str, after: set[str]) -> frozenset[str]:
    """The last run-actor intent on the corpus chain, with its move-source when it is
    a move-destination: the kernel's `move` appends the two back to back."""
    run_intents = [
        e
        for c in live
        if c.role == "corpus"
        for e in c.entries
        if isinstance(e, Intent) and e.actor == run_actor and e.digest not in after
    ]
    if not run_intents:
        return frozenset()
    last = run_intents[-1]
    if last.holdings_act == "move-destination" and len(run_intents) > 1 and run_intents[-2].holdings_act == "move-source":
        return frozenset({last.digest, run_intents[-2].digest})
    return frozenset({last.digest})


def _owner(
    reg: Registration,
    chain: Chain,
    act_by_entry: dict[str, ActLine],
    intents: dict[str, Intent],
    in_progress: frozenset[str],
) -> str | None:
    line = act_by_entry.get(reg.digest)
    if line is not None:
        return line.intent
    if reg.fulfills is not None:
        return reg.fulfills
    if chain.role != "store":
        return None
    for digest in sorted(in_progress):
        candidate = intents[digest]
        if candidate.holdings_act in _STORE_OWNING_ACTS and candidate.location in reg.registered_paths:
            return digest
    return None


def _after_run(chain: Chain, run_actor: str, later: tuple[Ledger, ...]) -> set[str]:
    later_actors = {f"session:{other.session_id}" for other in later}
    later_named = {d for other in later for line in other.acts for d in (line.entry, line.intent)}
    fulfilled = {e.fulfills for e in chain.entries if isinstance(e, Registration) and e.fulfills is not None}

    def evidence(e: object) -> bool:
        return getattr(e, "digest", None) in later_named or (isinstance(e, Intent) and e.actor in later_actors)

    last_run = max(
        (i for i, e in enumerate(chain.entries) if isinstance(e, Intent) and e.actor == run_actor),
        default=-1,
    )
    start = next((i for i, e in enumerate(chain.entries) if i > last_run and evidence(e)), None)
    if start is None:
        return set()
    after: set[str] = set()
    for e in chain.entries[start:]:
        if e.digest in later_named:
            after.add(e.digest)
        elif isinstance(e, Intent) and e.actor in later_actors and e.digest not in fulfilled:
            after.add(e.digest)
        elif isinstance(e, Settlement) and e.registration in after:
            after.add(e.digest)
    return after


def _unverified(acts: tuple[ActLine, ...], live: list[Chain]) -> list[Finding]:
    entries = {e.digest: e for c in live for e in c.entries}
    committed = {e.registration for c in live for e in c.entries if isinstance(e, Settlement) and e.committed}
    out: list[Finding] = []
    for line in acts:
        registration, intent = entries.get(line.entry), entries.get(line.intent)
        if not isinstance(registration, Registration) or not isinstance(intent, Intent) or line.entry not in committed:
            out.append(Finding("act-unverified", line.entry, f"an act line of {line.invocation} is not verified in the interval"))
    return out
```

- [ ] **Step 5: Run the tests**

Run: `just test-one tests/test_membership.py`
Expected: PASS.

If a test fails, compare it with spec §9 and fix the code, not the expectation. The
expectations are the spec's rows. If the spec itself is contradictory, stop and
report.

- [ ] **Step 6: Run the fast loop, then commit**

Run: `just test-fast` (PASS).

```bash
git add python/src/autonomy/evidence.py python/src/autonomy/membership.py python/tests/builders.py python/tests/test_membership.py
git commit -m "feat(closing): interval membership with the one-transaction crash allowance"
```

---

### Task 4: The closing check's rows and precedence (E2)

**Files:**
- Create: `python/src/autonomy/closing.py`, `python/tests/test_closing.py`

**Interfaces:**
- Consumes: `RunEvidence` and the chain types (Task 3); `Finding` and `classify`
  (Task 3); `Ledger` and `LedgerUnusable` (Task 2).
- Produces:
  - `SEVERITY: Mapping[str, Literal["unwired", "quarantined"] | None]`.
  - `Verdict(disposition, findings: tuple[Finding, ...], members: tuple[str, ...])`.
  - `disposition_of(findings) -> Literal["clean", "unwired", "quarantined"]`.
  - `close(evidence: RunEvidence) -> Verdict`.

- [ ] **Step 1: Write the failing tests**

`python/tests/test_closing.py`:

```python
import itertools

import pytest

from autonomy.closing import SEVERITY, close, disposition_of
from autonomy.ledger import LedgerUnusable
from autonomy.membership import Finding
from autonomy.tiers import REPORT_ONLY
from builders import INCOMPLETE, act, corpus, evidence, intent, ledger, reg, settle

SPEC_ROWS = {
    "baseline-unavailable": "unwired", "ledger-unavailable": "unwired", "read-unavailable": "unwired",
    "ledger-malformed": "unwired", "seal-missing": "unwired", "chain-discontinuous": "quarantined",
    "entry-foreign": "quarantined", "outcome-unknown": "unwired", "intent-unfulfilled": "unwired",
    "seal-timeout": "unwired", "act-unverified": "unwired", "world-moved": "quarantined",
    "basis-moved": "quarantined", "session-unclosed": "unwired", "permit-mismatch": "unwired",
    "orchestrator-lost": "unwired", "mount-moved": None, "after-run": None,
}


def codes(verdict):
    return sorted({f.code for f in verdict.findings})


def test_severity_is_the_spec_table():
    assert dict(SEVERITY) == SPEC_ROWS


def test_an_idle_run_is_clean():  # Review Focus 2
    v = close(evidence())
    assert (v.disposition, v.findings, v.members) == ("clean", (), ())


def test_a_normal_run_is_clean_with_its_members():
    v = close(evidence([corpus(intent("i1"), reg("r1", "i1"), settle("s1", "r1"))], ledger=ledger(act("r1", "i1"))))
    assert v.disposition == "clean" and v.members == ("i1", "r1", "s1")


@pytest.mark.parametrize(
    ("overrides", "code", "disposition"),
    [
        ({"baseline_available": False}, "baseline-unavailable", "unwired"),
        ({"ledger": None}, "ledger-unavailable", "unwired"),
        ({"ledger": LedgerUnusable("a" * 32, "ledger-malformed", "line 2: bad")}, "ledger-malformed", "unwired"),
        ({"ledger": ledger(torn_tail=True)}, "ledger-malformed", "unwired"),
        ({"chains": None}, "read-unavailable", "unwired"),
        ({"world_closing": None}, "read-unavailable", "unwired"),
        ({"mounts_closing": None}, "read-unavailable", "unwired"),
        ({"basis_seal": None}, "read-unavailable", "unwired"),
        ({"sealed": False, "basis_seal": None}, "seal-missing", "unwired"),
        ({"seal_timeout": True}, "seal-timeout", "unwired"),
        ({"orchestrator_lost": True}, "orchestrator-lost", "unwired"),
        ({"ledger": ledger(**INCOMPLETE)}, "session-unclosed", "unwired"),
        ({"ledger": ledger(permit=REPORT_ONLY.permit)}, "permit-mismatch", "unwired"),
        ({"world_closing": "w1"}, "world-moved", "quarantined"),
        ({"basis_seal": "b1"}, "basis-moved", "quarantined"),
    ],
)
def test_each_row(overrides, code, disposition):
    v = close(evidence(**overrides))
    assert code in codes(v)
    assert v.disposition == disposition


def test_a_moved_mount_is_reported_and_stays_clean():
    v = close(evidence(mounts_baseline={"m" * 32: "t0"}, mounts_closing={"m" * 32: "t1"}))
    assert codes(v) == ["mount-moved"] and v.disposition == "clean"


def test_a_vanished_mount_is_reported():
    v = close(evidence(mounts_baseline={"m" * 32: "t0"}, mounts_closing={}))
    assert codes(v) == ["mount-moved"]


def test_an_unsealed_run_skips_the_basis_comparison():
    v = close(evidence(sealed=False, basis_seal=None))
    assert "read-unavailable" not in codes(v) and "basis-moved" not in codes(v)


def test_membership_findings_reach_the_verdict():
    v = close(evidence([corpus(intent("x1", actor="session:" + "9" * 32))]))
    assert codes(v) == ["entry-foreign"] and v.disposition == "quarantined"


def test_quarantine_beats_unwired():
    assert disposition_of([Finding("seal-missing", "a", ""), Finding("entry-foreign", "b", "")]) == "quarantined"
    assert disposition_of([Finding("entry-foreign", "b", ""), Finding("seal-missing", "a", "")]) == "quarantined"


def test_unwired_beats_clean_and_reported_findings_do_not_count():
    assert disposition_of([Finding("mount-moved", "m", ""), Finding("act-unverified", "r", "")]) == "unwired"
    assert disposition_of([Finding("mount-moved", "m", ""), Finding("after-run", "e", "")]) == "clean"
    assert disposition_of([]) == "clean"


RANK = ["clean", "unwired", "quarantined"]


@pytest.mark.parametrize(("a", "b"), list(itertools.combinations(sorted(SPEC_ROWS), 2)))
def test_every_pair_takes_the_stronger(a, b):
    expected = max(SPEC_ROWS[a] or "clean", SPEC_ROWS[b] or "clean", key=RANK.index)
    assert disposition_of([Finding(a, "x", ""), Finding(b, "y", "")]) == expected
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `just test-one tests/test_closing.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.closing'`.

- [ ] **Step 3: Implement `closing.py`**

`python/src/autonomy/closing.py`:

```python
"""The closing check (envelope design §9): every row of the table, membership, and
the precedence `quarantined` > `unwired` > `clean`. Pure: `RunEvidence` in,
`Verdict` out."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from autonomy.evidence import RunEvidence
from autonomy.ledger import LedgerUnusable
from autonomy.membership import Finding, classify

Disposition = Literal["clean", "unwired", "quarantined"]

SEVERITY: Mapping[str, Literal["unwired", "quarantined"] | None] = MappingProxyType(
    {
        "baseline-unavailable": "unwired",
        "ledger-unavailable": "unwired",
        "read-unavailable": "unwired",
        "ledger-malformed": "unwired",
        "seal-missing": "unwired",
        "chain-discontinuous": "quarantined",
        "entry-foreign": "quarantined",
        "outcome-unknown": "unwired",
        "intent-unfulfilled": "unwired",
        "seal-timeout": "unwired",
        "act-unverified": "unwired",
        "world-moved": "quarantined",
        "basis-moved": "quarantined",
        "session-unclosed": "unwired",
        "permit-mismatch": "unwired",
        "orchestrator-lost": "unwired",
        "mount-moved": None,
        "after-run": None,
    }
)
_RANK: Mapping[str, int] = MappingProxyType({"clean": 0, "unwired": 1, "quarantined": 2})


@dataclass(frozen=True)
class Verdict:
    disposition: Disposition
    findings: tuple[Finding, ...]
    members: tuple[str, ...]


def disposition_of(findings: Iterable[Finding]) -> Disposition:
    worst: Disposition = "clean"
    for finding in findings:
        severity = SEVERITY[finding.code]
        if severity is not None and _RANK[severity] > _RANK[worst]:
            worst = severity
    return worst


def close(evidence: RunEvidence) -> Verdict:
    findings: list[Finding] = []
    members: tuple[str, ...] = ()

    def add(code: str, ref: str, message: str) -> None:
        findings.append(Finding(code, ref, message))

    if not evidence.baseline_available:
        add("baseline-unavailable", "baseline.json", "the baseline record is unavailable")
    if evidence.orchestrator_lost:
        add("orchestrator-lost", "events.jsonl", "the orchestrator died; supervision was absent for an unknown interval")
    if not evidence.sealed:
        add("seal-missing", "seal.json", "the endpoint wrote no seal; the intervals run to the closing heads")
    if evidence.seal_timeout:
        add("seal-timeout", "events.jsonl", "the endpoint could not drain the act in flight in time")

    if evidence.world_closing is None:
        add("read-unavailable", "world", "the closing world head could not be read")
    elif evidence.world_closing != evidence.world_baseline:
        add("world-moved", "world", f"the world head moved from {evidence.world_baseline} to {evidence.world_closing}")

    if evidence.mounts_closing is None:
        add("read-unavailable", "mounts", "the closing heads of the read mounts could not be read")
    else:
        for corpus_id, tip in sorted(evidence.mounts_baseline.items()):
            if evidence.mounts_closing.get(corpus_id) != tip:
                add("mount-moved", corpus_id, "a read-mounted corpus moved during the run")

    if evidence.sealed:
        if evidence.basis_open is None or evidence.basis_seal is None:
            add("read-unavailable", "basis", "the endpoint did not report the basis at open and at seal")
        elif evidence.basis_open != evidence.basis_seal:
            add("basis-moved", "basis", "the derivation context changed between open and seal")

    if evidence.chains is None:
        add("read-unavailable", "chains", "a written chain's interval could not be read")

    ledger = evidence.ledger
    if ledger is None:
        add("ledger-unavailable", "ledger.v1", "the session ledger is unavailable")
    elif isinstance(ledger, LedgerUnusable):
        add(ledger.code, ledger.session_id, ledger.message)
    else:
        if ledger.torn_tail:
            add("ledger-malformed", ledger.session_id, "a torn tail: the last line has no newline")
        if not ledger.closed or ledger.open_invocations:
            add("session-unclosed", ledger.session_id, "the ledger has no session-close, or an open invocation")
        if ledger.permit != evidence.tier_permit:
            add("permit-mismatch", ledger.session_id, "session-open's permit differs from the tier's")
        if evidence.chains is not None:
            result = classify(
                evidence.chains,
                ledger,
                evidence.run_actor,
                sealed=evidence.sealed,
                later_ledgers=evidence.later_ledgers,
            )
            findings.extend(result.findings)
            members = result.members

    return Verdict(disposition_of(findings), tuple(findings), members)
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `just test-one tests/test_closing.py`
Expected: PASS.

- [ ] **Step 5: Run the fast loop, then commit**

Run: `just test-fast` (PASS).

```bash
git add python/src/autonomy/closing.py python/tests/test_closing.py
git commit -m "feat(closing): disposition rows and precedence over typed run evidence"
```

---

### Task 5: Sandbox spec and static bind check (E4)

**Files:**
- Create: `python/src/autonomy/sandbox/__init__.py`, `python/src/autonomy/sandbox/spec.py`, `python/src/autonomy/sandbox/static.py`, `python/tests/test_sandbox_static.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `SandboxSpec(scratch: Path, ro_binds: tuple[Path, ...] = (), socket: Path | None = None, token: Path | None = None, network: Literal["none", "host"] = "none", env: Mapping[str, str] = {})`,
    with `.bind_sources() -> tuple[Path, ...]`.
  - `SYSTEM_RO`, `SYSTEM_SYMLINKS`, `IN_SANDBOX_SOCKET`, `IN_SANDBOX_TOKEN`.
  - `SandboxUnproven(code, path, message)`, an `Exception` with `.code` and `.path`.
  - `check_binds(spec: SandboxSpec, denied: Iterable[Path]) -> None`.

- [ ] **Step 1: Write the failing tests**

`python/tests/test_sandbox_static.py`:

```python
from pathlib import Path

import pytest

from autonomy.sandbox.spec import SandboxSpec
from autonomy.sandbox.static import SandboxUnproven, check_binds


@pytest.fixture
def layout(tmp_path):
    world = tmp_path / "world"
    corpus = world / "corpus"
    ops = tmp_path / "ops"
    scratch = tmp_path / "scratch"
    tools = tmp_path / "tools"
    for d in (corpus, ops, scratch, tools):
        d.mkdir(parents=True)
    return {"world": world, "corpus": corpus, "ops": ops, "scratch": scratch, "tools": tools, "tmp": tmp_path}


def denied(layout):
    return (layout["world"], layout["corpus"], layout["ops"])


def refused(spec, layout, code="bind-overlaps-denied"):
    with pytest.raises(SandboxUnproven) as caught:
        check_binds(spec, denied(layout))
    assert caught.value.code == code
    return caught.value


def test_an_unrelated_bind_passes(layout):
    check_binds(SandboxSpec(scratch=layout["scratch"], ro_binds=(layout["tools"],)), denied(layout))


def test_a_symlink_alias_of_a_corpus_is_refused(layout):
    alias = layout["tmp"] / "alias"
    alias.symlink_to(layout["corpus"])
    refused(SandboxSpec(scratch=layout["scratch"], ro_binds=(alias,)), layout)


def test_a_parent_of_the_operations_root_is_refused(layout):
    refused(SandboxSpec(scratch=layout["scratch"], ro_binds=(layout["tmp"],)), layout)


def test_a_child_of_a_denied_root_is_refused(layout):
    inner = layout["corpus"] / "inner"
    inner.mkdir()
    refused(SandboxSpec(scratch=layout["scratch"], ro_binds=(inner,)), layout)


def test_the_root_directory_is_refused(layout):
    refused(SandboxSpec(scratch=layout["scratch"], ro_binds=(Path("/"),)), layout)


def test_a_scratch_inside_a_denied_root_is_refused(layout):
    inside = layout["ops"] / "scratch"
    inside.mkdir()
    refused(SandboxSpec(scratch=inside), layout)


def test_a_missing_bind_source_is_typed(layout):  # Review Focus 3
    refused(SandboxSpec(scratch=layout["scratch"], ro_binds=(layout["tmp"] / "nope",)), layout, code="bind-missing")


def test_a_dangling_symlink_is_typed(layout):  # Review Focus 3
    dangling = layout["tmp"] / "dangling"
    dangling.symlink_to(layout["tmp"] / "gone")
    refused(SandboxSpec(scratch=layout["scratch"], ro_binds=(dangling,)), layout, code="bind-missing")


def test_a_denied_path_that_does_not_exist_is_ignored(layout):  # Review Focus 4
    check_binds(SandboxSpec(scratch=layout["scratch"]), (*denied(layout), layout["tmp"] / "no-store-root"))


def test_socket_and_token_sources_are_checked(layout):
    token = layout["ops"] / "token"
    token.write_text("t")
    refused(SandboxSpec(scratch=layout["scratch"], token=token), layout)


def test_bind_sources_lists_every_source(layout):
    sock_dir = layout["tmp"] / "run"
    sock_dir.mkdir()
    spec = SandboxSpec(scratch=layout["scratch"], ro_binds=(layout["tools"],),
                       socket=sock_dir / "endpoint.sock", token=sock_dir / "token")
    assert spec.bind_sources() == (Path("/usr"), Path("/etc"), layout["tools"], layout["scratch"],
                                   sock_dir / "endpoint.sock", sock_dir / "token")
```

`test_socket_and_token_sources_are_checked` uses a token file inside a denied root.
The spec requires the token to live outside the denied set, and this test shows that
the check enforces it.

- [ ] **Step 2: Run the tests to see them fail**

Run: `just test-one tests/test_sandbox_static.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.sandbox'`.

- [ ] **Step 3: Implement the spec and the static check**

`python/src/autonomy/sandbox/__init__.py`:

```python
"""The actor sandbox (envelope design §7, decision 8): default-deny, proven twice."""
```

`python/src/autonomy/sandbox/spec.py`:

```python
"""The sandbox spec is data (envelope design §7): what is bound, where, and how."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Literal

SYSTEM_RO: tuple[Path, ...] = (Path("/usr"), Path("/etc"))
# The merged-/usr symlinks, created inside the sandbox rather than bound.
SYSTEM_SYMLINKS: tuple[tuple[str, str], ...] = (
    ("usr/bin", "/bin"),
    ("usr/lib", "/lib"),
    ("usr/lib", "/lib64"),
    ("usr/bin", "/sbin"),
)
IN_SANDBOX_SOCKET = PurePosixPath("/run/va/endpoint.sock")
IN_SANDBOX_TOKEN = PurePosixPath("/run/va/token")


@dataclass(frozen=True)
class SandboxSpec:
    scratch: Path
    ro_binds: tuple[Path, ...] = ()
    socket: Path | None = None
    token: Path | None = None
    network: Literal["none", "host"] = "none"
    env: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def bind_sources(self) -> tuple[Path, ...]:
        """Every host path the sandbox binds, in argv order: each one is checked."""
        sources: list[Path] = [*SYSTEM_RO, *self.ro_binds, self.scratch]
        if self.socket is not None:
            sources.append(self.socket)
        if self.token is not None:
            sources.append(self.token)
        return tuple(sources)
```

`python/src/autonomy/sandbox/static.py`:

```python
"""The static bind check (envelope design §7, decision 8): no bind source may be,
contain, or lie inside a denied path, by real path or by (st_dev, st_ino) ancestry,
so a symlinked or bind-mounted alias of a corpus is caught before anything runs."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from autonomy.sandbox.spec import SandboxSpec


class SandboxUnproven(Exception):
    """The sandbox could not be proven: the run is `unwired` and the actor never starts."""

    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(f"{code}: {path}: {message}")
        self.code = code
        self.path = path


def _identity(path: Path) -> tuple[int, int]:
    info = os.stat(path)
    return (info.st_dev, info.st_ino)


def _ancestry(path: Path) -> set[tuple[int, int]]:
    """The (st_dev, st_ino) of a resolved path and of each of its ancestors."""
    return {_identity(p) for p in (path, *path.parents)}


def check_binds(spec: SandboxSpec, denied: Iterable[Path]) -> None:
    targets: list[tuple[Path, tuple[int, int], set[tuple[int, int]]]] = []
    for path in denied:
        real = path.resolve()
        if real.exists():
            targets.append((real, _identity(real), _ancestry(real)))
    for source in spec.bind_sources():
        try:
            real = source.resolve(strict=True)
        except (FileNotFoundError, RuntimeError) as caught:
            raise SandboxUnproven("bind-missing", str(source), f"a bind source must exist: {caught}") from caught
        identity, ancestry = _identity(real), _ancestry(real)
        for target, target_identity, target_ancestry in targets:
            overlaps = (
                real == target
                or real.is_relative_to(target)
                or target.is_relative_to(real)
                or target_identity in ancestry
                or identity in target_ancestry
            )
            if overlaps:
                raise SandboxUnproven(
                    "bind-overlaps-denied", str(source), f"is, contains, or lies inside the denied path {target}"
                )
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `just test-one tests/test_sandbox_static.py`
Expected: PASS.

- [ ] **Step 5: Run the fast loop, then commit**

Run: `just test-fast` (PASS).

```bash
git add python/src/autonomy/sandbox/__init__.py python/src/autonomy/sandbox/spec.py python/src/autonomy/sandbox/static.py python/tests/test_sandbox_static.py
git commit -m "feat(sandbox): sandbox spec and static bind check by path and inode ancestry"
```

---

### Task 6: `bwrap` argv, preflight, and the denial probe (E5)

**Files:**
- Create: `python/src/autonomy/sandbox/bwrap.py`, `python/tests/test_sandbox_probe.py`

**Interfaces:**
- Consumes: `SandboxSpec`, `SYSTEM_RO`, `SYSTEM_SYMLINKS`, `IN_SANDBOX_SOCKET` and
  `IN_SANDBOX_TOKEN` (Task 5); `SandboxUnproven` and `check_binds` (Task 5).
- Produces:
  - `preflight(which=shutil.which) -> None`, which raises `SandboxUnproven` with code
    `bwrap-missing` or `userns-unavailable`.
  - `build_argv(spec, argv, *, info_fd: int | None) -> list[str]`.
  - `probe(spec, denied) -> None`, which raises `SandboxUnproven` with code
    `probe-reachable` or `probe-failed`.
  - `prove(spec, denied, *, which=shutil.which) -> None`: preflight, then the static
    check, then the probe.

- [ ] **Step 1: Write the failing tests**

`python/tests/test_sandbox_probe.py`:

```python
import subprocess

import pytest

from autonomy.sandbox.bwrap import build_argv, preflight, probe, prove
from autonomy.sandbox.spec import SandboxSpec
from autonomy.sandbox.static import SandboxUnproven


@pytest.fixture
def layout(tmp_path):
    corpus = tmp_path / "corpus root"  # a space, so the probe's parsing is exercised
    ops = tmp_path / "ops"
    scratch = tmp_path / "scratch"
    for d in (corpus, ops, scratch):
        d.mkdir()
    return {"corpus": corpus, "ops": ops, "scratch": scratch, "tmp": tmp_path}


def test_argv_shape(layout):
    spec = SandboxSpec(scratch=layout["scratch"], network="host", env={"A": "1"})
    argv = build_argv(spec, ["/usr/bin/true"], info_fd=7)
    assert argv[:3] == ["bwrap", "--unshare-all", "--share-net"]
    for flag in ("--die-with-parent", "--new-session", "--clearenv"):
        assert flag in argv
    assert argv[argv.index("--info-fd") + 1] == "7"
    assert argv[-2:] == ["--", "/usr/bin/true"]
    scratch = str(layout["scratch"])
    assert ["--bind", scratch, scratch] == argv[argv.index("--bind"):argv.index("--bind") + 3]
    assert argv[argv.index("--chdir") + 1] == scratch


def test_no_network_unless_asked(layout):
    assert "--share-net" not in build_argv(SandboxSpec(scratch=layout["scratch"]), ["/usr/bin/true"], info_fd=None)


def test_a_missing_bwrap_is_typed_before_anything_runs(layout):
    with pytest.raises(SandboxUnproven) as caught:
        prove(SandboxSpec(scratch=layout["scratch"]), (layout["corpus"],), which=lambda _: None)
    assert caught.value.code == "bwrap-missing"


@pytest.mark.bwrap
def test_preflight_passes_on_this_host():
    preflight()


@pytest.mark.bwrap
def test_the_probe_passes_when_nothing_denied_is_bound(layout):
    prove(SandboxSpec(scratch=layout["scratch"]), (layout["corpus"], layout["ops"]))


@pytest.mark.bwrap
def test_a_planted_bind_fails_the_probe(layout):
    # bypass the static check to prove the probe is a second, independent proof
    spec = SandboxSpec(scratch=layout["scratch"], ro_binds=(layout["corpus"],))
    with pytest.raises(SandboxUnproven) as caught:
        probe(spec, (layout["corpus"], layout["ops"]))
    assert caught.value.code == "probe-reachable"
    assert caught.value.path == str(layout["corpus"])


@pytest.mark.bwrap
def test_prove_stops_a_planted_bind_at_the_static_check(layout):
    spec = SandboxSpec(scratch=layout["scratch"], ro_binds=(layout["corpus"],))
    with pytest.raises(SandboxUnproven) as caught:
        prove(spec, (layout["corpus"],))
    assert caught.value.code == "bind-overlaps-denied"


@pytest.mark.bwrap
def test_a_denied_path_that_does_not_exist_passes_the_probe(layout):  # Review Focus 4
    prove(SandboxSpec(scratch=layout["scratch"]), (layout["tmp"] / "no-store-root",))


@pytest.mark.bwrap
def test_the_actor_sees_its_scratch_at_its_host_path(layout):
    (layout["scratch"] / "hello").write_text("hi")
    argv = build_argv(SandboxSpec(scratch=layout["scratch"]), ["/usr/bin/cat", "hello"], info_fd=None)
    out = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=True)
    assert out.stdout == "hi"
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `just test-one tests/test_sandbox_probe.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.sandbox.bwrap'`.

- [ ] **Step 3: Implement `bwrap.py` (argv, preflight, probe, prove)**

`python/src/autonomy/sandbox/bwrap.py`:

```python
"""The bwrap driver (envelope design §7, §8): argv, preflight, the denial probe,
and (Task 7) launch and kill."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

from autonomy.sandbox.spec import IN_SANDBOX_SOCKET, IN_SANDBOX_TOKEN, SYSTEM_RO, SYSTEM_SYMLINKS, SandboxSpec
from autonomy.sandbox.static import SandboxUnproven, check_binds

_PROBE = """\
import errno, os, sys
for path in sys.argv[1:]:
    try:
        os.stat(path)
        print("REACHABLE", path)
    except OSError as caught:
        print(errno.errorcode.get(caught.errno, str(caught.errno)), path)
"""


def preflight(which: Callable[[str], str | None] = shutil.which) -> None:
    if which("bwrap") is None:
        raise SandboxUnproven("bwrap-missing", "bwrap", "bubblewrap is not on PATH")
    trial = [
        "bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr",
        *[arg for target, link in SYSTEM_SYMLINKS for arg in ("--symlink", target, link)],
        "--", "/usr/bin/true",
    ]
    result = subprocess.run(trial, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise SandboxUnproven("userns-unavailable", "bwrap", result.stderr.strip() or f"exit {result.returncode}")


def build_argv(spec: SandboxSpec, argv: Iterable[str], *, info_fd: int | None) -> list[str]:
    args = ["bwrap", "--unshare-all"]
    if spec.network == "host":
        args.append("--share-net")
    args += ["--die-with-parent", "--new-session", "--clearenv", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for path in SYSTEM_RO:
        args += ["--ro-bind", str(path), str(path)]
    for target, link in SYSTEM_SYMLINKS:
        args += ["--symlink", target, link]
    for path in spec.ro_binds:
        args += ["--ro-bind", str(path), str(path)]
    args += ["--bind", str(spec.scratch), str(spec.scratch)]
    if spec.socket is not None or spec.token is not None:
        args += ["--dir", "/run/va"]
    if spec.socket is not None:
        args += ["--bind", str(spec.socket), str(IN_SANDBOX_SOCKET)]
    if spec.token is not None:
        args += ["--ro-bind", str(spec.token), str(IN_SANDBOX_TOKEN)]
    env = {"PATH": "/usr/bin", **spec.env}
    for key, value in sorted(env.items()):
        args += ["--setenv", key, value]
    args += ["--chdir", str(spec.scratch)]
    if info_fd is not None:
        args += ["--info-fd", str(info_fd)]
    return [*args, "--", *argv]


def probe(spec: SandboxSpec, denied: Iterable[Path]) -> None:
    paths = [str(p.resolve()) for p in denied]
    argv = build_argv(spec, ["/usr/bin/python3", "-I", "-c", _PROBE, *paths], info_fd=None)
    result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise SandboxUnproven("probe-failed", "bwrap", result.stderr.strip() or f"exit {result.returncode}")
    lines = result.stdout.splitlines()
    if len(lines) != len(paths):
        raise SandboxUnproven("probe-failed", "bwrap", f"expected {len(paths)} lines, got {len(lines)}")
    for path, line in zip(paths, lines, strict=True):
        status, _, reported = line.partition(" ")
        if reported != path or status != "ENOENT":
            raise SandboxUnproven("probe-reachable", path, f"stat inside the sandbox gave {status}, not ENOENT")


def prove(spec: SandboxSpec, denied: Iterable[Path], *, which: Callable[[str], str | None] = shutil.which) -> None:
    denied = tuple(denied)
    preflight(which)
    check_binds(spec, denied)
    probe(spec, denied)
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `just test-one tests/test_sandbox_probe.py`
Expected: PASS.

If `test_the_probe_passes_when_nothing_denied_is_bound` reports a status other than
`ENOENT`, read the probe's stdout before changing anything. An `EACCES` means the
denied path is visible inside the sandbox, which is a real finding, not a test bug.

- [ ] **Step 5: Run the fast loop, then commit**

Run: `just test-fast` (PASS).

```bash
git add python/src/autonomy/sandbox/bwrap.py python/tests/test_sandbox_probe.py
git commit -m "feat(sandbox): bwrap argv, preflight, and the ENOENT denial probe"
```

---

### Task 7: Launch and kill: the actor's namespace dies on stop and with its parent (E6)

**Files:**
- Modify: `python/src/autonomy/sandbox/bwrap.py` (add `Sandboxed` and `launch`)
- Create: `python/tests/test_sandbox_launch.py`

**Interfaces:**
- Consumes: `build_argv` (Task 6); `SandboxSpec` and `SandboxUnproven` (Task 5).
- Produces:
  - `launch(spec, argv) -> Sandboxed`, which raises `RuntimeError` off the main thread
    and `SandboxUnproven("launch-failed")` when bwrap reports no child.
  - `Sandboxed(process: subprocess.Popen, child_pid: int, pidfd: int)`, with
    `.terminate(grace: float = 10.0) -> int`, `.wait(timeout: float | None = None) -> int`
    and `.close() -> None`.

- [ ] **Step 1: Write the failing tests**

`python/tests/test_sandbox_launch.py`:

```python
import os
import secrets
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from autonomy.sandbox.bwrap import launch
from autonomy.sandbox.spec import SandboxSpec
from autonomy.sandbox.static import SandboxUnproven

pytestmark = pytest.mark.bwrap


def marker() -> str:
    # a sleep duration no other process on the host is using
    return f"{4000 + secrets.randbelow(1000)}.{secrets.randbelow(10**6)}"


def alive(mark: str) -> list[int]:
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if mark.encode() in cmdline and b"sleep" in cmdline:
            found.append(int(entry.name))
    return found


def gone_within(mark: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(mark):
            return True
        time.sleep(0.1)
    return not alive(mark)


def actor(mark: str) -> list[str]:
    return ["/usr/bin/sh", "-c", f"/usr/bin/sleep {mark} & /usr/bin/sleep {mark}"]


def test_terminate_kills_every_process_in_the_namespace(tmp_path):
    mark = marker()
    sandboxed = launch(SandboxSpec(scratch=tmp_path), actor(mark))
    try:
        deadline = time.monotonic() + 5
        while len(alive(mark)) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        # two sleepers, plus the shell unless it exec'd its last command
        assert len(alive(mark)) >= 2
        sandboxed.terminate(grace=1.0)
        assert gone_within(mark, 5)
    finally:
        sandboxed.close()


def test_the_actor_dies_with_its_orchestrator(tmp_path):
    mark = marker()
    orchestrator = textwrap.dedent(f"""
        import sys, time
        from pathlib import Path
        from autonomy.sandbox.bwrap import launch
        from autonomy.sandbox.spec import SandboxSpec
        launch(SandboxSpec(scratch=Path({str(tmp_path)!r})), {actor(mark)!r})
        print("ready", flush=True)
        time.sleep(300)
    """)
    parent = subprocess.Popen([sys.executable, "-c", orchestrator], stdout=subprocess.PIPE, text=True)
    try:
        assert parent.stdout.readline().strip() == "ready"
        deadline = time.monotonic() + 5
        while not alive(mark) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert alive(mark)
        parent.send_signal(signal.SIGKILL)
        parent.wait()
        assert gone_within(mark, 5)
    finally:
        if parent.poll() is None:
            parent.kill()


def test_launch_refuses_any_thread_but_the_main_one(tmp_path):
    # PR_SET_PDEATHSIG fires when the spawning thread exits; a short-lived thread would
    # kill the actor early, so the rule is enforced rather than documented
    caught: list[BaseException] = []

    def body():
        try:
            launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"])
        except BaseException as error:
            caught.append(error)

    thread = threading.Thread(target=body)
    thread.start()
    thread.join()
    assert len(caught) == 1 and isinstance(caught[0], RuntimeError)


def test_a_binary_missing_from_the_sandbox_fails_promptly(tmp_path):  # Review Focus 5
    started = time.monotonic()
    try:
        sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/opt/not-in-sandbox"])
    except SandboxUnproven as error:
        assert error.code == "launch-failed"
    else:
        try:
            assert sandboxed.wait(timeout=10) != 0
        finally:
            sandboxed.close()
    assert time.monotonic() - started < 10
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `just test-one tests/test_sandbox_launch.py`
Expected: FAIL with `ImportError: cannot import name 'launch'`.

- [ ] **Step 3: Implement `launch` and `Sandboxed`**

Add these imports at the top of `python/src/autonomy/sandbox/bwrap.py`:

```python
import json
import os
import signal
import threading
from dataclasses import dataclass
```

Append to `python/src/autonomy/sandbox/bwrap.py`:

```python
@dataclass
class Sandboxed:
    """A running sandbox: the outer bwrap process and a pidfd on the namespace's
    init, opened as soon as bwrap reports it, so a reused pid is never signalled."""

    process: subprocess.Popen
    child_pid: int
    pidfd: int

    def _signal(self, sig: int) -> None:
        try:
            signal.pidfd_send_signal(self.pidfd, sig)
        except ProcessLookupError:
            pass

    def terminate(self, grace: float = 10.0) -> int:
        """SIGTERM, then SIGKILL after `grace`. bwrap's PID 1 need not forward
        SIGTERM, so SIGKILL is the path relied on: killing the namespace's init
        kills every process in it (spec §8)."""
        self._signal(signal.SIGTERM)
        try:
            return self.process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self._signal(signal.SIGKILL)
            return self.process.wait()

    def wait(self, timeout: float | None = None) -> int:
        return self.process.wait(timeout=timeout)

    def close(self) -> None:
        if self.process.poll() is None:
            self._signal(signal.SIGKILL)
            self.process.wait()
        try:
            os.close(self.pidfd)
        except OSError:
            pass


def _read_info(fd: int, process: subprocess.Popen) -> dict[str, object] | None:
    """Read bwrap's --info-fd JSON object; None when bwrap exits without one."""
    decoder = json.JSONDecoder()
    buffer = ""
    while True:
        chunk = os.read(fd, 4096)
        if not chunk:
            return None
        buffer += chunk.decode("utf-8")
        try:
            value, _ = decoder.raw_decode(buffer.lstrip())
        except ValueError:
            continue
        return value if isinstance(value, dict) else None


def launch(spec: SandboxSpec, argv: Iterable[str]) -> Sandboxed:
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError(
            "launch the sandbox from the main thread: --die-with-parent is PR_SET_PDEATHSIG, "
            "which fires when the spawning thread exits"
        )
    read_fd, write_fd = os.pipe()
    try:
        process = subprocess.Popen(
            build_argv(spec, argv, info_fd=write_fd),
            pass_fds=(write_fd,),
            stdin=subprocess.DEVNULL,
        )
    finally:
        os.close(write_fd)
    try:
        info = _read_info(read_fd, process)
    finally:
        os.close(read_fd)
    child = None if info is None else info.get("child-pid")
    if type(child) is not int:
        process.wait()
        raise SandboxUnproven("launch-failed", "bwrap", f"bwrap reported no child (exit {process.returncode})")
    return Sandboxed(process, child, os.pidfd_open(child))
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `just test-one tests/test_sandbox_launch.py`
Expected: PASS.

If `test_the_actor_dies_with_its_orchestrator` leaves the sleepers alive, check that the
helper process's `launch` ran on its main thread, and that the argv contains
`--die-with-parent`, before you change anything else. Do not widen the 5 s bound.

- [ ] **Step 5: Run the fast loop and the gate, then commit**

Run: `just test-fast` (PASS), then `just check` (silent, exit 0).

```bash
git add python/src/autonomy/sandbox/bwrap.py python/tests/test_sandbox_launch.py
git commit -m "feat(sandbox): launch from the main thread and kill the actor's namespace"
```

---

## After the last task

Run `just test` once: the full suite, including every `bwrap` test. Then hand the
branch to the final whole-branch review that the chosen execution skill prescribes.
