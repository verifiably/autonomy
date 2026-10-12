# Envelope — design (sub-project 6)

**Date:** 2026-10-12
**Status:** draft for review.
**Task:** autonomy-250f4d. Its goal is ops-3f5aa6, a science harness on pi. The
bounded unattended run (autonomy-9e8a43) cannot start before this exists.

**Scope:** the conditions under which any actor may run unattended. That covers how
a run opens and how it closes:

- the run-unique actor and the exclusive writer session;
- the baseline, kept outside the actor's reach;
- tiers as permits that the kernel writer enforces;
- the actor sandbox and its private endpoint handle;
- the lease and the kill switch;
- the closing check, which compares the chain interval against the session ledger
  entry by entry and ends in `clean`, `quarantined` or `unwired`.

The envelope constrains any actor identically: a pi agent, a Claude Code session or a
person's script. It names no harness.

**Inherits:** the governing design is the
[user and autonomy layer design](https://github.com/verifiably/beliefs/blob/main/docs/superpowers/specs/2026-08-29-user-and-autonomy-layer-design.md).
This document draws on these parts of it:

- §5.2: the writer endpoint binds the permit, sets the actor and keeps the ledger;
  the sandbox denial is the boundary; an unattended run on the arrangement alone
  never runs.
- §7.1: the envelope, interval membership and tiers.
- §7.4: the seam, kill switch and liveness.
- §9: an `unwired` disposition wherever a guard cannot see.

It also builds on what sub-project 2 delivered:

- the [command-framework design](https://github.com/verifiably/science/blob/main/docs/specs/2026-08-31-command-framework-design.md)
  in `science`;
- the [write-permits design](https://github.com/verifiably/beliefs/blob/main/docs/designs/2026-09-04-write-permits-design.md)
  in `beliefs`;
- the [writer-session design](https://github.com/verifiably/beliefs/blob/main/docs/designs/2026-09-05-writer-session-design.md)
  in `beliefs`.

Those documents name four pieces as this sub-project's: the run-session constructor
with its tier, the actor sandbox, the private endpoint handle, and quarantine on the
closing check.

**Out of scope:**

- **The loop, behavioural profiles and `science.priority.v1`:** sub-project 7.
- **Budget accounting and enforcement, outcome shapes, credential custody and the
  evidence report:** autonomy-9e8a43, which consumes this envelope.
- **The authorization model in general:** autonomy-1aac03. §11 maps the tier onto it.
- **Concurrent runs on one corpus:** the governing design §7.1 names the remedy and
  does not take it.
- **Multi-corpus write targeting:** the writer-session design §8.
- **Publishing:** never unattended.

## 1. What exists, and what is missing

This section is read from the code on 2026-10-12. Paths are relative to each
repository.

**Delivered, and this design uses it as built:**

- **The writer session.** `beliefs.session.open_attended_session(world_config,
  operations_root, *, write_root, profile, mounts=…, …)` opens a `WriterSession`.
  - **Actor:** a fresh `session_id = secrets.token_hex(16)` and the actor
    `session:<session_id>`, which is derived and never supplied.
  - **Writes:** exactly one `write_root`. Other roots are read mounts.
  - **Ceiling:** the session's ceiling permit is a constructor keyword on
    `WriterSession` that defaults to `WritePermit.full()`. No public constructor
    exposes it.
- **The permit.** `WritePermit(kinds, act_families, ungoverned)` is checked at every
  kernel write entry point. `RequiredCapabilities` covers `none`, `coordination`,
  `for_kinds` and `publishes`. An act outside the permit is `PermitExceeded`, before
  any effect. science maps write classes onto requirements in `dispatch.py`.
- **The session ledger.** It lives at `<operations root>/sessions/<id>/ledger.v1`. It
  is appended, flushed and fsynced per line, and any failure ends the session. Its
  line kinds:
  - `session-open`: records the session, the actor, the world and the permit.
  - `invocation-open`
  - `act`: records the invocation, the corpus id, the chain entry digest, the intent
    digest and the records. It is written under the root's operation lock.
  - `invocation-close`
  - `session-close`
  - `select`
- **Reconciliation.** `beliefs.session.reconcile` classifies ledgers against chains.
  Its finding codes include `session-entry-foreign`, `session-intent-unclaimed`,
  `session-act-unverified` and `session-unclosed`.
- **The endpoint.** `science serve` holds one session behind a Unix socket, one JSON
  request per line. `science`'s CLI is a client of that socket.
- **Chain reads.** `beliefs.root.log_seam()` reads a chain's head and its linearized
  entries, genesis first. The world root has its own chain.

**Missing, and named here because §7.1 assumes it:**

1. **No public run-session constructor.** The ceiling cannot be narrowed from outside
   `beliefs`.
2. **No cross-process exclusivity.** `OperationLock` is in-process. A single writer
   across processes is a stated deployment obligation (adoption ledger row 4).
   `science serve` refuses a second launcher only on the same socket path, not on the
   same corpus.
3. **No endpoint authentication.** Any process that can reach the socket can
   dispatch.
4. **No lease, fencing or seal.** A session lives as long as its process.
5. **No read of the entries between two tips.** A caller slices the full linearized
   view.
6. **No "belief basis" concept in the kernel.** The phrase appears only in the
   governing design §7.1. Decision 6 defines it.
7. **No client-only MCP bridge.** `science mcp serve` opens its own session
   in-process, so an MCP-speaking actor has no way to reach an endpoint it does not
   own.

## 2. Decisions

These are recorded as rulings so they are not re-derived. Items 6, 9 and 10 were taken
while drafting, and the review may overturn them.

1. **autonomy is a foreground supervisor, and it imports no kernel.**
   `autonomy run <options> -- <actor argv>` does the whole run in one process:

   - opens the run (§3);
   - launches the endpoint and the sandboxed actor as children;
   - holds the lease;
   - runs the closing check;
   - writes the disposition;
   - exits with a code that names the disposition.

   It reaches `beliefs` only through `science` commands, run as subprocesses, plus the
   published `ledger.v1` format, which it reads as a file. An orchestrator (the loop,
   or a person's script) composes runs. It never reaches inside one.
2. **The run's actor is its session's actor.** A run opens exactly one writer session,
   and that session's `session:<id>` is the run's actor identity. It is fresh for
   each session by construction (`secrets.token_hex(16)`), so an interactive write by
   the same person carries a different actor. No kernel change is needed for
   identity. The run id is autonomy's own (a fresh 128-bit hex, allocated before the
   session exists); `events.jsonl` maps it to the session id.
3. **A run writes exactly one corpus.** This matches the session as built. The
   baseline records the heads of every mounted corpus all the same. A read-mounted
   corpus that moves during the run is reported, never a membership finding, because
   the run cannot write it.
4. **Exclusivity is a kernel lock, not an endpoint convention.** `beliefs` gains a
   cross-process claim for each corpus:

   - every session constructor, attended and run alike, takes it before the
     `session-open` line;
   - the session holds it for its life;
   - the kernel releases it on process death.

   A second session on the same corpus is refused at open, whichever launcher asks.
   Plain library use (`CorpusWriter` outside a session) still bypasses it. That stays
   row 4's obligation, and the closing check's ledger comparison turns any violation
   into `quarantined` (§9).
5. **The lease is enforced at the endpoint.** The endpoint is the only process that
   can write, so the fence lives there:

   - it holds a monotonic deadline that the orchestrator renews over a control socket
     only the orchestrator holds;
   - at expiry, or on a stop, it seals the session: every later request is refused
     `run-sealed`, and the session closes;
   - an act already past its permit check runs to completion or is settled by kernel
     recovery, and no act starts after the seal.

   The actor's process tree is killed separately (§8), so non-governed work (shell,
   network, local files) stops with it.
6. **The belief basis is the derivation context, not the beliefs.** Beliefs are
   evaluated on read: science's `belief` command evaluates "the shipped belief
   policy". So every belief is a function of the chains, which the heads capture, and
   of everything else a belief evaluation reads. That second part is the basis:

   - the identity of the belief policy in effect;
   - the domain packs and corpus contracts bound;
   - the `beliefs` distribution version.

   The basis is captured as one digest over those identities, through a `science`
   read command (§10). Heads plus basis then determine every belief. A basis that
   changes during the run means the world now evaluates differently from the way the
   run's acts were judged, and it is `quarantined` (`basis-moved`).

   Rejected alternative: a digest of every evaluated belief. It costs one evaluation
   for each proposition at open and at close, and anything it would catch is a head
   or basis move already.
7. **Tiers are data in `autonomy`, and the kernel checks them.** A tier is a constant
   in `autonomy`: a closed permit in `WritePermit`'s serialized form (§5). The
   orchestrator hands it to the endpoint at launch. The endpoint passes it to the
   kernel's run-session constructor as the ceiling, and `session-open` records it.
   The closing check verifies that the recorded permit equals the tier's. Nothing
   downstream (a profile, a command, a body or the actor) can widen it, because
   requests carry no permit, and the ceiling is fixed before the session exists.
8. **The sandbox is default-deny, and it is probed before the actor runs.** The actor
   runs under `bwrap` in fresh namespaces:

   - **Denied:** every corpus root, the world root, the operations root and the run
     directory are never bound.
   - **Bound:** the system read-only, a run-scoped scratch directory, and the
     endpoint socket.
   - **Handed over:** the session token, in the actor's environment only.

   Before the actor starts, a probe inside the identical sandbox must fail to reach
   each denied root. A probe that succeeds, a missing `bwrap`, or unprivileged user
   namespaces being unavailable all make the run `unwired` at open, and the actor
   never starts. That is §5.2's "never runs on the arrangement alone".
9. **Dispositions have a precedence.** `quarantined` beats `unwired`, which beats
   `clean`, and every finding is listed whatever the disposition. `quarantined` says
   that something wrong was seen and the effects are held. `unwired` says that the
   guard could not vouch. When both hold, holding the effects is the stronger and
   more useful instruction.
10. **The closing comparison is autonomy's own code.** It does not call beliefs'
    `reconcile`. The governing design splits `autonomy` from `science` on code-lineage
    independence, and a check that delegates its verdict to the kernel it guards
    shares the kernel's blind spots. So autonomy compares raw evidence itself: the
    chain interval from a `science` read and the ledger file. The two are
    deliberately redundant.

## 3. A run, end to end

**Open.** Steps run in order. A failure at any step before 8 closes the run with the
named disposition, and the actor never starts.

1. **Allocate the run directory.** It is `<autonomy state>/runs/<run-id>/`, outside
   every corpus root, the world root and the operations root. `<autonomy state>`
   defaults to `$XDG_STATE_HOME/verifiably-autonomy`.
2. **Refuse on configuration.** Refuse (exit 2, no run) when:
   - the tier is `publishes` (never unattended);
   - the write corpus is not among the world's corpus roots;
   - the lease is shorter than the floor (§8).
3. **Capture the baseline** through `science` reads (§10):
   - the world head;
   - every mounted corpus's head (genesis digest and tip digest);
   - the belief basis.

   Write `baseline.json` (§6), fsync it, then fsync its directory. An unavailable read
   means `unwired` (`baseline-unavailable`).
4. **Launch the endpoint.** Run `science serve --run <launch.json>` as a child, with
   the tier's permit, the write corpus, a fresh 256-bit token and the control socket
   path in its launch file. The endpoint opens a run session through the kernel's run
   constructor, taking the corpus claim (decision 4). It reports
   `{session_id, ledger_path, socket}` on its control socket. Any of these means
   `unwired` (`endpoint-unavailable`):
   - a refusal, including `corpus-claimed` because another session holds the corpus;
   - no report within the start timeout.
5. **Verify the session.** Read `session-open` from the ledger. Its permit must equal
   the tier's permit, and its actor must be `session:<session_id>`. A mismatch means
   `unwired` (`permit-mismatch` or `actor-mismatch`), and the endpoint is stopped.
6. **Re-read the write corpus's head.** It must equal the baseline's. If it moved
   between steps 3 and 5, a write landed outside the run's session after capture and
   before the claim, so the run is `unwired` (`baseline-raced`).
7. **Probe the sandbox** (decision 8). A failed probe means `unwired`
   (`sandbox-unproven`).
8. **Start the actor.** Run the actor argv under the sandbox, with
   `VERIFIABLY_ENDPOINT` (the socket path inside the sandbox) and `VERIFIABLY_TOKEN`
   in its environment. Start the heartbeat.

**During.** The actor reaches the world only through the handle. Each request names a
command and its inputs, plus the token. The endpoint refuses `bad-token` before
dispatch, then dispatches under the run session as it does today. The orchestrator
renews the lease every lease/3.

**Close.** Any one of these triggers the close:

- the actor exits;
- `autonomy run stop <run-id>`;
- the wall-clock bound.

Then:

1. **Seal and stop the endpoint.** Seal it over the control socket. The endpoint
   finishes or settles an in-flight act, writes `session-close` and exits.
2. **Kill the actor's process tree** if it is still alive (§8).
3. **Run the closing check** (§9).
4. **Write `disposition.json`** (§9), fsync it, and exit with the disposition code:
   0 `clean`, 3 `quarantined`, 4 `unwired`.

**Orphaned runs.** A run directory with a baseline and no disposition belongs to an
orchestrator that died. `autonomy run close <run-id>` runs the closing check over it.
Its disposition is at least `unwired` (`orchestrator-lost`), because the supervision
the run depended on was absent for an unknown interval. A `quarantined` finding still
takes precedence (decision 9). The kernel's corpus claim dies with the endpoint, so
it does not guard the orphan. autonomy does: a new run on the corpus scans the run
directories, finds the orphan and refuses (`orphaned-run`) until it is closed. That way
an unclassified interval is never absorbed into the next run's baseline. A
non-autonomy session that writes the corpus in the meantime shows up at the orphan's
close as `entry-foreign`.

## 4. Components

**`autonomy`** is the new Python package `verifiably-autonomy`. It is laid out under
`python/src/autonomy/`, the way the sibling repositories are, with one module per
concern:

| module | does | depends on |
|---|---|---|
| `tiers` | the four tier constants and their permits; refusing `publishes` | nothing |
| `baseline` | capturing heads and the basis through `science`, and writing and reading `baseline.json` | `science_reads` |
| `science_reads` | the only place that invokes `science`: subprocess calls to read commands, with output parsed into typed values | the `science` CLI |
| `sandbox` | building the `bwrap` argv from a sandbox spec, and the denial probe | `bwrap` |
| `endpoint` | launching `science serve --run`, the control-socket client, heartbeat, seal | the `science` CLI |
| `ledger` | a reader for `ledger.v1`: only the lines the check needs, strict on format | nothing |
| `closing` | the comparison of §9: pure, over typed inputs, no I/O | `ledger`, `baseline` |
| `run` | the supervisor of §3, wiring the above together | all |
| `cli` | `autonomy run`, `run stop`, `run close`, `run show` | `run` |

`closing` is pure, so every disposition row is a unit test over constructed
evidence. `sandbox` and `endpoint` have integration tests against real `bwrap` and a
real `science serve`.

**`science`**, filed from the plan, needs:

- `serve --run <launch file>`: a run session with the given permit and corpus;
- the token check;
- the control socket (the lease deadline, seal and report);
- a client-only MCP bridge, `science mcp bridge`, that opens no session and forwards
  to a handle;
- three read commands: `heads`, `log` and `basis` (§10).

**`beliefs`**, filed from the plan, needs:

- `open_run_session(…, ceiling: WritePermit)`, with the permit deserialized from the
  launch file;
- the cross-process corpus claim, taken by every session constructor;
- `seal()` on `WriterSession`: refuse every later scoped write, and close;
- the read that `log` needs (entries after a given tip);
- the basis identity that `basis` needs.

Each is a kernel design slice, frozen in a conformance cut as `beliefs` does.

## 5. Tiers as permits

| tier | permit | the actor may |
|---|---|---|
| `report-only` | `READ_ONLY`: no kinds, no families | read; `session`-class commands (selection) |
| `coordination` | `RequiredCapabilities.coordination()`'s kinds and families | mint coordination kinds only |
| `mints:<kinds>` | coordination ∪ `for_kinds(<kinds>, <routes>)` | additionally mint the named kernel kinds through their routes |
| `publishes` | `RequiredCapabilities.publishes()` | refused at open: never unattended |

How the tiers relate:

- **Inclusion:** `report-only` ⊂ `coordination` ⊂ `mints:K` ⊂ `publishes`, for any K.
- **Mints:** `mints:<kinds>` is parameterized because "mints" names no kinds without
  a list. The kind list is part of the tier and is recorded in the baseline. An empty
  list is refused, because it would be `coordination` by another name.
- **Families:** `act_families` never includes `publish`, `registry`, `epoch` or
  `lifecycle` at any unattended tier. Those families are not command-reachable
  anyway, and the tier states the fact rather than relying on it.
- **Ungoverned writes:** `ungoverned` is `false` at every tier.

The serialized permit is `{"kinds": [...sorted], "act_families": [...sorted],
"ungoverned": false}`, the same shape `session-open` records. That makes the check in
step 5 an equality between two canonical JSON values.

## 6. The baseline

`<run dir>/baseline.json`, version 1, is written once and never rewritten:

```json
{
  "version": 1,
  "run": "<run id>",
  "opened_at": "<UTC RFC 3339>",
  "tier": {"name": "mints", "kinds": ["claim", "proposition"]},
  "permit": {"kinds": [], "act_families": [], "ungoverned": false},
  "world": {"root": "...", "id": "...", "head": {"genesis": "<64 hex>", "tip": "<64 hex>"}},
  "write_corpus": "<32 hex corpus id>",
  "corpora": {"<corpus id>": {"root": "...", "genesis": "<64 hex>", "tip": "<64 hex>"}},
  "basis": "<64 hex>",
  "actor_argv": ["..."],
  "sandbox": {"spec": "...", "probe": "passed"},
  "lease": {"seconds": 60}
}
```

Step 3 writes the heads and the basis, before the session exists. Steps 4–7 append
their facts (session id, ledger path, orchestrator and endpoint pids, probe result,
actor start) as separate lines in `<run dir>/events.jsonl`, fsynced line by line, and
never by rewriting the baseline. Everything the actor
could influence lives in the corpora, and everything that judges the actor lives in
the run directory, which the sandbox never binds.

## 7. Sandbox and endpoint handle

The sandbox spec is data: what is bound read-only, what is bound read-write (only the
run's scratch directory), the socket, environment variables, the network mode
(`none` or `host`), and a working directory.

- **The argv** is built as `bwrap --unshare-all [--share-net] --die-with-parent
  --new-session --clearenv …`, followed by the binds the spec names, in order.
- **Network** is a per-run choice in the spec. A model-calling harness needs `host`.
  Narrowing it (an egress proxy) belongs with credentials in autonomy-9e8a43.
- **The probe** runs `/bin/sh -c` inside the same spec, with the denied paths as
  arguments. For each path it attempts `stat` and an open-for-write, and it prints one
  line per path. The orchestrator requires every line to be a denial. The denied set
  is computed from the world configuration (the world root, every corpus root, the
  operations root) plus the run directory and the autonomy state root, never from the
  sandbox spec, so a spec that binds a denied path fails its own probe.

**The handle** is the socket path inside the sandbox plus the token. The token is
born in the orchestrator, written to the endpoint's launch file (mode 0600, in the run
directory), and placed in the actor's environment. It is never logged, never written
into the baseline, and never echoed by any command. An MCP-speaking harness is given
`science mcp bridge` as its MCP server. The bridge reads the handle from the
environment, so the harness configuration needs no secret.

## 8. Lease and kill switch

- **The lease** is `lease.seconds`. The floor is 10 s and the default is 60 s.
  - **Renewal:** the orchestrator sends `renew` every lease/3.
  - **The deadline:** the endpoint holds `deadline = monotonic() + lease.seconds` and
    checks it when it claims an invocation, before any act, under its dispatcher
    lock.
  - **Expiry:** an expired deadline seals the session.
  - **A dead orchestrator** stops renewing, so its endpoint seals within one lease. A
    dead orchestrator also closes the control socket, and the endpoint treats EOF on
    the control socket as an immediate seal. The lease is the bound when the process
    is hung rather than dead.
- **The kill switch** is `autonomy run stop <run-id>`. It signals the orchestrator
  (SIGTERM; the pid is in `events.jsonl`). The orchestrator then:
  1. seals the endpoint;
  2. sends SIGTERM to the actor's process group, and after a 10 s grace, SIGKILL;
  3. closes normally.

  If the orchestrator is already gone, `stop` reports that and directs the operator to
  `run close`. The endpoint has sealed by EOF or will seal by lease. Seal comes before
  kill so that no act starts between deciding to stop and the actor's death.
- **The actor dies with the orchestrator.** `--die-with-parent` ties the actor to the
  orchestrator, and `--unshare-pid` puts every descendant in the actor's PID
  namespace, so the namespace dies with it. A dead orchestrator therefore leaves:
  - no actor;
  - a sealed endpoint;
  - a run directory with no disposition, which is `unwired` by §3's orphan rule.

## 9. The closing check

**Inputs:**

- the baseline;
- the events file;
- the ledger;
- a `science log` read of the write corpus's chain from the baseline tip to its
  current tip;
- a fresh `heads` read and `basis` read.

**Output:** a disposition and a list of findings. Each finding has a code, a ref (an
entry digest, a corpus id or a path) and a one-line message.

**Membership.** The interval is the entries after the baseline tip, up to and
including the closing tip, of the one write corpus. Each entry is classified:

- **A member** is an intent entry or registration entry that a ledger `act` line names
  (as its `intent` or its `entry` digest), with an intent whose actor is the run's
  actor.
- **`entry-foreign`** is any entry the ledger did not append, whatever actor it
  carries. → `quarantined`.
- **`actor-foreign`** is an entry the ledger names whose intent carries another actor.
  This is impossible unless the endpoint is broken, and it is checked anyway.
  → `quarantined`.
- **`entry-settled-recovery`** is a settled entry appended by kernel recovery that
  settles one of the run's own member intents (an act in flight at the seal). It is a
  member, and the finding is informational.
- **`act-unverified`**: every `act` line must appear in the interval, and a ledger
  claim missing from the chain is reported as this. → `unwired`.

**The rows:**

| condition | finding | disposition |
|---|---|---|
| baseline, events, ledger, or a read unavailable or malformed | `baseline-unavailable` / `ledger-unavailable` / `read-unavailable` | `unwired` |
| the write corpus's baseline tip is not an ancestor of its closing tip (chain rewritten) | `chain-discontinuous` | `quarantined` |
| an entry in the interval not appended by the ledger | `entry-foreign` | `quarantined` |
| a ledger `act` whose intent actor is not the run's | `actor-foreign` | `quarantined` |
| a ledger `act` with no entry in the interval | `act-unverified` | `unwired` |
| the world head moved | `world-moved` | `quarantined` |
| the basis moved | `basis-moved` | `quarantined` |
| the ledger has no `session-close` | `session-unclosed` | `unwired` |
| `session-open`'s permit differs from the tier's | `permit-mismatch` | `unwired` |
| the orchestrator was lost (an orphan close) | `orchestrator-lost` | `unwired` |
| a read-mounted corpus moved | `mount-moved` | none (reported) |
| a recovery settlement of a member intent | `entry-settled-recovery` | none (reported) |
| none of the above | — | `clean` |

A world move is `quarantined` rather than reported. Registry, epoch and lifecycle
families are outside every unattended tier, so the run cannot have moved the world.
The run's reads were therefore made against a world that changed under it.

**Precedence.** The disposition is the strongest the rows produce (decision 9).

**`disposition.json`** records:

- `{version, run, disposition, findings[], closed_at}`;
- the member entries;
- the closing heads.

It is written once. A second `run close` on a closed run prints the existing
disposition and changes nothing.

## 10. The seam: commands as tools

`autonomy` uses `science` in two ways:

- **as a CLI**, for the three read commands below;
- **as an endpoint process** that it launches.

It holds no private kernel path.

The three read commands are new, are `read-only` class, and exist for people too:

- **`heads`:** the world head, and the genesis and tip of every mounted corpus.
- **`log --corpus <id> --after <tip>`:** the entries after a tip, in chain order.
  Each entry carries its digest, its entry type, its `fulfills` and intent digest
  where present, and the decoded intent's kind and actor. A tip that is not on the
  chain is refused (`tip-unknown`), which is how `chain-discontinuous` is detected.
  The output budget pages through a cursor as usual.
- **`basis`:** the basis digest and its components (decision 6).

Harness neutrality follows from the shape of the run:

- the actor is an argv;
- the handle is two environment variables;
- the MCP bridge is optional.

pi, Claude Code and a shell script all run identically under `autonomy run`. Anything
harness-specific (a pi configuration naming the bridge, a model credential) is the
caller's, and none of it enters the envelope.

## 11. A tier as an authorization

The companion authorization model (autonomy-1aac03) describes a grant by the parts
below. A tier fills each of them as follows:

| part of a grant | where it lives |
|---|---|
| identity | the run's actor `session:<id>` |
| operation and resource | the permit (kinds, act families) over one write corpus |
| scope | the corpus claim and the sandbox's denied set |
| lifetime | the lease and the wall-clock bound |
| revocation | `run stop`; the seal |
| approval | the person or orchestrator that ran `autonomy run` with that tier; `publishes` is never approvable unattended |
| audit receipt | the baseline, events, ledger and disposition |
| rollback | out of scope here: a `quarantined` run's member entries are listed for a person to act on |

A flow gate grants none of these. A tier comes only from the `autonomy run`
invocation.

## 12. Verification

Each row has a test that can fail and a negative test. Rows E1–E10 belong to
`autonomy`. Rows that need the `science` or `beliefs` pieces run once those land, and
until then they are skipped with the piece named, never passed.

| row | claim | test | negative |
|---|---|---|---|
| E1 | every tier's permit is the table's, and `publishes` is refused at open | unit: each constant against literal permits; `run --tier publishes` exits 2 with no run directory | a tier built from `full()` fails the unit |
| E2 | `closing` gives each row's disposition and the precedence | unit: constructed evidence for every row and for each pair of rows | swapping two precedence ranks fails a pair case |
| E3 | the sandbox denies every computed denied path | integration: real `bwrap`, probe output | a spec that binds the operations root fails the probe, and the run is `unwired` with no actor started |
| E4 | a missing `bwrap` or user-namespace failure means `unwired` before the actor | integration with `PATH` stripped of `bwrap` | the same run with `bwrap` present starts the actor |
| E5 | the session's recorded permit and actor are verified | integration: an endpoint launched with a permit wider than the tier | the endpoint started with the exact permit passes step 5 |
| E6 | a write outside the session lands as `entry-foreign` and `quarantined` | integration: mid-run, the test writes the corpus through a bare `CorpusWriter` in another process (the corpus claim refuses a second session, so row 4's bypass is the route) | the same run with no foreign write is `clean` |
| E7 | the lease seals: after expiry or control EOF, no act lands | integration: stop renewing, issue a write request → `run-sealed`, chain head unchanged | while renewing, the same request lands |
| E8 | kill switch: `run stop` seals before killing, and no act after the stop | integration: an actor that writes in a loop; `stop`; assert the last entry precedes the seal event | without the seal step, a test hook lands one act after `stop` |
| E9 | an orphaned run closes `unwired` with `orchestrator-lost`, and a new run on its corpus is refused until then | integration: SIGKILL the orchestrator; assert actor and endpoint gone; `run` refuses; `run close` → `unwired` | a normally closed run allows the next |
| E10 | world, basis and baseline races are seen | integration for each: move the world head, change a pack binding, write between steps 3 and 5 | an untouched run is `clean` |
| E11 | a second session on a claimed corpus is refused (beliefs) | kernel test: two constructors, two processes | sequential sessions both open |
| E12 | a request without the token is refused before dispatch (science) | endpoint test | the correct token dispatches |

## 13. Delivery

The plan orders the work as follows. The `science` and `beliefs` pieces are filed to
their projects, each with a dependency from this task's plan steps.

1. **`autonomy` package skeleton, `tiers`, `ledger`, `closing`:** pure code, E1 and
   E2. It runs today.
2. **`sandbox` and its probe:** E3 and E4. It runs today.
3. **`beliefs`:** the run constructor with ceiling, the corpus claim, `seal`, the
   entries-after read, and the basis identity, in one kernel slice (E11).
4. **`science`:** `serve --run`, token, control socket, `mcp bridge`, and `heads`,
   `log` and `basis` (E12).
5. **`endpoint`, `baseline`, `run` and the CLI:** E5–E10, after 3 and 4.

The first unattended run (autonomy-9e8a43) starts after step 5.

## 14. Alternatives rejected

- **A container per run (Docker).** It gives the strongest isolation, but it needs a
  root daemon, image management, and a socket bind across the boundary. `bwrap` gives
  the same filesystem denial rootlessly. A container stays a later sandbox backend
  behind the same spec, for when network or credential custody needs it.
- **The lease held by the actor, or in a file the endpoint polls.** An actor-held
  lease lets the constrained party renew its own authority. Wall-clock expiry in a
  file is open to clock changes and a race between check and act. The control
  socket's EOF gives prompt detection of death, and the monotonic deadline bounds a
  hang.
- **The closing check through beliefs' `reconcile`.** Rejected by decision 10. The
  autonomy check and `reconcile` may disagree, and a disagreement is itself a defect
  to report.
- **Exclusivity by the endpoint's socket path only.** It is what exists. Two
  launchers with different configurations name different sockets and open the same
  corpus.
- **The basis as a digest of all evaluated beliefs.** Rejected by decision 6.
- **Runs that write several corpora.** The session writes one root. Widening it is the
  writer-session design's §8 and a kernel slice of its own, with no consumer yet.
- **A permit file the actor could read.** The permit is in the launch file in the run
  directory, which the sandbox never binds. The actor learns its tier only from
  refusals and from `session`-class reads.
