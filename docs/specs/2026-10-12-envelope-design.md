# Envelope — design (sub-project 6)

**Date:** 2026-10-12
**Status:** approved 2026-10-12 (human review round 10). Plan A (§13 item 1) implemented
the same day: `docs/plans/2026-10-12-envelope-plan-a.md`, rows E1–E6 and E17. Items 2–3
are open: beliefs-7a56ef, sci-a1d45f. Item 4 stays open until B2 lands; it is split: Plan B1, the launch side that
needs neither slice (autonomy-641123, `docs/plans/2026-10-15-envelope-plan-b1.md`),
implemented on 2026-10-15, and Plan B2, the endpoint side (autonomy-f6efe8), open. Revised after review round 1, which found 3 Critical, 9
Important and 8 Minor problems; after round 2, which found 7 Important and 2 Minor;
after round 3, which found 2 Important and 5 Minor; after round 4, which found 2
Important and 2 Minor; after round 5, which found 1 Important and 5 Minor; and after
round 6, a human-directed review that found 3 P1 and 3 P2; and after round 7, which
found 2 P2 and 5 P3; after round 8, a human-directed review that found 3 P2; and
after round 9, a human-directed review that found 1 P2. All of them are addressed
in
this text.
**Amendment of 2026-10-15** (autonomy-a41de4): the actor's stdio. It adds decision 12,
adds SIGTERM to decision 5's seal triggers, and changes §3, §6, §7, §8, §10, §12 (row
E20), §13 and §14 to match. It follows the probe autonomy-c5c566. Approved 2026-10-15
(human review round 8), after five agent review rounds and three human ones.
**Amendment of 2026-10-17** (autonomy-efa755): egress and credential custody. It adds
decision 13. It moves both out of autonomy-9e8a43's deferral (§1), replaces decision 12's
credential template, removes the `host` network mode, and changes §3, §4, §6, §7, §8,
§9, §10, §11, §12 (rows E21 and E22), §13 and §14 to match. Status: draft, for review.
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
- **Budget accounting and enforcement, outcome shapes, scratch's lifetime and the
  evidence report:** autonomy-9e8a43, which consumes this envelope. Its allowance check
  joins the model proxy at the point decision 13 names. Egress and credential custody
  are decision 13's, shared by every run.
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
   - **What triggers it:** the endpoint seals on lease expiry, on `stop`, on EOF of
     its control socket, or on SIGTERM. It seals from a control thread that does not
     wait on the dispatcher lock, so a hung handler cannot block the kill switch.
     - **SIGTERM is taken by the control thread,** with SIGTERM blocked in every other
       thread and received by `sigwait` or a signalfd. A handler on the main thread
       could wait behind a hung request. A stop of the caller's whole scope (cgroup)
       delivers it (decision 12).
     - **Terminal and process-group signals never reach the endpoint.** It runs in its
       own session, so neither a Ctrl-C at the caller's terminal nor a signal to the
       caller's process group reaches it. Those reach the orchestrator, which treats
       SIGINT and SIGHUP as SIGTERM (§8). They also reach the outer `bwrap` unless it
       runs in a process group of its own, which it does (§3 step 9).
     - **The first trigger wins.** A later trigger joins the seal in progress. The
       first trigger's cause is recorded, and `seal.json` is written once.
   - **Sealed tips:** sealing has three steps.
     1. The endpoint sets the flag without taking the session lock.
     2. It acquires the session lock, with a timeout (the seal timeout, 30 s by
        default). Acts come in two shapes, and the lock treats them differently:
        - **A scoped act** (`ScopedWriter._act`) holds the lock across the whole act,
          so acquiring the lock drains it. There is at most one.
        - **A route act** takes the lock once per phase. Such an act is not drained;
          it is cut at its next phase, which is refused `run-sealed`.
          - **A run record** (`session/routes.py`) has two phases: the intent, and
            the fulfil. Between them the confined job runs (`_execute_run`, under
            `bwrap`) without the lock and without writing any chain.
          - **A holdings observation** (`ledgered_seam`) has more: the intent, then
            `store_write`, `store_move` or `store_delete`, then
            `publish_fulfilling`. Each holds the lock for its call, so a store
            write in progress is drained and lands before the sealed tip. Each
            store operation appends a store-chain registration whose `fulfills` is
            null, plus its settlement; the `beliefs` slice ledgers it (§4).
            `store_genesis` and `read_path` are guarded reads that append nothing.

          The check reports a cut route act as `intent-unfulfilled` (§9).
     3. The endpoint kills its own execution subtree. The confined job's outer
        `bwrap` is a direct child of the endpoint, in the endpoint's own process
        group, so a process-group kill would take the endpoint with it. Instead, the
        endpoint runs its jobs in a child cgroup it owns and kills that cgroup.
        Killing the outer `bwrap` takes down the job's PID namespace through
        `--die-with-parent`, which also covers the endpoint's own death.

        Where no delegated cgroup is available, the endpoint SIGKILLs its direct
        children (`/proc/self/task/*/children`). That list can miss a `bwrap`
        spawned concurrently by a run act whose intent preceded the flag. Such a job
        writes no chain, because its fulfil is refused, and `--die-with-parent`
        kills it when the endpoint exits.
     4. Holding the lock and still holding the claim, it reads each written chain's
        tip with a detached read. It reports these **sealed tips** on the control
        socket and in `<run dir>/seal.json`, which it writes itself. Only then does
        it write `session-close` and exit, releasing the claim.

     If the lock is not acquired in time, the endpoint reports `seal-timeout`. The
     orchestrator appends that to `events.jsonl` and kills the endpoint, and the run
     closes through `seal-missing` and the orphan interval rule (§3). An endpoint
     whose control socket is already at EOF does the same on its own: it kills its
     execution subtree and exits without `seal.json`.
   - **The interval:** each written chain's interval ends at its sealed tip. A
     legitimate session that opens after the claim is released therefore never lands
     inside a run's interval.
6. **The belief basis is the derivation context, reported by the endpoint.** Beliefs
   are evaluated on read. science's `belief` command evaluates "the shipped belief
   policy". So every belief is a function of the chains, which the heads capture, and
   of everything else an evaluation reads. That second part is the basis:

   - the content digest of a fixed file set: every file installed into the endpoint's
     environment by `beliefs`, `science`, and the transitive closure of their
     `verifiably-*` requirements (`nodes` and `atoms` today; `nodes` parses every
     record) (each distribution's
     `RECORD`, or a walk of its package tree for an editable install). These are file
     digests, not version strings, so an editable install counts. The set is fixed at
     open and re-digested at seal. A digest of the modules actually imported would grow
     with the kernel's lazy imports and move on its own;
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
     every denied path, and `ENETUNREACH` from a connect to a non-loopback IPv4 and
     IPv6 address (decision 13).
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
11. **A run confines every host path an actor can name, by descriptor, not by path
    string.** A check on a path followed by a later open is a race the actor wins: it
    can swap a checked file or directory for a symlink in between. So under a run
    session, the endpoint never opens an actor-named path by name.

    - **The scratch handle.** At launch, the endpoint opens the scratch directory
      once (`O_PATH | O_DIRECTORY`) and holds that descriptor for the session.
    - **Path inputs.** A command input that names a host path must be absolute, and
      its leading path components must equal the scratch path's components, compared
      component by component and never as a string prefix (`…/run1` is not a prefix
      of `…/run10/x`). Otherwise it is refused `path-outside-run`. The
      remainder is opened relative to the scratch handle with `openat2` and
      `RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS |
      RESOLVE_NO_XDEV`. A path that fails to resolve under those flags is refused
      `path-outside-run`. Everything after that reads through the resulting
      descriptor.
    - **Directory capture.** A directory input (`run`'s `code`) is captured before
      anything uses it. The endpoint copies it to
      `<operations root>/capture/<invocation>/<basename of code>`, which the actor
      cannot reach. The basename is kept because the kernel's bundle names files
      under the code root's own name. The capture directory is separate from the
      kernel's own staging under `<operations root>/scratch/<invocation>`. The walk goes entry by
      entry: each child is opened with `openat2` relative to its parent's descriptor,
      under the same flags plus `O_NOFOLLOW`, checked with `fstat`, and read from
      that descriptor. A symlink, device, FIFO or socket is refused. Every later step
      (validation, bundling, execution) uses the private copy, so a swap in scratch
      after capture changes nothing.
    - **Platforms without `openat2`** (Linux before 5.6, or a seccomp policy that
      blocks it): path inputs are refused `path-confinement-unavailable`. The
      endpoint never falls back to resolving paths by name.
    - **Shared paths.** The scratch directory is bound into the sandbox at its own
      canonical host path, so the actor and the endpoint name the same file the same
      way.
    - **Code execution.** Commands that execute code (`run`) execute the private
      copy under kernel confinement whose denied set includes the envelope's.
    - **Fail closed.** A command reachable at a tier that cannot meet all of this is
      not reachable under a run session: science refuses it at dispatch.

    `run`'s `entrypoint` is not a host path, and the scratch rules do not apply to it.
    It stays what the kernel's execution contract makes it: a path relative to the
    captured bundle, checked by `validate_entrypoint` inside the bundle. science
    builds the bundle from the private copy of `code` and passes `entrypoint`
    through unchanged. One change comes first: today `prepare` reads
    `code_root.parent / entrypoint` by name before the kernel checks anything. Under a
    run session that read goes through `openat2` beneath the capture's parent
    directory, with the same flags. An entrypoint such as `../..` is therefore refused
    `path-outside-run` before any intent exists.
12. **The actor's stdio is the caller's channel, and it carries bytes only.**
    `autonomy run` hands its own fds 0, 1 and 2 to the actor, so a caller drives the
    actor over the stdio of the `autonomy run` it started: crew drives
    `pi --mode rpc` this way. The probe autonomy-c5c566 ran pi's RPC over
    passed-through pipes in Plan A's sandbox, abort included.

    - **What may be passed.** Step 2 (§3) checks each of fds 0, 1 and 2 with `fstat`
      and `fstatfs`, and each must be one of these:
      - `pipe`: an anonymous pipe (on pipefs). A named FIFO is refused, because the
        actor could reopen it through `/proc/self/fd` and reach its other users.
      - `socket`: an `AF_UNIX` `SOCK_STREAM` socket, not listening, and connected:
        `getpeername` succeeds. An unconnected one would let the actor connect to the
        host's abstract sockets. Node's `'pipe'` stdio is such a socketpair.
      - `null`: `/dev/null`, identified by `S_ISCHR` and `st_rdev` 1:3, never by
        path.

      Anything else is refused `stdio-refused`, naming the fd and what it is: a closed
      fd, a terminal or other device, a regular file, a directory, a listening,
      unconnected or datagram socket, or a socket of another family. Each of these hands the actor a
      host object by descriptor, past the static check and the probe:
      - A terminal gives the actor the person's keystrokes, its ioctls and its
        termios.
      - A file can be reopened read-write through `/proc/self/fd`, even when it was
        passed read-only.
      - An `AF_INET` or unconnected socket reaches the host's network namespace,
        past the sandbox's own (decision 13).

      A connected stream ends at a process the caller chose: its own, or a host
      service it hands the stream to, such as journald under a systemd unit, where the
      actor's lines appear under the unit's name. What that process does with the bytes
      is the caller's choice. A person at a terminal runs
      `(set -o pipefail; autonomy run … </dev/null 2>&1 | cat -v)`. Without
      `pipefail`, a pipeline's status is its last command's, so `cat`'s 0 would hide
      an `unwired` or `quarantined` run. From step 9 on, the person sees only the
      actor's output. The exit code is the outcome. The run's id in the
      diagnostics before step 9 is a convenience for `run show <id>`, because the actor
      can read and forge stderr. The kinds are recorded in
      `baseline.json` (§6).
    - **What the actor holds.** Fds 0, 1 and 2, and no other descriptor. The gate takes
      its release on a dedicated pipe and closes it before it execs the actor (§7).
    - **The channel is the actor's alone once it starts.** `autonomy run` never reads
      fd 0 and never writes fd 1, refusals included. It writes diagnostics on fd 2 only
      before step 9, and it ignores a failed write there. Once the actor has started, it
      replaces its own fds 0 and 1 with `/dev/null` and its fd 2 with
      `<run dir>/orchestrator.log`. From then on:
      - nothing on its lease or kill path can block on a caller that stops reading, or
        fail on one that closes;
      - the caller sees EOF when the actor's namespace is gone.

      No other process that `autonomy run` starts receives the caller's descriptors.
      The preflight, the probe and the `science` reads get stdin from `/dev/null` and
      have their output captured. The endpoint gets stdin from `/dev/null`, and its
      stdout and stderr go to `<run dir>/endpoint.log`, so its confined jobs inherit no
      descriptor of the caller's either.
    - **stderr is not evidence.** The actor can read back what was written on a pipe
      it holds, by reopening it through `/proc/self/fd`, and it can write anything
      there. So nothing relies on stderr: diagnostics before step 9 are for a person.
      The record is the exit code, the run directory, and the report fd.
    - **The report fd** is how a program learns which run it started.
      `autonomy run --report-fd <n>` names a descriptor that the caller opened and that
      the actor never holds. On it, `autonomy run` writes one JSON line once step 2
      passes, `{"run": "<run id>", "run_dir": "<path>", "scratch": "<path>"}`, and a
      second line after `disposition.json` is durable,
      `{"run": "<run id>", "disposition": "<clean|quarantined|unwired>", "exit": <code>}`.
      Then it closes the descriptor. A caller checks that `run_dir` is
      `<state>/runs/<run>`, and treats a line without its newline as absent.
      - **Kinds.** The report fd must be an anonymous pipe or a connected `AF_UNIX`
        stream socket. Step 2 refuses anything else. A regular file always polls
        writable, yet a write to it can block on filesystem I/O.
      - **No write can hang the run.** Every line `autonomy run` writes to a caller's
        descriptor, on the report fd and on stderr before step 9, goes through a
        non-blocking path. A poll alone is not enough: it reserves no space, and
        another holder can fill the channel between the poll and the write. The path
        leaves the descriptor's own flags alone, because they belong to an open file
        description that the caller shares, and on fd 2 the actor too:
        - **Socket:** `send` with `MSG_DONTWAIT` on each call.
        - **Pipe:** a private descriptor obtained by opening `/proc/self/fd/<n>` with
          `O_NONBLOCK`. That is a new open file description on the same pipe, so its
          flag is independent. A `dup` would share the original description's flags.
          The private descriptor is opened once and is not inheritable.
        - **`/dev/null` on stderr:** diagnostics are skipped.
      - **Writing and dropping.** Each line is one write of at most `PIPE_BUF` bytes.
        `autonomy run` may wait up to 1 s for the descriptor to poll writable before
        it tries, but the write itself never blocks. A non-blocking pipe write of that
        size is all or nothing (`EAGAIN`). A line is dropped if its write fails (for
        example `EPIPE` once no reader remains), returns `EAGAIN` or is written short,
        and also if the private open fails. After a drop, nothing more is written on
        that descriptor, so a short line is never followed by another.
      - **Recording.** A dropped report line is recorded as `report-unwritten` in
        `events.jsonl`, once that file exists. The run goes on to its disposition and
        its exit code either way, because the run directory is the record.
      - **Never the actor's channel.** Step 2 refuses a report fd that is fd 0, 1 or 2,
        that is closed, or whose `fstat` `(st_dev, st_ino)` equals that of fd 0, 1 or
        2, such as `3>&2`. A duplicate of the actor's channel would carry the lines
        where the actor can read and forge them.
      - **On failure.** A refusal at step 2 writes nothing on the report fd. A run that
        closes at any later step, including one that never starts the actor, still
        writes the closing line after its `disposition.json`. If the orchestrator dies,
        the fd reaches EOF with no closing line, and the run is closed with `run close`
        (§3 *Orphans*).
      - **Without `--report-fd`,** a program has only the exit code.
    - **What the channel cannot do.** It grants nothing. The tier, the sandbox spec and
      the handle are fixed before the actor starts, and no byte on stdin widens them.
      It is not a control channel for the run.
      - **Stopping.** A caller stops a run with `run stop` or a SIGTERM to the
        `autonomy run` pid, which is the same path (§8). It then waits for
        `autonomy run` to exit. It escalates only past a deadline of its own, no
        shorter than the seal timeout plus 20 s (50 s by default), which covers the route's close, the seal
        and the actor's grace. The closing check reads chains and has no fixed bound,
        so a caller that escalates before the exit may leave a run for `run close`.
      - **A harder stop.** A stop of the caller's scope (cgroup) delivers SIGTERM to the
        endpoint too, and the endpoint seals on it (decision 5). It also reaches the
        outer `bwrap`, so the actor may die before the seal completes. No act is lost,
        but §8's "seal before kill" holds only for signals to the orchestrator. A
        signal to the caller's process group reaches only the orchestrator. If the group is
        SIGKILLed, the endpoint sees EOF on its control socket and seals. A SIGKILL
        before the close finishes leaves a run that `run close` settles, and until then
        a new run on its corpus is refused `orphaned-run` (§3 *Orphans*).
      - **stdin and reading.** Closing stdin closes the run only when the actor exits on
        EOF, as pi does. A caller that stops reading stalls the actor but not the run,
        and the wall-clock bound still closes it.
    - **What stays the caller's obligation.** A stream socket can carry descriptors
      (`SCM_RIGHTS`). A caller that sends one grants the actor whatever it reaches,
      outside the sandbox spec. The envelope cannot see such a grant, and a caller must
      never send one. Nor may a caller pass the peer end of the actor's own socketpair
      as the report fd. Step 2 cannot tell it apart, and the report would then flow to
      the actor. Nor may a caller give the actor a credential of its own: a key in the
      actor's argv or in a file under scratch, or a template that holds one. The
      envelope keeps the route's credential out of the actor, and it cannot see a copy
      the caller hands over (decision 13). These join the same-uid obligations of §7.
    - **Harness state stays in scratch.** pi needs a writable agent directory, a
      `HOME`, a session directory, and the worktree as its working directory. The actor
      argv places these under scratch, for example with a wrapper that copies a
      read-only bound template and changes directory before it execs pi. The probe's
      separate read-write bind of the agent directory and its working directory apart
      from scratch are not added to the sandbox spec, so the actor still writes only
      scratch. The template is a curated directory, never the host's live pi agent
      directory, and it holds no credential. Its harness configuration points at the
      model route's URL with a placeholder key (decision 13), so what outlives the run
      in scratch can reach nothing. Scratch's lifetime is autonomy-9e8a43's. Whether a
      development mode needs binds beyond scratch, such as git metadata, is
      autonomy-d5c1cb's question.
13. **The actor's only network path is the model route, and the credential stays with
    the proxy.** An actor that calls a model needs the model API and nothing else on the
    network. No actor sandbox shares the host's network namespace, so the actor has
    loopback only. A run given a **model route** also gets a listener on that loopback.
    A **model proxy** outside the sandbox serves the listener. It permits only the
    route's operations and adds the provider credential upstream. The actor never holds
    the credential, and nothing it configures widens what the proxy forwards.

    The provider is a destination of its own. Its API can be asked to reach other hosts
    for the caller: an MCP server URL, a server tool such as web fetch or search, a
    container, or a URL given as an image or document source. A request that asks the
    provider to reach somewhere would carry the actor's traffic to any host. So the
    route bounds the request's body and its feature headers, not only its path.

    - **The route** is operator configuration, a file at
      `<config>/routes/<name>.toml`, where `<config>` defaults to
      `$XDG_CONFIG_HOME/verifiably-autonomy`. `autonomy run --model-route <name>`
      selects it, as the tier is selected (§11). It names:
      - `api`: the dialect the proxy checks bodies in. This amendment defines one,
        `anthropic-messages`, the Messages API that pi uses. A route naming any other
        dialect is refused. Each dialect fixes where in a body a provider feature can
        sit, so that every such position is checked against a closed list. A new
        provider shape needs a new dialect, written and reviewed like this one.
      - `upstream`: one `https` origin. The proxy verifies the upstream's certificate
        against the system trust store, or against the route's `ca_file` when it has
        one, and never disables verification.
      - `operations`: each names
        - a method, an exact path, and the exact query strings allowed (pi sends
          `POST /v1/messages?beta=true`);
        - `models`, the values allowed in the body's `model` field;
        - `fields`, the closed set of top-level body fields allowed. A route that
          lists none of `mcp_servers` and `container` refuses both;
        - `tool_types`, the values allowed for `type` in each element of the body's
          `tools`. An element without `type` is a client tool, which the actor's
          own process runs. Every server tool has a `type`, so it is refused unless
          listed;
        - `block_types`, the content block types allowed, and `source_types`, the
          source types allowed in a block's `source`. pi needs `text`, `image`,
          `tool_use`, `tool_result`, `thinking` and `redacted_thinking`, and `base64`.
          A `url` source, which the provider would fetch, and a `file` source, which
          names the organization's stored files, are refused unless listed.

        A route with no operation, or an operation with no model, no fields or no
        block types, is refused.
      - `forward_headers`: the exact header names that cross the proxy toward the
        upstream. Header names are compared ASCII case-insensitively everywhere: in
        forwarding, in the always-dropped set, in repeat detection and in
        `header_tokens`. Every other request header is dropped, never refused.
        `header_tokens` names, for a forwarded header that switches provider
        features, the tokens its comma-separated value may hold. The dialect marks
        which headers switch features: for `anthropic-messages`, `anthropic-beta` and
        `anthropic-version`, which selects the body's shape that the dialect's
        positions assume (pi sends `2023-06-01`). A
        route that forwards such a header without listing its tokens is refused. Some
        headers are dropped whatever the list says, and a route that lists one is
        refused:
        - `host`, `forwarded` and every `x-forwarded-*` header;
        - the credential headers `x-api-key`, `authorization` and
          `proxy-authorization`, and `cookie` and `set-cookie`;
        - the framing and hop-by-hop headers `content-length`, `transfer-encoding`,
          `connection` and every header it names, `keep-alive`, `te`, `trailer`,
          `upgrade` and `expect`.

        Response headers return to the actor, the confined side, as the upstream sent
        them, less the same set. A retry hint such as `retry-after` reaches the
        harness.
      - `credential`: an absolute path to a file and the header the proxy sends it in
        (`x-api-key`, or `authorization` with the `Bearer` scheme). The file must be a
        regular file owned by the user, not a symlink, with one link (`st_nlink` 1, so
        no second name for it sits in a bound directory) and no group or other
        permission bits. Its content must be one line of visible ASCII. A credential
        that must be refreshed, such as an OAuth login, is not a route credential. The
        route records no secret.
      - `max_request_bytes`: the largest request body forwarded.

      The route's real path, its directory `<config>`, and the credential file's real
      path join the denied set (§7). The static check and the probe therefore hold
      them out of every actor sandbox, and a toolchain bind that would expose one is
      refused. The orchestrator reads the route once, at step 2, and digests those
      bytes into `baseline.json`. It passes the same bytes to the proxy over the
      control socket, so the route that is enforced is the one recorded. The proxy
      never reads `<config>`.

      Whether a provider feature reaches outside hosts is the operator's judgement
      when writing a route. The dialect's closed lists, checked at their own positions,
      make a new provider feature unavailable until a route names it.
    - **The listener** is a TCP socket on `127.0.0.1:4780` inside the actor's own
      network namespace. The orchestrator makes it before it releases the gate (§3 step
      9), with a single-threaded helper. The helper opens the namespace through the
      actor's init pid, held by its pidfd (§8), and confirms the pidfd is still alive
      after the open. It joins the user namespace that owns that network namespace,
      found with `NS_GET_USERNS`, not the init's own. bwrap nests a second user namespace
      inside the one that owns the network. Then it joins the network namespace, binds
      and listens, and passes the socket back over `SCM_RIGHTS`. The orchestrator hands
      the socket to the proxy and closes its own copy, so the listener lives only as
      long as the proxy does.
      - **Only the actor reaches it.** A loopback address is private to its network
        namespace, so a host process reaches the listener only by joining the actor's
        namespaces. That is the same-uid position §7 leaves to row 4. No token is
        needed.
      - **The actor is given** `VERIFIABLY_MODEL_URL=http://127.0.0.1:4780`. Without a
        route, the variable is absent and nothing listens.
    - **The proxy** forwards one request at a time per connection, and any number of
      connections. Every process in the actor's namespace shares it, children
      included. For each request it:
      1. parses strict HTTP/1.1. A request body must come with `Content-Length`. The
         proxy refuses `Transfer-Encoding` on a request, `CONNECT`, an absolute-form or
         authority-form target, an `Upgrade` header, and a body over
         `max_request_bytes`;
      2. matches the method, the path and the query exactly against the route's
         operations. A path is compared byte for byte, with no decoding and no
         normalization, so `..`, `%2e` and `//` match nothing;
      3. refuses a request that repeats any forwarded header, and checks each
         `header_tokens` header token by token, with optional whitespace trimmed;
      4. parses the body as strict JSON: UTF-8 with no byte-order mark, one object,
         no duplicate key at any depth, and no `NaN` or `Infinity`. A body that fails
         is `request-malformed`, so the proxy and the upstream cannot read different
         values from the same bytes. Then it checks the body against the operation,
         at the positions `anthropic-messages` defines:
         - `model` is an allowed string, and every top-level field is in `fields`;
         - every `tools` element has no `type` or an allowed one;
         - the `type` of every block in `system` and in each message's `content`,
           and of every block in a `tool_result`'s `content`, is in `block_types`;
         - the `type` of every block's `source` is in `source_types`;
         - the check recurses into every block list nested in a checked block or
           source, such as a `content` source, at any depth. A block type whose
           nested positions the dialect does not define cannot be listed: such a
           route is refused.

         A `tool_use` block's `input` and a tool's `input_schema` are the client's
         data and are not checked. It forwards the body's bytes unchanged;
      5. asks the allowance (*the allowance join* below);
      6. opens a new upstream connection to the route's origin and frames the request
         itself: the method, path and query; `Host` set to the upstream; the forwarded
         headers; the credential header; and its own `Content-Length` for the bytes it
         sends. It streams the response back as it arrives, with no buffering beyond
         one read, in framing of its own. It never follows a redirect: a `3xx` returns
         to the actor like any other status. A connection per request costs a TLS
         handshake per model turn and is kept for its simplicity. Reuse after a
         complete response would be safe too, because the proxy frames both ways.

      A refusal is answered `403` with a JSON body
      `{"type": "error", "error": {"type": "egress_refused", "code": "<code>",
      "message": "<one line>"}}`. The codes are `request-malformed`,
      `target-refused`, `operation-refused`, `header-refused`, `model-refused`,
      `body-refused`, `request-too-large`, `route-closed` and, once an allowance
      exists, `allowance-refused`. The message names what was refused and, for
      `operation-refused`, the route's operations, so an actor can correct itself. The
      host's network stays out of reach either way.
    - **The proxy is sandboxed too.** It parses what the actor sends, and it holds the
      credential and the host's network. Its argv comes from a fixed builder in
      `egress`, not from a `SandboxSpec`: `bwrap --unshare-all --share-net
      --new-session --clearenv --info-fd <n>`, the only sandbox of a run that shares the
      host's network. It has no `--die-with-parent`, deliberately. A proxy that died
      with the orchestrator would write no closing line, and every orphan would report
      `egress-lost`. Instead the proxy sees EOF on its control socket and closes the
      route. The orchestrator records the init pid that `--info-fd` reports for the
      proxy's namespace, holds a pidfd on it, and kills through that pidfd, as for the
      actor (§8). Killing a namespace's init kills the proxy inside it. It binds `/usr`, `/etc`, its interpreter
      and package read-only, the credential file read-only at `/run/va/credential`, the
      route's `ca_file` read-only when it has one, and the real path of
      `/etc/resolv.conf` read-only when it lies outside `/etc`, as under
      systemd-resolved's stub. Nothing else is bound. It holds
      no run directory, no scratch and no corpus.
      - **Its static check** runs at step 7, beside the actor's. Its binds are checked
        against the denied set, with the credential file and the `ca_file` exempt as
        exact paths, so their own binds pass under a denied ancestor such as `<config>`.
        A failure is `egress-unproven`.
      - **Its descriptors:** stdin is `/dev/null`, and stdout and stderr go to
        `<run dir>/proxy.log`. It writes its records on a descriptor the orchestrator
        opened `O_APPEND` on `<run dir>/egress.jsonl`. It talks to the orchestrator over
        a control socketpair. It runs in a session of its own, like the endpoint
        (decision 5). The helper also gets stdin from `/dev/null`, and its output is
        captured (decision 12).
      - **What stays exposed.** The host's network namespace includes its abstract
        `AF_UNIX` sockets, such as a desktop session's bus. A parser bug that the actor
        triggers in the proxy could reach them. A seccomp filter that allows the proxy
        only `AF_INET` and `AF_INET6` sockets would close that. It is not required
        here, and the plan may add it.
    - **Access belongs to one run, and it ends.** Each run has its own proxy and
      listener, so no run reaches another's. The proxy holds the lease (§8). It
      closes the route on `close` from the orchestrator, on lease expiry, on EOF of
      its control socket, or on SIGTERM. Closing stops accepting, closes the listener,
      cuts every upstream stream in flight, writes the closing records, and exits. A
      request after that finds nothing listening (`ECONNREFUSED`).
    - **Missing enforcement fails closed.** Without a route, the actor has no network
      at all. A route that is unknown or invalid, or whose credential file fails its
      checks, refuses the run at step 2. A proxy that cannot start, cannot read a
      credential of one line of visible ASCII, cannot confirm `ready`, or cannot take
      the listener makes the run `unwired`
      (`egress-unproven`) before the gate is released, and the actor never runs. A
      proxy that dies leaves no listener, because the orchestrator holds no copy. The
      actor's next request is refused by the kernel, and the run closes
      (`egress-lost`). There is no fallback path to the network.
    - **Configuration directs, and the boundary enforces.** The caller points its
      harness at `VERIFIABLY_MODEL_URL` with a placeholder key. For pi, that is a
      provider `baseUrl` in the attempt's `models.json`, which crew writes
      (crew-799319). That file sits in scratch, and the actor may rewrite it. Nothing
      depends on it:
      - a request to any other host fails with `ENETUNREACH`, or with a refused DNS
        lookup;
      - a proxy setting (`HTTPS_PROXY`) makes the harness send `CONNECT`, which is
        refused `target-refused`;
      - another path, query or model is refused by the route;
      - a body or a beta token that asks the provider to fetch, search, run a
        container or connect to an MCP server is refused, unless the route names it;
      - a real-looking key is stripped, and the route's credential is sent in its
        place.

      A placeholder's shape can still steer the harness's own behaviour. pi treats a
      key containing `sk-ant-oat` as an OAuth token and changes its headers. That
      lies within the operations the route permits.
    - **The credential is outside the actor.** It is not in scratch, the environment,
      bwrap's argv, any bound file, or the actor's process. The proxy reads it once,
      at start, from its own bind. The orchestrator checks the file's kind, owner and
      mode at step 2 with `fstat`, and never reads its bytes. The proxy is outside the
      actor's PID and user namespaces, so the actor can neither see it in `/proc` nor
      ptrace it. No record carries the credential: not `egress.jsonl`, `proxy.log`,
      `events.jsonl` or `baseline.json`.
    - **What the proxy records.** One line in `egress.jsonl` per request:
      `{at, seq, method, path, query, model, status, refused, upstream_request_id,
      request_bytes, response_bytes, ended}`, written when the request ends. `at` is
      when the proxy received the request, and `seq` counts requests in the order
      received. `refused` is the code or null, and
      `ended` is `complete`, `actor-closed`, `route-closed` or `upstream-error`. No
      body and no header value is recorded. When the proxy closes the route, its last
      line is `{at, closed, last_seq}`: the cause (`close`, `lease`, `eof` or `term`)
      and the last request it accepted before it stopped accepting. It also reports
      these on its control socket. A proxy that exits without that line died,
      and the run reports `egress-lost`.
    - **Commands the endpoint runs.** The endpoint runs on the host's network, and it
      runs commands the actor asks for. A command reachable under a run session does
      no network I/O on the actor's behalf. A command that would must be refused at
      dispatch, as decision 11 refuses one that cannot confine its paths. No `science`
      command fetches anything today, and the kernel's confined jobs run with
      `--unshare-all` and probe for `ENETUNREACH`.
    - **Revoking a running run.** The proxy holds the route's bytes and the credential
      from its start. Editing or deleting the route or the credential file affects only
      later runs. A running run's access ends with `run stop`. Revoking the key at the
      provider ends every run's access at once.
    - **The allowance join.** The proxy is the one path by which any process of the
      run reaches a model. It therefore has two points where autonomy-9e8a43's
      allowance attaches, and this amendment defines them without implementing either:
      - **`admit`**, at step 5 above, before any byte goes upstream. It receives the
        run, the operation, the model, the request size and the requests in flight,
        and returns allow or a refusal code.
      - **`settle`**, when the response stream ends, however it ended. It receives
        the request's `seq`, the upstream request id, and the usage the upstream
        reported in the stream, if it reported any.

      Until an allowance exists, `admit` allows every request the route permits, and
      `settle` does nothing beyond the record line. A run configured with an allowance
      whose check is unavailable will be refused at open, never run unmetered.

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
     disposition (`orphaned-run`, §3 *Orphans*);
   - fd 0, 1 or 2 is not an anonymous pipe, a connected `AF_UNIX` stream socket or
     `/dev/null`, or the `--report-fd` descriptor is closed, is fd 0, 1 or 2, is the
     same file as one of them, or is not an anonymous pipe or a connected `AF_UNIX`
     stream socket (`stdio-refused`, decision 12);
   - `--model-route` names no file under `<config>/routes/` (`route-unknown`), the file
     breaks a rule of decision 13 (`route-invalid`), or its credential file is missing,
     a symlink, not a regular file, not the user's, has more than one link, or has any
     group or other permission bit (`credential-unavailable`).

   Once these pass, write the first line on the report fd (decision 12).
3. **Capture the baseline heads** with `science heads --resolve`. This is a
   recovery-resolving read: it settles any work a crashed writer left pending. It
   reads the world head, every mounted corpus's head (genesis and tip), and the store
   root's head.
   - A chain still pending after resolution is `unwired` (`baseline-pending`).
   - An unavailable read is `unwired` (`baseline-unavailable`).

   Write `baseline.json` (§6), fsync it, then fsync its directory.
4. **Launch the endpoint** as `science serve --run <launch.json>`, a child process.
   It runs in its own session. Its stdin is `/dev/null`, and its stdout and stderr go
   to `<run dir>/endpoint.log` (decision 5, decision 12).
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
   `unwired` (`sandbox-unproven`). With a model route, also check the proxy's binds
   (decision 13); a failure there is `unwired` (`egress-unproven`).
8. **Append to `events.jsonl`** as each step completes: the session id, the ledger
   path, the opening basis, the pids (each with its start time), and the probe
   result.
9. **Start the actor** from the orchestrator's main thread, under the sandbox, with
   `--info-fd` to learn the namespace's init pid. The outer `bwrap` starts in a process
   group of its own, so a Ctrl-C at the caller's terminal cannot kill the actor before
   the seal. `--die-with-parent` follows the spawning thread, not the group. The actor
   inherits `autonomy run`'s fds 0, 1 and 2, and the gate releases it on its own fd
   (§7). A run with a model route does more before the release (decision 13):
   - it starts the proxy in its own sandbox, records the init pid that `--info-fd`
     reports for the proxy's namespace, with its start time, in `events.jsonl`, and
     passes the proxy the route's bytes. The proxy reads its credential
     and reports `ready` on its control socket within the start timeout;
   - once the pidfd is held, it makes the listener in the actor's network namespace
     with the helper and passes it to the proxy, which confirms `listening`.

   Any failure here kills the actor's namespace through the pidfd and the proxy, before
   the release, and the run closes `unwired` (`egress-unproven`). Then replace the
   orchestrator's own fds 0 and 1 with `/dev/null` and its fd 2 with
   `<run dir>/orchestrator.log`, and close the private non-blocking stderr descriptor
   with them (decision 12). Start the heartbeat.

**During.** The actor reaches the world only through the handle (§7). The caller may
exchange bytes with it over stdio, which grants nothing (decision 12). The orchestrator
renews the lease every lease/3.

**Close.** Any one of these triggers the close:

- the actor exits;
- `autonomy run stop <run-id>`, or SIGTERM, SIGINT or SIGHUP to `autonomy run`;
- the endpoint seals or exits on its own, seen as a refused renewal or through its
  pidfd;
- the proxy exits on its own, seen through its pidfd: it closed the route on its
  lease, EOF or SIGTERM, or it died (`egress-lost`, decision 13);
- the wall-clock bound.

Then:

0. **Close the model route,** when the run has one, at the same moment as step 1's
   `seal` request, and wait on both, each within its own bound. If the proxy is still
   running, send `close` on its control socket. The proxy stops accepting, cuts the
   streams in flight, writes its closing line and exits. If it has not exited within
   5 s, the orchestrator kills its sandbox through the pidfd
   (`egress-close-timeout`). A proxy that has already exited on its own has written its
   closing line, or it died (`egress-lost`). Neither request waits on the other, so a
   hung proxy cannot delay the seal, and no model call starts after the proxy receives
   `close`.
1. **Seal.** Send `seal` on the control socket. The endpoint seals (decision 5),
   reports the sealed tips and `basis_seal`, writes `seal.json`, writes
   `session-close` and exits. An endpoint that has already sealed on its own (lease,
   EOF or SIGTERM) has written `seal.json`, and the orchestrator reads that instead
   (§8). Only when neither arrives within the seal timeout plus 5 s, or the endpoint's
   pidfd shows it exited without `seal.json`, does the orchestrator kill what remains,
   and the run closes through `seal-missing`.
2. **Kill the actor's namespace** if it is still alive (§8).
3. **Run the closing check** (§9) over the intervals from the baseline heads to the
   sealed tips.
4. **Write `disposition.json`** (§9), fsync it, write the closing line on the report
   fd (decision 12), and exit with the disposition's code: 0 `clean`, 3 `quarantined`,
   4 `unwired`.

**Orphans.** A run directory with a baseline and no disposition belongs to an
orchestrator that died.

- **What happens to the endpoint:** it sees EOF on its control socket and seals
  within one read, writing `seal.json` itself.
- **What happens to the proxy:** it sees EOF on its control socket and closes the
  route, writing its closing line. `run close` locates its namespace's init through
  `events.jsonl` (pid plus start time, opened as a pidfd), waits up to 5 s for it to
  exit, and SIGKILLs it through that pidfd after that (`egress-close-timeout`). A proxy that left no closing line is
  `egress-lost`, as in a normal close.
- **Closing it:** `autonomy run close <run-id>` waits until the endpoint can no
  longer write before it reads any chain:
  1. It locates the endpoint through `events.jsonl` (pid plus start time, opened as a
     pidfd).
  2. If the endpoint is alive, it waits for `seal.json`, for at most the seal timeout
     plus 5 s.
  3. Once `seal.json` exists, it waits on the pidfd for the endpoint to exit by
     itself, for at most 5 s, because the endpoint writes `session-close` after
     `seal.json`. It SIGKILLs only on a timeout, or when `seal.json` never came, and
     then waits for the exit.

  Only then does it run the closing check. The disposition is at least `unwired`
  (`orchestrator-lost`), and a `quarantined` finding still takes precedence.
- **No `seal.json`:** if the endpoint died too, nothing marks where the run's writes
  ended. A commit that became durable just before the death, with no `act` line yet,
  is exactly the effect that needs investigating. So the tail is never dropped:
  - Each interval ends at the **closing head**, read after the endpoint is confirmed
    dead, and every entry in it is classified by §9's rules. The run's one crash
    transaction comes out `outcome-unknown` (§9 *Transactions and the crash
    allowance*), and anything else unexplained comes out `entry-foreign`.
  - The one exception needs independent boundary evidence: another session's ledger.
    Ledgers are read from `<operations root>/sessions/`, on the host side.
    1. **Find the boundary.** It is the first entry in the tail that carries
       verified later-session evidence, with no run-actor entry after it in the
       chain. That evidence is either of these:
       - an `act` line in a later session's ledger names the entry;
       - the entry is an intent whose decoded actor is a later session's
         `session:<id>`.

       A session whose only acts failed, or that failed before its first commit,
       therefore still establishes the boundary through its intents. Settlements
       carry no actor, so a settlement is never a run-actor entry for this test.
    2. **Mark `after-run`.** From the boundary on, these entries are `after-run`,
       reported and not classified, because they were written once the run's claim
       was gone:
       - an entry that a later session's `act` line names;
       - a settlement whose registration is `after-run`;
       - an intent whose decoded actor is a later session's `session:<id>`, with no
         registration. This is a failed or refused act of that session.

       A later session is one whose ledger is present and whose `session-open`
       exists.
    3. **Classify the rest.** Everything from the boundary on that none of these
       covers, and any run-actor entry after it, is still classified.
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
| `egress` | the model route (parsing, step 2's route checks), the namespace helper that makes the listener, and the model proxy with its records, lease and close (decision 13) | `bwrap`, the upstream's TLS |
| `run` | the supervisor of §3 | all |
| `cli` | `autonomy run` (with `--model-route`), `run stop`, `run close`, `run show` | `run` |

**`science`**, filed from the plan, needs:

- `serve --run <launch file>`;
- the token and peer-namespace check (§7);
- the control socket (lease, seal, reports, `seal.json`), and the endpoint's own
  execution subtree, killed at the seal;
- the `run-sealed` refusal mapping;
- the dispatch refusal of decision 11, which also refuses any command that would do
  network I/O for the actor (decision 13);
- `mcp bridge`, a client-only bridge to a handle;
- **handle mode for the CLI.** Today the CLI runs read-only commands in-process from
  host configuration, and finds the write socket through that same configuration.
  When `VERIFIABLY_ENDPOINT` is set, every declared command, reads and writes alike,
  goes through the handle with the token from `VERIFIABLY_TOKEN_FILE`, and no host
  configuration is loaded. The framework verbs (`mcp`, `adapters`, `build`, `serve`,
  `epoch`) cannot run through a handle, so in handle mode they are refused
  `handle-mode`. The exception is `mcp bridge`, which exists for this mode. Two cases are refused `handle-incomplete`: a handle given
  together with `--config`, and one variable set without the other. There is no
  fallback to local execution;
- the descriptor-based path confinement and the private capture of decision 11;
- `heads [--resolve]` and `log` (§10);
- the basis computation.

**`beliefs`**, filed from the plan, needs:

- `open_run_session(…, ceiling: WritePermit)`, deserializing the permit;
- the cross-process claim on each written chain, taken by every session constructor;
- `WriterSession.seal()`;
- a detached read of the entries after a tip;
- the belief-policy and contract identities the basis reads;
- the confinement denied-set extension that decision 11 names. It denies the
  envelope's denied set to the confined job, with one exception: the kernel's own
  per-invocation staging, `<operations root>/scratch/<invocation>`, which the kernel
  binds for that job itself. The capture copy is never bound;
- a fix to `reconcile`'s act matching, by `corpus` today, so that store-root acts
  verify (§9);
- an `act` line for every store-chain registration a holdings act appends
  (`store_write`, `store_move`, `store_delete`). The line carries:
  - `entry`: the registration. It is resolved by the transaction's `txid`, through a
    read-back inside the same lock hold, because the store outcome returns no
    registration digest and its null `fulfills` rules out the usual lookup;
  - `intent`: the holdings act's intent; for a move, the move-source intent;
  - `records`: empty. Without it, every holdings write would be an unledgered registration in a
  written chain.

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
    "sandbox": {"binds": [], "stdio": ["pipe", "socket", "pipe"]},
    "egress": {"route": "anthropic", "digest": "<64 hex>",
               "upstream": "https://api.anthropic.com",
               "url": "http://127.0.0.1:4780"},
    "lease": {"seconds": 60}
  }
  ```

- **`events.jsonl`** is append-only and fsynced line by line. It holds the facts that
  exist only after step 3: the session id, the ledger path, the opening basis, pids
  with their start times (the proxy's included), the probe result, the proxy's
  `ready` and `listening`, the close's start with its trigger, the route's close with
  its cause, the seal request, and actor start and exit.
- **`seal.json`** is written once, by the endpoint, atomically (a temporary file,
  fsync, rename), and read by the orchestrator or `run close` only after the endpoint
  has stopped writing or has reported its seal: the sealed tips, the closing basis
  and the seal cause (`stop`, `lease`, `eof`, `term`). A `seal-timeout` writes no `seal.json`:
  the orchestrator records it in `events.jsonl`, and the closing check reads it
  there.
- **`disposition.json`** is written once, by the closing check (§9).
- **`egress.jsonl`** holds the proxy's line per request (decision 13). It is appended
  through the descriptor the orchestrator opened, and it is a record of what the actor
  asked for, not evidence the closing check reads.
- **`orchestrator.log`**, **`endpoint.log`** and **`proxy.log`** hold diagnostics: the
  orchestrator's stderr from step 9 on, the endpoint's stdout and stderr (decision 12),
  and the proxy's. They are appended, not evidence, and never read by the closing
  check.

`baseline.json`'s `sandbox.stdio` lists the kinds step 2 found on fds 0, 1 and 2, each
`pipe`, `socket` or `null` (decision 12). Its `egress` names the route, the SHA-256 of
the route file's bytes as read at step 2, the upstream and the URL given to the actor,
or is `null` for a run without a route. It never holds the credential or its path.

The launch file lives in the run directory with mode 0600. It holds the path of the
token file, never the token.

None of the records is ever rewritten. Together they are the baseline record that governing
§7.1 places outside any corpus the actor can write: the sandbox never binds the run
directory.

## 7. Sandbox and endpoint handle

**The sandbox spec** is data. It names:

- the read-only system binds (`/usr`, `/etc`, and the `/bin`, `/lib`, `/lib64` and
  `/sbin` symlinks);
- the actor's own toolchain paths, each listed;
- the scratch directory, canonicalized to its real path and bound read-write there,
  so a path means the same thing inside the sandbox and to the endpoint;
- the endpoint socket, at the fixed path `/run/va/endpoint.sock`;
- the token file, bound read-only at `/run/va/token`. Its host copy is mode 0600 in
  the host-side socket directory under `$XDG_RUNTIME_DIR/va/`, never in the run
  directory;
- the environment.

No sandbox spec shares the host's network namespace. The actor's network is its own
loopback, and its only path out is the model route's listener (decision 13). Plan A's
`network` field and its `host` value are removed.

**The argv** is `bwrap --unshare-all --die-with-parent --new-session
--clearenv --proc /proc --dev /dev --tmpfs /tmp --info-fd <n>`, followed by the
binds, then `--setenv` for non-secret variables only, then the gate and the actor argv.

**The gate** is a short program that bwrap runs in front of the actor, under
`/usr/bin/python3 -I`, which the probe already requires. It reads one line from a
dedicated pipe, which the launch passes to bwrap as an extra fd and names in the gate's
argv. It closes that fd, and then it execs the actor only if the line is `run`. EOF
exits 125 without running the actor.
- **Why not a shell:** the pipe's number is whatever the orchestrator's open
  descriptors leave free, often above 9. Dash, a common `/usr/bin/sh`, rejects a
  multi-digit fd in a redirection (`Bad fd number`).
- **Inheritance:** the gate's own descriptors are not inheritable (PEP 446), so the
  actor receives only fds 0, 1 and 2.
 The orchestrator writes `run` only after it
holds a pidfd on the namespace's init (§8). The gate never touches stdin, so the release
cannot come from the caller, and the caller's bytes are never consumed before the actor
reads them. Plan A's gate was a shell that took the release on stdin and reopened stdin
on `/dev/null`. Decision 12 replaces it. The launch takes the actor's three descriptors explicitly and
refuses a closed one, so a library caller never passes a stray descriptor.

**What the actor is given:** `VERIFIABLY_ENDPOINT=/run/va/endpoint.sock`,
`VERIFIABLY_TOKEN_FILE=/run/va/token`, and `VERIFIABLY_SCRATCH`, the scratch path,
which is also the working directory. A run with a model route also gives
`VERIFIABLY_MODEL_URL` (decision 13). Its fds 0, 1 and 2 are `autonomy run`'s, and it
holds no other descriptor (decision 12). The token never appears in an argv, the
environment, the baseline, a log, or any command's output.

**The denied set** is computed from the world configuration, never from the spec:

- the world root and every corpus root;
- the store root;
- the operations root;
- `<state>`, which holds every run directory;
- `<config>`, which holds the routes, and the real path of each route's credential
  file (decision 13).

The host-side socket directory holds only the socket and the token file. It must lie
outside the denied set. The static check verifies that, as for every bind, and a
configuration that puts a denied root under `$XDG_RUNTIME_DIR` fails closed at step 7.

**The static check** refuses a bind whose source's real path, or whose
`(st_dev, st_ino)` chain, is an ancestor or descendant of any denied path. A bind of
`/` is refused by the same rule.

**The probe** runs `/usr/bin/python3 -I` in the identical spec, from the bound
`/usr`, because a shell cannot report which errno `stat` failed with. For each denied
path, given as an argument by its real path, it reports `stat`'s errno, and every one
must be `ENOENT`. It also connects TCP sockets to `192.0.2.1:443` and
`[2001:db8::1]:443`, documentation addresses, and must get `ENETUNREACH` from both.

**The handle** is the socket plus the token.

- **What the endpoint accepts:** a connection whose `SO_PEERCRED` pid lives in the
  actor's PID namespace, compared by the `/proc/<pid>/ns/pid` inode against the init
  pid from `--info-fd`, and that presents the token.
- **What it refuses:** an ordinary host process that reads the token file and
  connects is refused `bad-peer`. Without that check, a stray client (a person's
  shell, another tool) would dispatch under the run's actor and pass membership.
- **What stays outside the boundary:** the host user owns the actor's namespaces. A
  same-uid process that deliberately joins the actor's PID namespace (`setns`) or
  ptraces the actor passes the peer check, and its requests are indistinguishable
  from the actor's. That, and same-uid processes that write the corpora directly, are
  row 4's obligation: the envelope bounds the actor, not the host's own user. Direct
  writes are still caught as `entry-foreign`. A caller that sends the actor a descriptor
  over a socket on its stdio is in the same position (decision 12).

**CLI:** a shell actor runs the `science` CLI as it is. The two handle variables put
the CLI in handle mode (§4): every command goes through the endpoint, and no host
configuration is read.

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
  - **The proxy holds the same lease.** The orchestrator renews it with the endpoint's,
    and the proxy keeps its own deadline. On expiry, on EOF of its control socket, or
    on SIGTERM, it closes the route (decision 13).
- **The kill switch** is `autonomy run stop <run-id>`. It locates the orchestrator
  through `events.jsonl`, by pid plus start time, opened as a pidfd so a reused pid is
  never signalled. It sends SIGTERM. The orchestrator treats SIGINT and SIGHUP the same
  way. It then:
  1. closes the model route, if the run has one, together with step 2's seal request
     (§3 *Close* step 0);
  2. seals the endpoint and waits for its sealed-tips report, for at most the seal
     timeout plus 5 s. An endpoint that has already sealed on its own (lease, EOF or
     SIGTERM) has written `seal.json`, and the orchestrator reads that instead. If
     neither arrives, it kills the endpoint and the run closes through
     `seal-missing`;
  3. kills the actor. A pidfd is opened on the namespace's init pid as soon as
     `--info-fd` reports it, so a reused pid is never signalled. SIGTERM goes first,
     then SIGKILL after a 10 s grace. bwrap's PID 1 need not forward SIGTERM, so
     SIGKILL is the path that is relied on: killing PID 1 of the namespace kills
     every process in it. The grace is a courtesy to an actor that handles SIGTERM;
  4. closes normally.

  If the orchestrator is already gone, `stop` reports that and directs the operator to
  `run close`. The endpoint has sealed by EOF, and the proxy has closed the route by
  EOF. Route close and seal come before kill, so no model call and no act starts
  between deciding to stop and the actor's death.
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
up to and including its sealed tip. Act lines are matched to entries by digest across
all the written chains, never by the line's `corpus` field. The session writes the
write corpus's id there even for a holdings act that commits to the store root's chain.

The ledger is **incomplete** when any of these holds:

- it has a torn tail or a failed append;
- it has an invocation with no `invocation-close`;
- it has no `session-close`.

Only an incomplete ledger can explain a missing `act` line. Each entry is classified as
follows. This mirrors `reconcile`'s split between `session-outcome-unknown` and
`session-entry-foreign`, with three stated divergences:

- incompleteness also counts a torn tail and a missing `session-close`, where
  `reconcile` counts only open invocations or an unreadable ledger;
- an intent that never registered is `unwired`, not foreign;
- act lines are matched by digest, not by `corpus`. `reconcile` matches by `corpus`,
  so it reports `session-act-unverified` for every store-root act. The plan files that
  disagreement in `beliefs`.

**Transactions and the crash allowance.** Every effect on a written chain is a
**transaction**: one registration and its settlement. A transaction is **recorded**
when an `act` line names its registration, and **unrecorded** otherwise.

**The act in progress.** The session runs one handler at a time, and the kernel
appends an act's intents before its transactions. So the act that a crash
interrupted is always the last one the run began:

- the last run-actor intent in the write corpus's interval, in chain order;
- plus, when that intent is a `move-destination`, its `move-source`. The kernel's
  `move` appends the two back to back, source first, and no run-actor intent
  separates them.

The payloads carry no explicit link between a move's two intents, so this structural
rule is the pairing, and `log.v1` reports each holdings intent's act kind for it.

**Owning intent.** Ownership is decided before any allowance applies, and never by
location matching across the whole interval:

- **A recorded registration:** owned by the intent its `act` line names. For a
  `store_move`, that is the move-source intent (§4).
- **An unrecorded registration with a `fulfills`:** owned by the intent it fulfils.
- **An unrecorded null-`fulfills` store registration:** owned by the holdings intent
  of the act in progress whose location is among its registered paths. For a move,
  both locations appear, and the owner is the move-source intent. If the act in
  progress is not a holdings act, or no location matches, the registration has no
  owner.

So a successful write to x followed by a failed intent for x causes no confusion: the
write's registration is recorded and owned through its `act` line, and the failed
intent owns nothing.

**The allowance.** Within an act, every transaction is followed by its `act` line
before the next transaction begins, whether that is the next phase of the same act or
the next act. So a crash can leave at most one unrecorded transaction across all the
written chains: the one in progress. It may be the first transaction of its act, or a
later phase of an act whose earlier phases are already recorded. Examples of a later
phase are a holdings publish after its store write, or a move's destination publish
after its source publish.

Under an incomplete ledger, an unrecorded registration **qualifies** for the crash
allowance when both of these hold:

- its owning intent belongs to the act in progress;
- it comes after every recorded registration on its own chain.

When exactly one registration qualifies, that one is the **crash transaction**. It,
its settlement and its owning intent, if no `act` line names that intent, are
`outcome-unknown` (`unwired`). When more than one qualifies, no crash explains them
all, so none gets the allowance. Every unledgered transaction is then
`entry-foreign`, and the run is `quarantined`. Under a complete ledger nothing
qualifies.

The limit is therefore one transaction, not one intent. Several forged store
transactions that touch the act in progress's location all qualify, and they
quarantine the run. A store transaction whose paths match no intent of the act in
progress has no owner and is `entry-foreign`. A forger can downgrade at most one transaction, only to
`unwired`, and only when the endpoint really did leave the ledger incomplete.

- **Intent entry:**
  - A member if an `act` line names it as `intent` and its decoded actor is the
    run's.
  - A run-actor intent that no `act` line names:
    - when it owns the crash transaction: `outcome-unknown` (`unwired`);
    - when it owns no registration at all: `intent-unfulfilled` (`unwired`). No
      transition landed: an execution failed after its intent, or a fulfil was
      refused `run-sealed`. A forged bare intent lands here too; it has no effect,
      and it is reported;
    - when it owns a registration that is not the crash transaction:
      `entry-foreign` (`quarantined`).
  - Any other intent is `entry-foreign`, which is `quarantined`.
- **Registration entry:**
  - A member if an `act` line names it as `entry`, that line's intent is a member,
    and either:
    - its `fulfills` is that intent; or
    - it is a store-chain registration whose `fulfills` is null. This is a holdings
      store write, ledgered under its holdings act's intent.
  - The crash transaction's registration is `outcome-unknown` (`unwired`).
  - Otherwise it is `entry-foreign`. This includes a write by a process that forged
    the run's actor string, which can be read from the run directory.
- **Settled entry:**
  - A member if its `registration` is a member registration.
  - The crash transaction's settlement is `outcome-unknown`. A chain does not record
    whether recovery or the original commit appended a settlement
    (`SettledEntryView` carries only `txid`, `registration` and `committed`), so the
    check does not distinguish the two.
  - Otherwise it is `entry-foreign`.
- **Every `act` line:** its intent and registration must appear in the interval, with
  a settlement whose `committed` is true. Otherwise it is `act-unverified`, which is
  `unwired`.
- **A member intent with no fulfilling registration** is a cut route act:
  `intent-unfulfilled`, which is `unwired`. This covers an intent with no `act` line
  naming a fulfilling registration, or with only store-write lines. A fulfilling
  registration that is the crash transaction means the act was not cut, so it does
  not count here.

**The rows:**

| condition | finding | disposition |
|---|---|---|
| baseline, events, ledger or a read is unavailable | `baseline-unavailable` / `ledger-unavailable` / `read-unavailable` | `unwired` |
| the ledger has a torn tail or an unknown line | `ledger-malformed` | `unwired` |
| no `seal.json` (endpoint died) | `seal-missing` | `unwired`; the intervals end per §3 *Orphans* |
| a baseline tip is not on its chain (the chain was rewritten) | `chain-discontinuous` | `quarantined` |
| an entry that neither the ledger nor the run's actor explains | `entry-foreign` | `quarantined` |
| the crash transaction (exactly one qualifying unledgered registration, under an incomplete ledger), its settlement, and its owning intent if unnamed | `outcome-unknown` | `unwired` |
| any other unledgered transaction, including every one when more than one qualifies, and an unnamed run-actor intent that owns one | `entry-foreign` | `quarantined` |
| a run-actor intent with no fulfilling or matched registration (no `act` line, or only store-write lines) | `intent-unfulfilled` | `unwired` |
| the endpoint could not drain the in-flight act in time | `seal-timeout` | `unwired` |
| a ledger `act` not verified in the interval | `act-unverified` | `unwired` |
| the world head moved | `world-moved` | `quarantined` |
| the basis differs between open and seal | `basis-moved` | `quarantined` |
| the ledger has no `session-close`, or has open invocations | `session-unclosed` | `unwired` |
| `session-open`'s permit differs from the tier's | `permit-mismatch` | `unwired` |
| the orchestrator was lost | `orchestrator-lost` | `unwired` |
| a read mount moved | `mount-moved` | none (reported) |
| the proxy exited without its closing line in `egress.jsonl` (decision 13) | `egress-lost` | none (reported) |
| the proxy did not exit within 5 s of `close` and was killed | `egress-close-timeout` | none (reported) |
| with no seal, tail entries that another session's ledger names, from the first such entry with no run-actor entry after it | `after-run` | none (reported) |
| none of the above | — | `clean` |

**Why a world move and a mount move differ.** The world chain moves only by the
registry, epoch and lifecycle families, which are outside every unattended tier. A
world move therefore changes the frame the run resolved names in, under it, and it is
quarantined. A read mount moves whenever its owner works, so treating that as
quarantine would make every run on a shared world fail. The run's own records cite
what they read by digest, so a later mount change cannot alter what they say. The
move is reported.

**Why the egress findings are reported, not dispositions.** The proxy grants no write
and holds no chain. A proxy that died, or had to be killed, leaves the actor with less
reach, never more, and the closing check verifies the run's writes whatever the actor
could call. Whether a run cut off from its model did useful work is the caller's
judgement.

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
  read, in chain order. Its header names the chain: whether it is a corpus or the
  store, its id (the corpus id, or the store root's identity), its root, and its
  genesis digest. Each entry carries what §9's rules read:
  - its digest and entry type;
  - for an intent: the decoded kind and actor. For a holdings intent, also its act
    kind (`write`, `delete`, `move-source`, `move-destination`, `re-check`), its
    `location` (the store-relative path), and the store identity it targets;
  - for a registration: `fulfills` (possibly null), the consumer tag, the
    transaction id, and the registered paths, meaning each path's `initial` and
    `final` state from the transaction;
  - for a settlement: `registration` and `committed`.

  The fields are a versioned output contract (`log.v1`). autonomy's `science_reads`
  parses that contract strictly. A missing field is `read-unavailable`, and the check
  never guesses.

  A tip that is not on the chain is refused `tip-unknown`, which is how
  `chain-discontinuous` is detected. The output budget pages through a cursor as
  usual.

The basis is not a command. The endpoint computes and reports it itself (decision 6).

**Harness neutrality** follows from the shape of the run: the actor is an argv, the
handle is two environment variables, the actor's stdio is the caller's (decision 12),
the MCP bridge is optional, and the model route is a base URL (decision 13). pi,
Claude Code and a shell script run identically under `autonomy run`. Anything specific
to a harness belongs to the caller and never enters the envelope: a pi configuration
naming the bridge or the model URL with a placeholder key, or a protocol spoken over
stdio, such as pi's RPC. The model credential belongs to neither the caller nor the
actor. It is the operator's, named by the model route and held by the proxy.

## 11. A tier as an authorization

The companion authorization model (autonomy-1aac03) describes a grant by the parts
below. A tier fills each of them as follows:

| part of a grant | where it lives |
|---|---|
| identity | the run's actor `session:<id>` |
| operation and resource | the permit (kinds, routes, families) over the written chains; the model route's operations and models |
| scope | the claims, the sandbox's denied set, path-input confinement, a network namespace whose only way out is the model route's listener |
| lifetime | the lease, which the endpoint and the proxy both hold, and the orchestrator's wall-clock bound |
| revocation | `run stop`, which closes the model route and seals; editing the route or its credential affects only later runs (decision 13) |
| approval | the person or orchestrator that ran `autonomy run` with that tier and model route; the model route itself is the operator's configuration; `publishes` is never approvable unattended |
| audit receipt | the run directory (`egress.jsonl` included) and the ledger |
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
| E11 *(pending)* | an orphan closes `unwired` with `orchestrator-lost`; a new run on its corpus is refused until then; `run close` reads no chain while the endpoint can still write | SIGKILL the orchestrator; `run` refuses `orphaned-run`; `run close` while an act is held inside the seal timeout, and again past it | a normally closed run allows the next; a `run close` that skips the endpoint wait finalizes before the held act's entries land; a `run close` that kills as soon as `seal.json` appears leaves no `session-close` |
| E12 *(pending)* | world, basis and baseline races are seen | move the world head; change a pack binding between open and seal; write between steps 3 and 5 | an untouched run is `clean` |
| E13 *(pending, science)* | a host process holding the token is refused `bad-peer`; a request without the token is refused | endpoint test | the actor's own request dispatches |
| E14 *(pending, science)* | a path input outside scratch, relative, or through a symlink is refused `path-outside-run`; a swap after the check cannot redirect a read; a captured directory is immune to later changes | `run` with `code` naming a host directory; a relative path; a symlink in scratch pointing out; a race harness that swaps a checked file, then a checked subdirectory, for a symlink to a host file between validation and open (looped); a capture followed by a swap, then execution | `code` as a directory in scratch with a bundle-relative `entrypoint` executes, and a host file never appears in the bundle or the record; a resolve-by-path variant (test hook) loses the race harness |
| E15 *(pending, beliefs)* | a second session on a claimed chain is refused, across processes | kernel test | sequential sessions both open |
| E16 *(pending, beliefs, science)* | `seal()` refuses the next act; the sealed tip includes a drained scoped act; a route act held between intent and fulfil is cut (`intent-unfulfilled`) and its job killed; a held act past the seal timeout gives `seal-timeout` | kernel and endpoint tests with a scoped act held across the seal (released inside and past the timeout), a `run` act held mid-execution, and a holdings act sealed between its store write and its publish, and an endpoint killed between a store commit and its `act` line | an unsealed session's next act lands; the kill case is `unwired` (`outcome-unknown`), and without the store clause it is `quarantined`; without store-write `act` lines, a clean holdings run is `quarantined`; a seal that reads tips without draining leaves the scoped act after the sealed tip (`act-unverified`); without the subtree kill, the job outlives the endpoint |
| E17 | a forged run actor with a complete ledger is `quarantined`; a crash's intent, registration and settlement with no `act` line, under an incomplete ledger, are all `outcome-unknown` and the run is `unwired`; with no seal, the uncertain tail is classified, and only entries another session's ledger names become `after-run` | unit over constructed evidence for each sequence: corpus act; holdings act with store registration; a holdings act that crashed in its second phase (store write ledgered, publish committed without its `act` line); a recorded write to x followed by a failed intent for x; a move fully recorded; a move crashed after its `store_move` commit, and another between its source and destination publishes; a store transaction touching a location outside the act in progress; several null-`fulfills` store registrations matching one holdings intent; orphan tail with and without a later session, including that session's settlements, a failed intent before its first commit, and a session whose only acts failed; two unledgered run-actor sequences under an incomplete ledger | dropping the incomplete-ledger condition makes the forged case `unwired`; classifying the intent without propagation makes the crash case `quarantined`; truncating the tail at the last member hides the crash commit; the second-phase crash is `unwired`, and an allowance keyed to unnamed intents makes it `quarantined`; the several-registrations case is `quarantined`, and an allowance keyed to one intent makes it `unwired`; with location matching across the interval, the write-then-failed-intent case is `quarantined` instead of `unwired` (`intent-unfulfilled`, its write a member); ownership by any matching move intent makes a crashed `store_move` ambiguous; without the one-transaction limit the second sequence is `unwired` rather than `quarantined`; with a boundary found only through `act` lines, the failed-first-intent and failure-only cases quarantine the orphan; without the settlement clause of `after-run` the later session's settlements quarantine the orphan |
| E18 *(pending, science)* | the closing check's rules run on real `log.v1` output | crash fixtures through a real endpoint: a holdings act killed after its store commit and before its `act` line; a holdings act killed after its publish commit and before that `act` line, with its store write already ledgered; a corpus act killed after its commit; each `science log` output fed to `closing` | the same fixtures without the kill are `clean`; dropping a `log.v1` field gives `read-unavailable`, never a guess |
| E19 *(pending, science)* | a sandboxed shell actor uses the CLI through the handle at `report-only` | an actor under `bwrap` with no host configuration bound runs `science status` (succeeds) and a minting command (refused `permit-exceeded` by the endpoint) | the same CLI with no handle variables and no configuration fails with a configuration error, not a local dispatch; the handle together with `--config` is `handle-incomplete` |
| E20 *(full-run arm pending, science)* | the actor's stdio is the caller's (decision 12): bytes reach it across the gate, it holds only fds 0–2, the release cannot come from stdin, no other child holds the caller's descriptors, step 2 accepts only the three kinds, `autonomy run` never writes stdout and leaves the channel once the actor starts, the report fd carries the run and its disposition out of the actor's reach, and a scope stop, or a signal to the orchestrator's process group, leaves a sealed run | launch, under real `bwrap`: with fds 3–16 held open in the orchestrator, so the gate's fd is above 9, an echo actor driven over anonymous pipes and again over a socketpair, one line written before the release and one after, both echoed, and EOF ends it with exit 0; the actor lists `/proc/self/fd` and sees 0–3 (3 is the listing's own); step 2: `/dev/null` and a socketpair pass, and each of these exits 2 `stdio-refused` with no run directory, an empty stdout and nothing on the report fd: a pty on fd 1, a regular file on fd 2, `/dev/zero` on fd 0, a named FIFO, an unconnected UDP socket, an unconnected `AF_UNIX` stream socket, a listening `AF_UNIX` socket, a connected `AF_INET` socket, a closed fd 0, a `--report-fd` of 1, a `--report-fd 3` duplicated from fd 2, a report fd that is a tty, and a report fd that is a regular file; children: the recorded spawn arguments give the preflight, the probe, each `science` read, the endpoint, the proxy and the namespace helper stdin from `/dev/null`, and the endpoint shows `/dev/null` at `/proc/<pid>/fd/0`; a run that closes `unwired` at step 4 still writes the closing line after `disposition.json`; with the report pipe shrunk to one page (`F_SETPIPE_SZ`) and never read, that run still exits 4 within its bounds, its closing line dropped and `report-unwritten` in `events.jsonl`; with stderr a one-page pipe the caller has filled and never reads, a refusal at step 2 still exits 2; with a second writer the caller holds on the report pipe, and on a stderr pipe, filling the channel after the poll reports writable (a test hook between poll and write), the write returns `EAGAIN`, the line is dropped, the run exits within its bounds, and the original descriptors are still blocking afterwards; the same with a socketpair report fd; the documented terminal recipe returns 4 for that run under bash and zsh; full run with `--report-fd`: the actor's `/proc/self/fd` listing shows 0–3 only; bytes written on stdin before step 7 reach the actor intact; a silent actor leaves stdout empty; with the seal reply held by a test hook, the caller sees EOF on stdout and stderr once the namespace is gone while `autonomy run` has not exited; the report fd carries the run line and then the closing line, whose disposition and exit match `disposition.json` and the exit code; an actor that reopens fd 2 for reading gets neither line; with the orchestrator SIGSTOPped (no seal request, no EOF), SIGTERM to the endpoint within the lease gives `seal.json` with cause `term` and `session-close`, and after SIGCONT the orchestrator closes from that `seal.json`, kills the actor and writes the closing line; SIGTERM to every process of the run closes it through the orchestrator, whose exit code matches `disposition.json` and whose closing line arrives on the report fd; the same with the orchestrator SIGKILLed once `seal.json` appears leaves a run that `run close` settles `unwired` (`orchestrator-lost`) from that `seal.json`; SIGINT to the orchestrator's process group reaches neither the endpoint nor the outer `bwrap`, and the orchestrator seals before the actor dies and closes the run | a shell gate under `/usr/bin/dash` (skipped, naming dash, where it is absent) fails on the fd above 9 with `Bad fd number`; a blocking report write hangs the shrunk-pipe run past its bounds; a poll followed by a blocking write hangs the competing-writer case until a reader drains it; a non-blocking write through a `dup` leaves the original description non-blocking; the recipe without `pipefail` returns 0; a gate that reads its release on fd 0 consumes the first line, or exits 125 on it; a gate that reopens stdin on `/dev/null` gives immediate EOF; a gate that keeps its fd shows a fifth descriptor; `run` written on stdin with the gate fd closed unreleased exits 125, and the actor never runs; a check that accepts any character device but a tty passes `/dev/zero`; a check by `S_ISSOCK` alone passes the UDP socket, and its actor reaches a host listener from its own network namespace; a check by `SO_PEERCRED` alone passes the unconnected `AF_UNIX` socket; a report-fd check by number alone passes `3>&2`; a launch that passes the report fd into the sandbox shows a fifth descriptor; a probe that inherits stdin and reads it consumes the early bytes; an orchestrator that keeps its fds holds stdout open until it exits; an endpoint with the default SIGTERM disposition dies in the SIGSTOP case with no `seal.json`; without the endpoint-exit close trigger, the SIGCONT case stays open until the actor exits; with SIGTERM sent to the endpoint first and to the orchestrator only once the endpoint's pidfd shows it exited, a close step 1 without the already-sealed clause records `seal-missing`; an outer `bwrap` in the orchestrator's process group dies on the SIGINT before the seal; an endpoint in the caller's session dies on the SIGINT with no `seal.json` |
| E21 *(full-run arm pending, science)* | the model route is the actor's only network path, and the credential never reaches the actor (decision 13): an allowed request streams, direct network access is unavailable, destination overrides are refused or rewritten, and the credential is absent from everything the actor can read | launch, under real `bwrap`, with a fake upstream on the host serving TLS under a test CA (the model route's `ca_file`) and a canary credential: an actor script sends the allowed operation, and the upstream sends server-sent events 200 ms apart; the actor reads the first event before the upstream sends the last; the upstream saw its own `Host`, the canary in the route's header, none of the actor's `x-api-key` or `authorization`, and the body's bytes unchanged; from inside, a connect to the upstream's address, to `192.0.2.1:443` and to `[::1]:443` fails, the upstream's name does not resolve, and a host abstract `AF_UNIX` socket the test listens on is refused; refused with their codes, and absent from the upstream's request log: `CONNECT`, an absolute-form and an authority-form target, `/v1/messages/../x`, `/v1/%2e%2e/x`, `//other/v1/messages`, a query outside the route, a model outside the route, `Upgrade: h2c`, a chunked body carrying a second request to an unlisted path, a body over `max_request_bytes`, a body with `mcp_servers`, a `tools` element of type `web_fetch_20250910`, an image source of type `url`, an `anthropic-beta` token outside `header_tokens`, `anthropic-beta` repeated on two lines with the second holding an unlisted token, `anthropic-beta` and `Anthropic-Beta` on one request, an unlisted `anthropic-version`, a content block type outside `block_types`, a `tool_result` holding an unlisted block type, a `document` source of type `file`, a body with `model` twice (the allowed value first), a body with a byte-order mark, and a body with `NaN`; `Connection: x-api-key` with an `x-api-key` header leaves the upstream seeing only the canary; requests carrying `Host: other` or `X-Forwarded-Host: other` reach only the route's upstream, under its own `Host`, and never a second fake server named `other`; an upstream `302` to `other` returns to the actor, and `other` is never contacted; the actor walks every file it can read, its environment, and `/proc/*/environ` and `/proc/*/cmdline` of every process it can see, and keeps every byte the proxy sent it, and the canary appears in none of them; on the host, the canary appears in neither bwrap's argv (the actor's or the proxy's), nor the run directory, scratch, `egress.jsonl`, `proxy.log`, `events.jsonl` or `baseline.json`; the probe reports `ENETUNREACH`; full run (live, run by a recipe and never in the suite): pi in RPC mode under `autonomy run` with a model route to the real API and a cheap model, configured only through a `models.json` `baseUrl` and a placeholder key, answers one prompt, and `egress.jsonl` has its requests | an actor spec that shares the host network (a test hook) connects to the upstream directly, and the probe makes the run `unwired` (`sandbox-unproven`); a proxy that routes by the `Host` header (a test hook) sends the request to `other`; a proxy that forwards every header outside a deny list lets an `x-probe` header, absent from `forward_headers`, reach the upstream; a proxy that checks only `model` forwards the `mcp_servers`, `web_fetch` and URL-source bodies; a check keyed on `"type": "url"` alone forwards the `file` source and the unlisted block type; a proxy that checks only the first `anthropic-beta` line forwards the unlisted token; a `tool_use` block whose `input` holds `{"type": "url"}` is forwarded, and a check that walks the whole body refuses it; a lenient JSON parser forwards the duplicate `model`; a proxy that forwards the actor's framing lets the chunked second request reach the upstream's log; a proxy that normalizes paths before matching forwards `/v1/messages/./`; a buffering proxy delivers the first event only after the last; a credential passed with `--setenv` appears in bwrap's `/proc/<pid>/cmdline` |
| E22 *(full-run arm pending, science)* | proxy access belongs to one run and ends on stop, lease expiry, EOF or SIGTERM; missing enforcement fails closed | step 2: an unknown model route exits 2 `route-unknown` with no run directory; an `http` upstream, a route with no operation, and an operation with no model exit 2 `route-invalid`; a credential file that is missing, a directory, a symlink, mode 0644, hard-linked a second time, or not the user's (a root-owned file) exits 2 `credential-unavailable`; a route listing `x-api-key` or `transfer-encoding` in `forward_headers`, a route forwarding `anthropic-beta` with no `header_tokens` for it, a route with an unknown `api`, and an operation with no `block_types` each exit 2 `route-invalid`; a toolchain bind containing the credential file fails the static check; launch, under real `bwrap`: a credential removed between step 2 and the proxy's start, a credential of two lines, a helper whose `setns` is refused (a test hook), and a proxy that never confirms `listening` each make the run `unwired` (`egress-unproven`), and the actor's marker file never appears; `run stop` during a stream cuts it (`ended: route-closed`), a new connect gets `ECONNREFUSED`, and no request in `egress.jsonl` has a `seq` above the closing line's `last_seq`; with the orchestrator SIGSTOPped past the lease, the proxy closes the route (cause `lease`); with the orchestrator SIGKILLed, it closes on EOF; SIGTERM to the proxy process itself, as a scope stop delivers it, closes it; a SIGKILLed proxy leaves the actor's next connect refused at once, and the run closes with `egress-lost` reported; a proxy that ignores `close` (a test hook) is killed after 5 s with `egress-close-timeout` reported; two concurrent runs with different canaries each see only their own requests in their own `egress.jsonl`, and the upstream sees each run's own canary; with the orchestrator SIGKILLed and the proxy SIGSTOPped, `run close` kills the proxy after 5 s and reports `egress-close-timeout`; a route file edited after step 2 changes neither the enforced route nor the recorded digest | an orchestrator that keeps its copy of the listener leaves the actor's connect hanging in the backlog after the proxy dies, instead of refused; a helper that joins the init's own user namespace gets `EPERM` joining the network namespace (documents `NS_GET_USERNS`); a proxy without its own deadline keeps forwarding for a SIGSTOPped orchestrator past the lease; a close that waits for the seal before it closes the route forwards a request after the stop; a close that waits for the route's close before it seals lets an act start while a hung proxy is killed; a launch that ignores a helper failure releases the gate, and the actor's marker file appears; a proxy that rereads the route file enforces an edit made after step 2 that `baseline.json`'s digest does not show |

## 13. Delivery

The work lands across three repositories. The autonomy work splits into two plans
because half of it cannot be tested before the slices in `science` and `beliefs` land:

1. **Plan A (autonomy, now):** package skeleton, `tiers`, `ledger`, `closing`,
   `sandbox` with the static check and probe; rows E1–E6 and E17.
2. **The `beliefs` slice:** the run constructor with ceiling, the claims, `seal()`,
   the detached after-tip read, the basis identities, the confinement extension; rows
   E15–E16. It is filed in `beliefs`, designed there, and frozen in a cut.
3. **The `science` slice:** `serve --run`, the handle checks, the control socket,
   `seal.json`, the `run-sealed` mapping, descriptor path confinement and capture,
   `mcp bridge`, CLI handle mode, `heads`,
   `log`, the basis computation; rows E13–E14, E18 and E19. It is filed in `science`, and depends
   on 2.
4. **Plan B (autonomy, after 2 and 3):** `science_reads`, `baseline`, `endpoint`,
   `run`, the CLI, the gate's own release fd under `python3`, the stdio check, the
   non-blocking writes to the report fd and stderr, and
   `/dev/null` as stdin for the preflight and the probe; rows E7–E12 and E20.
   It is split in two. B1 needs neither slice: the gate's release
   fd, the stdio check, the non-blocking writes, `/dev/null` stdin for the preflight
   and the probe, steps 1 and 2 without the world checks, the close's records, and the
   CLI; E1's CLI arm and E20's launch arm. B2 follows 2 and 3 with the rest.
5. **The egress plan (autonomy, independent of 2 and 3):** decision 13. It covers the
   `egress` module, `--model-route` and step 2's route and credential checks, the
   denied set's `<config>` and credential entries, the probe's network check, the
   namespace helper and the listener, the proxy in its own sandbox with its records,
   lease and close, close step 0, and the removal of Plan A's `host` network mode. It
   lands rows E21 and E22 on their launch arms, and a live recipe that runs pi
   through B1's launch path, with no endpoint, and its proxy to the real API. Their
   full-run arms join B2. On
   approval, crew is asked to configure pi through `VERIFIABLY_MODEL_URL` with a
   placeholder key, and to pass no credential to an actor under `autonomy run`
   (crew-799319). `PI_OFFLINE=1` keeps pi from trying its own update and catalog hosts,
   which the sandbox cannot reach anyway.

The first unattended run (autonomy-9e8a43) starts after 4 and 5. The development mode
(autonomy-d5c1cb) consumes 5.

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
- **A channel socket bound into scratch for the caller's protocol.** It adds a second
  channel, with its own path and lifetime, and the probe found no benefit it gives over
  stdio (decision 12).
- **pi-durable running in the actor's process.** It moves the caller's driver and
  metering to the constrained side of the boundary. It remains an option for the
  science path if ops-fbc3d9 picks pi-durable, and it then needs no stdio channel.
- **`autonomy run` relaying the actor's stdio.** A relay puts autonomy in the data path
  of every byte, and it would let a terminal stay connected on the host side. It does
  nothing that a pipe the caller holds cannot do.
- **Passing any descriptor through, or checking a regular file against the denied
  set.** A terminal gives the actor the person's keystrokes, ioctls and termios. A file
  passed read-only can be reopened read-write through `/proc/self/fd`, and a socket of
  the host's network namespace bypasses the sandbox's own. Checking a file's path
  against the denied set by descriptor adds a second form of the static check, and it
  still hands the actor a host object. A connected stream ends at a process the caller
  chose.
- **Other gates.**
  - **A shell gate on a fixed low fd.** Moving the pipe to a fixed low fd in the
    orchestrator means a `dup2` over a descriptor it may hold, or a `preexec_fn`.
  - **Requiring bash.** That would be a new host requirement.
  - **bwrap's `--block-fd`.** It releases the child on any byte and also on EOF, so
    a launcher that closes the fd while aborting would run the actor.
- **Egress by the host network and a proxy variable.** `--share-net` with
  `HTTPS_PROXY` set is configuration, not enforcement. The actor unsets the variable
  and reaches any host.
- **An `AF_UNIX` socket bound into the sandbox, like the endpoint's.** It keeps a
  token and a peer check, but no harness checked accepts a socket as a model base URL:
  pi's HTTP stack has no socket option. Each actor would need a bridge process inside
  the sandbox, and the bridge is harness-shaped. A loopback listener made from the
  host side needs no process inside, and a loopback address is already private to the
  actor's network namespace.
- **A user-mode network stack (`slirp4netns`, `pasta`) with a destination filter.**
  It forwards general traffic, so the filter must name addresses that the upstream's
  DNS changes. Below HTTP it can check neither the operation nor the model, and the
  actor would still have to hold the credential.
- **A forward proxy with TLS interception.** The actor would need to trust a CA the
  run mints, and the actor would still send the credential. An allow-list on the TLS
  server name checks neither the operation nor the model.
- **The credential substituted inside the actor's process** (an `!command` key, a
  file the harness reads). Whatever the actor's process can use, the actor can read.
- **The proxy in the orchestrator's process, or unsandboxed.** The orchestrator would
  hold the credential, and a parser bug reachable from the actor would run with the
  user's files and the host's network. A process of its own, in a sandbox of its own,
  bounds both.
- **A route-free run with the host network.** Plan A's `host` mode let a run reach
  any host, and no current actor needs it. Keeping it would leave a second way out
  that decision 13 does not see.
- **The run line on stderr.** The actor can reopen a stderr pipe through
  `/proc/self/fd`, read the line and write a forged one in its place. A forged
  `run_dir` could point into scratch, at a `disposition.json` the actor wrote. The
  report fd is never the actor's.
