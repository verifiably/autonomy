# Envelope — design (sub-project 6)

**Date:** 2026-10-12
**Status:** draft for review. Revised after review round 1, which found 3 Critical, 9
Important and 8 Minor problems. All of them are addressed in this text.
**Task:** autonomy-250f4d. Its goal is ops-3f5aa6, a science harness on pi. The
bounded unattended run (autonomy-9e8a43) cannot start before this exists.

**Scope:** the conditions under which any actor may run unattended:

- how a run opens and closes;
- the run-unique actor and the exclusive writer session;
- the baseline, kept outside the actor's reach;
- tiers as permits that the kernel writer enforces;
- the actor sandbox and its private endpoint handle;
- the lease, the seal and the kill switch;
- the closing check, which compares the chain intervals against the session ledger
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
- **Budget accounting and enforcement, outcome shapes, credential custody, network
  egress policy and the evidence report:** autonomy-9e8a43, which consumes this
  envelope.
- **The authorization model in general:** autonomy-1aac03. §11 maps the tier onto it.
- **Concurrent runs on one corpus:** the governing design §7.1 names the remedy and
  does not take it.
- **Multi-corpus write targeting:** the writer-session design §8.
- **Exclusivity across hosts:** corpora on a synced store can be opened from another
  host. The corpus claim and the orphan scan are per host (§2 decision 4).
- **Publishing:** never unattended.

## 1. What exists, and what is missing

This section is read from the code on 2026-10-12. Paths are relative to each
repository's `python/src/`.

**Delivered, and used here as built:**

- **The writer session.** `beliefs.session.open_attended_session(world_config,
  operations_root, *, write_root, profile, mounts=…, store_root=…, …)` opens a
  `WriterSession`.
  - **Actor:** a fresh `session_id = secrets.token_hex(16)` and the actor
    `session:<session_id>`, which is derived and never supplied (`session/writer.py`).
  - **What it writes:** exactly one `write_root`. Other roots are read mounts. It
    also writes the holdings **store root** that science passes it
    (`science/session.py`). Holdings acts publish to that root's own chain through
    `ledgered_seam(...).publish_fulfilling`, and each such commit is ledgered
    (`session/routes.py`).
  - **Ceiling:** `WriterSession` is exported, and its `ceiling` keyword defaults to
    `WritePermit.full()`. The only supported constructor, `open_attended_session`,
    takes no ceiling.
- **The permit.**
  - **Shape:** `WritePermit(kinds, act_families, ungoverned)`, checked at every kernel
    write entry point.
  - **Requirements:** `RequiredCapabilities` covers `none`, `coordination`, and
    `for_kinds(kinds, routes)`, where a kind admitting several families needs a
    route. It also covers `publishes`, the closed kernel requirement
    `_PUBLICATION_PERMIT`.
  - **Refusal:** an act outside the permit is `PermitExceeded`, before any effect.
- **The session ledger.** It lives at `<operations root>/sessions/<id>/ledger.v1`. It
  is appended, flushed and fsynced per line, and any failure ends the session.
  - **The `act` line:** `{invocation, corpus, entry, intent, records}`. It is written
    under the session lock, after the commit, and names the intent digest and the
    registration digest.
  - **What it does not name:** the settlement entry that a commit also appends.
    Reconciliation reaches settlements through `SettledEntryView.registration` and
    requires `committed` (`session/reconcile.py`).
- **Reconciliation.** `beliefs.session.reconcile`. Its finding codes include
  `session-entry-foreign`, `session-intent-unclaimed`, `session-outcome-unknown`,
  `session-act-unverified` and `session-unclosed`.
- **The endpoint.**
  - **Shape:** `science serve` holds one session behind a Unix socket, one JSON
    request per line. The dispatcher lock is held for a whole handler.
  - **Clients:** science's CLI is a client of the socket.
  - **MCP:** `science mcp serve` opens its own session in-process.
- **Chain reads.**
  - **The read:** `beliefs.root.log_seam()` reads a chain's head and its linearized
    entries (intent, registered, settled; genesis first).
  - **Recovery on read:** a registered read resolves recovery and can append
    settlements. A detached read appends nothing.
  - **The world:** the world root has its own chain.

**Missing, and named here because §7.1 assumes it:**

1. **No run-session constructor** with a ceiling, a seal, and the run's confinement of
   path inputs.
2. **No cross-process exclusivity.** `OperationLock` is in-process. A single writer
   across processes is a stated deployment obligation (adoption ledger row 4).
3. **No endpoint authentication**, and no check of who the peer is.
4. **No lease or seal.** A session lives as long as its process.
5. **No read of the entries after a tip.**
6. **No "belief basis" concept** in the kernel (decision 6).
7. **No client-only MCP bridge.**
8. **Commands that take host paths read or execute them unconfined.** `science run`
   joins `entrypoint` onto `code`'s parent and reads the Snakefile without checking
   it (`science/commands/run.py`).

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

   It reaches `beliefs` only through `science`, used as a CLI for reads and as an
   endpoint process it launches, plus the published `ledger.v1` format, which it reads
   as a file.

   Orchestrators compose runs and never reach inside one. An orchestrator here is the
   loop, or a person's script.
2. **The run's actor is its session's actor.** A run opens exactly one writer session,
   and that session's `session:<id>` is the run's actor identity. It is fresh by
   construction, so an interactive write by the same person carries a different
   actor, and identity needs no kernel change. The run id is autonomy's own, a fresh
   128-bit hex allocated before the session exists; `events.jsonl` maps it to the
   session id.
3. **A run writes one corpus and, when configured, the store root.** Together these
   are the run's **written chains**. Each is baselined, denied to the actor, and
   checked for membership. Every other mounted corpus is a **read mount**: it is
   baselined, and a move is reported (§9).
4. **Exclusivity is a kernel claim, per host.** `beliefs` gains a cross-process claim
   for each written chain.

   - **Who takes it:** every session constructor, attended and run alike, before its
     `session-open` line.
   - **How long it lasts:** the session holds it until close, and process death
     releases it.
   - **What it refuses:** a second session on a claimed corpus or store root,
     whichever launcher asks.
   - **What it does not cover:** plain library writes (`CorpusWriter` outside a
     session) still bypass it. That stays row 4's obligation, and the ledger
     comparison turns a violation into `quarantined` (§9).

   The claim is a host-local lock. Another host on a synced store is outside it.
5. **The lease and the seal bind per act, at the kernel.** Sealing is a kernel
   operation, `WriterSession.seal()`, made of a flag that `_require_current` checks
   under the session lock. Every ledgered seam already passes through that check
   before it appends an intent.

   - **No new act after the seal.** An act that has already appended its intent
     finishes its commit or is left for recovery, bounded by one act, not by the
     handler. A handler that keeps running gets a refusal at its next act.
   - **The refusal:** `science` maps it to `run-sealed`. It never surfaces as an
     uncaught `SessionClosed`.
   - **What triggers it:** the endpoint seals on lease expiry, on `stop`, or on EOF of
     its control socket. It seals from a control thread that does not wait on the
     dispatcher lock, so a hung handler cannot block the kill switch.
   - **Sealed tips:** after sealing, the endpoint still holds the claim. It reads each
     written chain's tip with a detached read and reports these **sealed tips**: on
     the control socket, and in `<run dir>/seal.json`, which it writes itself. Only
     then does it write `session-close` and exit, releasing the claim.
   - **The interval:** each written chain's interval ends at its sealed tip. A
     legitimate session that opens after the claim is released therefore never lands
     inside a run's interval.
6. **The belief basis is the derivation context, reported by the endpoint.** Beliefs
   are evaluated on read. science's `belief` command evaluates "the shipped belief
   policy". So every belief is a function of the chains, which the heads capture, and
   of everything else an evaluation reads. That second part is the basis:

   - the content digest of the `beliefs` and `science` code the endpoint process
     actually imported (file digests, not version strings, so an editable install
     counts);
   - the belief policy identity;
   - the bound domain packs and corpus contracts.

   The endpoint computes the basis at session open and again at seal, and reports
   both. The orchestrator never computes it, because its own `science` may resolve to
   a different environment. A basis that differs between open and seal is
   `basis-moved`, and the run is `quarantined`.

   Rejected alternative: a digest of every evaluated belief. It costs one evaluation
   for each proposition, twice, and anything it would catch is a head move or a basis
   move already.
7. **Tiers are data in autonomy, and the kernel checks them.** A tier is a constant in
   autonomy: a closed permit in `WritePermit`'s serialized form (§5).

   - The orchestrator hands it to the endpoint at launch, and the endpoint passes it
     to the kernel's run-session constructor as the ceiling.
   - `session-open` records it, and the closing check verifies that the recorded
     permit equals the tier's.
   - Requests carry no permit, and the ceiling is fixed before the session exists.
     Nothing downstream can widen it: not a profile, a command, a body or the actor.
8. **The sandbox is default-deny and proven twice, statically and by probe.** The
   actor runs under `bwrap` in fresh namespaces, with only named paths bound (§7).

   - **Before launch:** the bind list is checked statically against the denied set by
     real path and by `(st_dev, st_ino)` ancestry, so a symlinked alias of a corpus
     is caught.
   - **The probe:** run in the identical sandbox, it must get `ENOENT` from `stat` on
     every denied path.
   - **When either fails:** a failed check, a failed probe, a missing `bwrap`, or
     unavailable unprivileged user namespaces all make the run `unwired` at open. The
     actor never starts. That is §5.2's "never runs on the arrangement alone".
9. **Dispositions have a precedence.** `quarantined` beats `unwired`, which beats
   `clean`, and every finding is listed whatever the disposition.
   - `quarantined` says that something wrong was seen, and the effects are held.
   - `unwired` says that the guard could not vouch.

   When both hold, holding the effects is the stronger instruction.
10. **The closing comparison is autonomy's own code.** It does not call beliefs'
    `reconcile`. The governing design splits autonomy from science on code-lineage
    independence, and a check that delegates its verdict to the kernel it guards
    shares the kernel's blind spots. So autonomy compares raw evidence itself: the
    chain intervals from a science read, and the ledger file. Its rules mirror
    `reconcile`'s where the two overlap (§9). A disagreement between the two is a
    defect to report.
11. **A run confines every host path an actor can name.** Under a run session, a
    command input that names a host path must resolve, by real path, under the run's
    scratch directory, or it is refused `path-outside-run`. Commands that execute
    code (`run`) execute under kernel confinement whose denied set includes the
    envelope's. A command reachable at a tier that cannot meet both is not reachable
    under a run session: science refuses it at dispatch.

## 3. A run, end to end

**Open.** Steps run in order. A failure at any step before 9 closes the run with the
named disposition, and the actor never starts.

1. **Allocate the run directory and the scratch directory.**
   - **Run directory:** `<state>/runs/<run-id>/`. `<state>` defaults to
     `$XDG_STATE_HOME/verifiably-autonomy`.
   - **Scratch directory:** `<cache>/scratch/<run-id>/`, outside `<state>`.
     `<cache>` defaults to `$XDG_CACHE_HOME/verifiably-autonomy`.
   - **Host-side socket directory:** `$XDG_RUNTIME_DIR/va/<run-id[:12]>/`, short
     because of the 107-byte `AF_UNIX` limit.
2. **Refuse on configuration** (exit 2, no run directory kept) when:
   - the tier is `publishes`;
   - the write corpus is not among the world's corpus roots;
   - the lease is below the floor (§8);
   - another run directory on this host names the same written chain without a
     disposition (`orphaned-run`, §3 *Orphans*).
3. **Capture the baseline heads** with `science heads --resolve`. This is a
   recovery-resolving read: it settles any work a crashed writer left pending. It
   reads the world head, every mounted corpus's head (genesis and tip), and the store
   root's head.
   - A chain still pending after resolution is `unwired` (`baseline-pending`).
   - An unavailable read is `unwired` (`baseline-unavailable`).

   Write `baseline.json` (§6), fsync it, then fsync its directory.
4. **Launch the endpoint** as `science serve --run <launch.json>`, a child process.
   - **Launch file:** names the tier's permit, the written chains, the run
     directory, the scratch directory, the socket and control socket paths, the token
     file, and the lease.
   - **What the endpoint does:** opens a run session through the kernel's run
     constructor, taking the claims (decision 4). It then reports
     `{session_id, ledger_path, basis_open}` on the control socket.
   - **Failure:** a refusal, including `corpus-claimed`, or no report within the
     start timeout, is `unwired` (`endpoint-unavailable`).
5. **Verify the session.** Read `session-open` from the ledger. Its permit must equal
   the tier's, and its actor must be `session:<session_id>`. A mismatch is `unwired`
   (`permit-mismatch` or `actor-mismatch`), and the endpoint is stopped.
6. **Re-read the written chains' heads** with a detached read. They must equal the
   baseline's. A move between steps 3 and 5 means a write landed outside the run
   before the claim, which is `unwired` (`baseline-raced`).
7. **Check the binds statically, then probe the sandbox** (decision 8). A failure is
   `unwired` (`sandbox-unproven`).
8. **Append to `events.jsonl`** as each step completes: the session id, the ledger
   path, the opening basis, the pids (each with its start time), and the probe
   result.
9. **Start the actor** from the orchestrator's main thread, under the sandbox, with
   `--info-fd` to learn the namespace's init pid. Start the heartbeat.

**During.** The actor reaches the world only through the handle (§7). The orchestrator
renews the lease every lease/3.

**Close.** Any one of these triggers the close:

- the actor exits;
- `autonomy run stop <run-id>`;
- the wall-clock bound.

Then:

1. **Seal.** Send `seal` on the control socket. The endpoint seals (decision 5),
   reports the sealed tips and `basis_seal`, writes `seal.json`, writes
   `session-close` and exits.
2. **Kill the actor's namespace** if it is still alive (§8).
3. **Run the closing check** (§9) over the intervals from the baseline heads to the
   sealed tips.
4. **Write `disposition.json`** (§9), fsync it, and exit with the disposition's code:
   0 `clean`, 3 `quarantined`, 4 `unwired`.

**Orphans.** A run directory with a baseline and no disposition belongs to an
orchestrator that died.

- **What happens to the endpoint:** it sees EOF on its control socket and seals
  within one read, writing `seal.json` itself.
- **Closing it:** `autonomy run close <run-id>` runs the closing check. Its
  disposition is at least `unwired` (`orchestrator-lost`), and a `quarantined`
  finding still takes precedence.
- **No `seal.json`:** if the endpoint died too, each interval ends at the last entry
  that is a member by §9's rules. Later entries are reported as `after-run`, never
  classified, because the claim no longer held.
- **What guards the orphan:** the kernel claim dies with the endpoint, so autonomy's
  scan at step 2 is what keeps an unclassified interval out of the next run's
  baseline.

## 4. Components

**`autonomy`** is the new Python package `verifiably-autonomy`, under
`python/src/autonomy/` like the sibling repositories. It has one module per concern:

| module | does | depends on |
|---|---|---|
| `tiers` | the tier constants and their serialized permits; refusing `publishes` | nothing |
| `ledger` | a reader for `ledger.v1`: the lines the check needs; a torn tail or an unknown line is a typed finding, never a crash | nothing |
| `closing` | the comparison of §9: pure, over typed inputs, no I/O | `ledger`, `baseline` types |
| `sandbox` | the sandbox spec, the static bind check, the `bwrap` argv, the probe | `bwrap` |
| `science_reads` | the only place that invokes the `science` CLI: `heads` and `log`, parsed into typed values | the `science` CLI |
| `baseline` | writing and reading `baseline.json`, `events.jsonl`, `seal.json` | `science_reads` |
| `endpoint` | launching `science serve --run`, the control-socket client, heartbeat, seal | the `science` CLI |
| `run` | the supervisor of §3 | all |
| `cli` | `autonomy run`, `run stop`, `run close`, `run show` | `run` |

**`science`**, filed from the plan, needs:

- `serve --run <launch file>`;
- the token and peer-namespace check (§7);
- the control socket (lease, seal, reports, `seal.json`);
- the `run-sealed` refusal mapping;
- the path-input confinement and the dispatch refusal of decision 11;
- `mcp bridge`, a client-only bridge to a handle;
- `heads [--resolve]` and `log` (§10);
- the basis computation.

**`beliefs`**, filed from the plan, needs:

- `open_run_session(…, ceiling: WritePermit)`, deserializing the permit;
- the cross-process claim on each written chain, taken by every session constructor;
- `WriterSession.seal()`;
- a detached read of the entries after a tip;
- the belief-policy and contract identities the basis reads;
- the confinement denied-set extension that decision 11 names.

Each of these is a design slice in its own repository, frozen in a conformance cut
there.

## 5. Tiers as permits

| tier | permit | the actor may |
|---|---|---|
| `report-only` | no kinds, no families | read; `session`-class commands (selection) |
| `coordination` | the ordinary coordination kinds; `corpus-write` | mint coordination kinds only |
| `mints:{kind: route}` | coordination ∪ `for_kinds(kinds, routes)` | also mint the named kernel kinds through their routes |
| `publishes` | `_PUBLICATION_PERMIT` | refused at open: never unattended |

How the tiers relate:

- **Inclusion:** `report-only` ⊂ `coordination` ⊂ `mints:M`, for any M. `publishes`
  is above them in the order of trust but is not a superset: its permit lacks `run`,
  `holdings` and the coordination kinds. Only its refusal matters here.
- **Mints:** a mints tier names its kinds with their routes, for example
  `{"proposition": "corpus-write", "run": "run", "holdings-observation": "holdings"}`.
  A kind with several admissible families needs a route. The kind and route map is
  part of the tier and is recorded in the baseline.
  - An empty map is refused, because it would be `coordination` by another name.
  - A map naming a non-command-reachable family is refused.
  - `holdings-observation` in the map is what makes the store root a written chain.
    Without it the store root is a read mount.
- **Ungoverned writes:** `ungoverned` is `false` at every tier.

The serialized permit is `{"kinds": [...sorted], "act_families": [...sorted],
"ungoverned": false}`, the shape `session-open` records. That makes the check at step
5 an equality between two canonical JSON values.

## 6. The run directory

- **`baseline.json`**, version 1, is written once at step 3, before any session
  exists:

  ```json
  {
    "version": 1,
    "run": "<run id>",
    "opened_at": "<UTC RFC 3339>",
    "tier": {"name": "mints", "routes": {"proposition": "corpus-write"}},
    "permit": {"kinds": ["decision", "hypothesis", "note", "project", "proposition",
                         "question", "task", "theme", "topic"],
               "act_families": ["corpus-write"], "ungoverned": false},
    "world": {"root": "...", "id": "...", "genesis": "<64 hex>", "tip": "<64 hex>"},
    "written": {"<corpus id>": {"root": "...", "genesis": "<64 hex>", "tip": "<64 hex>"}},
    "mounts": {"<corpus id>": {"root": "...", "genesis": "<64 hex>", "tip": "<64 hex>"}},
    "actor_argv": ["..."],
    "sandbox": {"binds": [], "network": "host"},
    "lease": {"seconds": 60}
  }
  ```

- **`events.jsonl`** is append-only and fsynced line by line. It holds the facts that
  exist only after step 3: the session id, the ledger path, the opening basis, pids
  with their start times, the probe result, and actor start and exit.
- **`seal.json`** is written once, by the endpoint: the sealed tips, the closing basis
  and the seal cause (`stop`, `lease`, `eof`).
- **`disposition.json`** is written once, by the closing check (§9).

The token file and the launch file live in the run directory with mode 0600.

None of these is ever rewritten. Together they are the baseline record that governing
§7.1 places outside any corpus the actor can write: the sandbox never binds the run
directory.

## 7. Sandbox and endpoint handle

**The sandbox spec** is data. It names:

- the read-only system binds (`/usr`, `/etc`, and the `/bin`, `/lib`, `/lib64` and
  `/sbin` symlinks);
- the actor's own toolchain paths, each listed;
- the scratch directory, bound read-write at `/work`;
- the endpoint socket, at the fixed path `/run/va/endpoint.sock`;
- the token file, bound read-only at `/run/va/token`;
- the network mode (`none` or `host`);
- the environment.

**The argv** is `bwrap --unshare-all [--share-net] --die-with-parent --new-session
--clearenv --proc /proc --dev /dev --tmpfs /tmp --info-fd <n>`, followed by the
binds, then `--setenv` for non-secret variables only, then the actor argv.

**What the actor is given:** `VERIFIABLY_ENDPOINT=/run/va/endpoint.sock` and
`VERIFIABLY_TOKEN_FILE=/run/va/token`. The token never appears in an argv, the
environment, the baseline, a log, or any command's output.

**The denied set** is computed from the world configuration, never from the spec:

- the world root and every corpus root;
- the store root;
- the operations root;
- `<state>`, which holds every run directory.

**The static check** refuses a bind whose source's real path, or whose
`(st_dev, st_ino)` chain, is an ancestor or descendant of any denied path. A bind of
`/` is refused by the same rule.

**The probe** runs `/bin/sh` in the identical spec. For each denied path, given as an
argument by its real path, it reports `stat`'s errno, and every one must be `ENOENT`.

**The handle** is the socket plus the token.

- **What the endpoint accepts:** a connection whose `SO_PEERCRED` pid lives in the
  actor's PID namespace, compared by the `/proc/<pid>/ns/pid` inode against the init
  pid from `--info-fd`, and that presents the token.
- **What it refuses:** a host process of the same uid that reads the token file and
  connects is refused `bad-peer`. Without that check it would dispatch under the
  run's actor and pass membership.
- **What stays outside the boundary:** same-uid processes that write the corpora
  directly, not through the endpoint, are row 4's obligation, caught as
  `entry-foreign`.

**MCP:** an MCP-speaking harness is given `science mcp bridge` as its MCP server. The
bridge reads the handle from the environment and opens no session.

## 8. Lease and kill switch

- **The lease** is `lease.seconds`. The floor is 10 s and the default is 60 s.
  - **Renewal:** the orchestrator sends `renew` every lease/3.
  - **The deadline:** the endpoint holds `deadline = monotonic() + seconds`. A control
    thread seals the session when the deadline passes, and the per-act seal check
    makes that binding at the next act (decision 5).
  - **A dead orchestrator** closes the control socket. EOF seals at once. The lease is
    the bound when the orchestrator is hung rather than dead.
- **The kill switch** is `autonomy run stop <run-id>`. It locates the orchestrator
  through `events.jsonl`, by pid plus start time, opened as a pidfd so a reused pid is
  never signalled. It sends SIGTERM. The orchestrator then:
  1. seals the endpoint and waits for its sealed-tips report;
  2. sends SIGTERM to the namespace's init pid, then SIGKILL after a 10 s grace.
     Killing PID 1 of the namespace kills every process in it;
  3. closes normally.

  If the orchestrator is already gone, `stop` reports that and directs the operator to
  `run close`. The endpoint has sealed by EOF. Seal comes before kill, so no act
  starts between deciding to stop and the actor's death.
- **The actor dies with the orchestrator.** `--die-with-parent` is
  `PR_SET_PDEATHSIG`, which fires when the spawning thread exits. The actor is
  therefore spawned from the orchestrator's main thread, which lives until close.

## 9. The closing check

**Inputs:**

- the baseline, events, seal and ledger;
- for each written chain, a detached `science log --after <baseline tip>`, bounded at
  the sealed tip;
- a detached `heads` read for the world and the read mounts.

**Output:** a disposition and a list of findings. Each finding has a code, a ref (an
entry digest, a corpus id or a path) and a one-line message.

**Membership.** Each written chain's interval is the entries after its baseline tip,
up to and including its sealed tip. Each entry is classified, mirroring `reconcile`:

- **Intent entry:**
  - A member if a ledger `act` line names it as `intent` and its decoded actor is the
    run's.
  - A run-actor intent that no `act` line names is `outcome-unknown`, which is
    `unwired`. This happens when an execution failed after its intent, or a crash
    came between the commit and the ledger line.
  - Any other intent is `entry-foreign`, which is `quarantined`.
- **Registration entry:**
  - A member if an `act` line names it as `entry`, its `fulfills` is that line's
    `intent`, and that intent is a member.
  - A registration fulfilling a run-actor intent that no `act` line names is
    `outcome-unknown`.
  - Otherwise it is `entry-foreign`.
- **Settled entry:**
  - A member if its `registration` is a member registration, or a registration that
    is `outcome-unknown`.
  - A settlement that recovery appended for a run-actor intent that never registered
    is a member, reported as `entry-settled-recovery`.
  - Otherwise it is `entry-foreign`.
- **Every `act` line:** its intent and registration must appear in the interval, with
  a settlement whose `committed` is true. Otherwise it is `act-unverified`, which is
  `unwired`.

**The rows:**

| condition | finding | disposition |
|---|---|---|
| baseline, events, ledger or a read is unavailable | `baseline-unavailable` / `ledger-unavailable` / `read-unavailable` | `unwired` |
| the ledger has a torn tail or an unknown line | `ledger-malformed` | `unwired` |
| no `seal.json` (endpoint died) | `seal-missing` | `unwired`; the intervals end per §3 *Orphans* |
| a baseline tip is not on its chain (the chain was rewritten) | `chain-discontinuous` | `quarantined` |
| an entry that neither the ledger nor the run's actor explains | `entry-foreign` | `quarantined` |
| a run-actor entry with no `act` line | `outcome-unknown` | `unwired` |
| a ledger `act` not verified in the interval | `act-unverified` | `unwired` |
| the world head moved | `world-moved` | `quarantined` |
| the basis differs between open and seal | `basis-moved` | `quarantined` |
| the ledger has no `session-close`, or has open invocations | `session-unclosed` | `unwired` |
| `session-open`'s permit differs from the tier's | `permit-mismatch` | `unwired` |
| the orchestrator was lost | `orchestrator-lost` | `unwired` |
| a read mount moved | `mount-moved` | none (reported) |
| a recovery settlement of a run-actor intent | `entry-settled-recovery` | none (reported) |
| entries after the last member, when there is no seal | `after-run` | none (reported) |
| none of the above | — | `clean` |

**Why a world move and a mount move differ.** The world chain moves only by the
registry, epoch and lifecycle families, which are outside every unattended tier. A
world move therefore changes the frame the run resolved names in, under it, and it is
quarantined. A read mount moves whenever its owner works, so treating that as
quarantine would make every run on a shared world fail. The run's own records cite
what they read by digest, so a later mount change cannot alter what they say. The
move is reported.

**Precedence.** The disposition is the strongest the rows produce (decision 9).

**`disposition.json`** records:

- `{version, run, disposition, findings[], closed_at}`;
- the member entries of each written chain;
- the closing heads.

A second `run close` on a closed run prints the existing disposition and changes
nothing.

## 10. The seam: commands as tools

`autonomy` uses `science` in two ways:

- **as a CLI**, for reads;
- **as an endpoint process**, which it launches.

It holds no private kernel path.

Two read commands are new. Both are `read-only` class, and both exist for people too:

- **`heads [--resolve]`:** the world head, and the genesis and tip of every mounted
  corpus and of the store root. The read is detached by default. `--resolve` uses the
  recovery-resolving read and reports any chain still pending.
- **`log --chain <corpus id | store> --after <tip> [--through <tip>]`:** a detached
  read, in chain order. Each entry carries:
  - its digest and entry type;
  - for an intent, the decoded kind and actor;
  - for a registration, `fulfills`;
  - for a settlement, `registration` and `committed`.

  A tip that is not on the chain is refused `tip-unknown`, which is how
  `chain-discontinuous` is detected. The output budget pages through a cursor as
  usual.

The basis is not a command. The endpoint computes and reports it itself (decision 6).

**Harness neutrality** follows from the shape of the run: the actor is an argv, the
handle is two environment variables, and the MCP bridge is optional. pi, Claude Code
and a shell script run identically under `autonomy run`. Anything specific to a
harness, such as a pi configuration naming the bridge or a model credential, belongs
to the caller and never enters the envelope.

## 11. A tier as an authorization

The companion authorization model (autonomy-1aac03) describes a grant by the parts
below. A tier fills each of them as follows:

| part of a grant | where it lives |
|---|---|
| identity | the run's actor `session:<id>` |
| operation and resource | the permit (kinds, routes, families) over the written chains |
| scope | the claims, the sandbox's denied set, path-input confinement |
| lifetime | the lease and the wall-clock bound |
| revocation | `run stop`; the seal |
| approval | the person or orchestrator that ran `autonomy run` with that tier; `publishes` is never approvable unattended |
| audit receipt | the run directory and the ledger |
| rollback | out of scope here: a `quarantined` run lists its members for a person to act on |

A flow gate grants none of these. A tier comes only from an `autonomy run`
invocation.

## 12. Verification

Each row has a test that can fail and a negative test. Rows marked *(pending)* need a
`science` or `beliefs` piece. Until that piece lands they are skipped with the piece
named, never passed.

| row | claim | test | negative |
|---|---|---|---|
| E1 | every tier's permit is the table's; `publishes`, an empty mints map, and a non-reachable family are refused at open | unit: each constant against literal permits; `run --tier publishes` exits 2 with no run directory | a tier built from `full()` fails the unit |
| E2 | `closing` classifies every entry type and gives each row's disposition and the precedence | unit: constructed evidence for every row, every entry type and each pair of rows; a normal commit's intent, registration and settlement are all members | swapping two precedence ranks fails a pair case; dropping the settlement rule turns the normal-commit case `quarantined` |
| E3 | the ledger reader types a torn tail and an unknown line as findings | unit over byte fixtures | a reader that raises fails the fixture |
| E4 | the static check refuses aliases of the denied set | unit: a symlink to a corpus, a parent of the operations root, `/` | an unrelated directory passes |
| E5 | the probe gets `ENOENT` on every denied path; `bwrap` missing means `unwired` before the actor | integration: real `bwrap`, a planted bind that bypasses the static check (test hook) | the same spec without the plant passes, and the actor starts |
| E6 | the actor's namespace dies on `stop` and with the orchestrator | integration: an actor that forks a sleeper; `stop`; SIGKILL the orchestrator in a second case; no process survives | an actor spawned from a short-lived thread is killed early (documents the main-thread rule) |
| E7 *(pending)* | the session's recorded permit and actor are verified | integration: an endpoint launched with a permit wider than the tier | the exact permit passes step 5 |
| E8 *(pending)* | a write outside the session lands as `entry-foreign` and `quarantined` | mid-run, a bare `CorpusWriter` in another process writes the corpus | the same run without it is `clean` |
| E9 *(pending)* | after the seal, no act lands, and a write after the release falls outside the interval | an actor writing in a loop; `stop`; then open an attended session and write | the seal-less variant (test hook) puts an entry after `stop` inside the interval |
| E10 *(pending)* | the lease seals a hung orchestrator; EOF seals a dead one | SIGSTOP the orchestrator past the lease; separately SIGKILL it; a write request is refused `run-sealed` | while renewing, the request lands |
| E11 *(pending)* | an orphan closes `unwired` with `orchestrator-lost`, and a new run on its corpus is refused until then | SIGKILL the orchestrator; `run` refuses `orphaned-run`; `run close` | a normally closed run allows the next |
| E12 *(pending)* | world, basis and baseline races are seen | move the world head; change a pack binding between open and seal; write between steps 3 and 5 | an untouched run is `clean` |
| E13 *(pending, science)* | a host process holding the token is refused `bad-peer`; a request without the token is refused | endpoint test | the actor's own request dispatches |
| E14 *(pending, science)* | a path input outside the scratch directory is refused `path-outside-run` | `run` with `entrypoint` naming a host file | the same file copied into scratch is accepted |
| E15 *(pending, beliefs)* | a second session on a claimed chain is refused, across processes | kernel test | sequential sessions both open |
| E16 *(pending, beliefs)* | `seal()` refuses the next act and lets an in-flight one finish | kernel test with a held act | an unsealed session's next act lands |

## 13. Delivery

The work lands across three repositories. The autonomy work splits into two plans
because half of it cannot be tested before the slices in `science` and `beliefs` land:

1. **Plan A (autonomy, now):** package skeleton, `tiers`, `ledger`, `closing`,
   `sandbox` with the static check and probe; rows E1–E6.
2. **The `beliefs` slice:** the run constructor with ceiling, the claims, `seal()`,
   the detached after-tip read, the basis identities, the confinement extension; rows
   E15–E16. It is filed in `beliefs`, designed there, and frozen in a cut.
3. **The `science` slice:** `serve --run`, the handle checks, the control socket,
   `seal.json`, the `run-sealed` mapping, path confinement, `mcp bridge`, `heads`,
   `log`, the basis computation; rows E13–E14. It is filed in `science`, and depends
   on 2.
4. **Plan B (autonomy, after 2 and 3):** `science_reads`, `baseline`, `endpoint`,
   `run`, the CLI; rows E7–E12.

The first unattended run (autonomy-9e8a43) starts after 4.

## 14. Alternatives rejected

- **A container per run (Docker).** It gives the strongest isolation, but it needs a
  root daemon, image management, and a socket crossing a daemon-managed boundary.
  `bwrap` gives the same filesystem denial rootlessly. A container stays a later
  sandbox backend behind the same spec.
- **A lease that the actor renews, or a file that the endpoint polls.** If the actor
  renews, the constrained party extends its own authority. A polled file uses wall
  clock and races the act it guards.
- **Sealing at the dispatcher.** The dispatcher lock spans a whole handler. A seal
  that waits on it lets a long handler keep acting, and a hung one blocks the kill
  switch. The kernel's per-act check has neither problem.
- **Ending the interval at the closing read.** The claim is released before the read,
  so a legitimate session's writes would land inside the interval and quarantine
  clean runs. The sealed tip is read while the claim still holds.
- **The closing check through beliefs' `reconcile`.** Rejected by decision 10.
- **Exclusivity by socket path.** This is what exists today. Two launchers with
  different configurations name different sockets and open the same corpus.
- **The basis computed by the orchestrator, or from version strings.** The
  orchestrator's environment may differ from the endpoint's, and an editable install
  keeps its version while its code changes.
- **The basis as a digest of all evaluated beliefs.** Rejected by decision 6.
- **Runs that write several corpora.** The session writes one root. Widening it is a
  kernel slice of its own, with no consumer yet.
- **The token in the actor's environment or argv.** Both are readable through `/proc`
  by any same-uid process. A read-only bound file plus the peer-namespace check means
  a stolen token is not enough.
