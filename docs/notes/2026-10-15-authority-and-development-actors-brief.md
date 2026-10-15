# Authority beyond the science run — brief

**Date:** 2026-10-15, revised the same day after the user's review. **Goal:**
autonomy-d9adef. **Ideas and tasks:** autonomy-1aac03 (the authorization contract),
autonomy-d5c1cb (a development mode of `autonomy run`), autonomy-a41de4 (the actor
stdio amendment), autonomy-c5c566 (the probe).

## 1. Problem

Several designs name autonomy as the owner of authority to act: spending money,
publishing, changing a host, operating unattended. A flow gate or an inbox answer must
never grant any of these. But the only authority autonomy defines is a tier on a science
run. Two consumers are now waiting on more than that. crew wants autonomy to enforce the
limits for unattended development work, and crew drives pi over stdio, which the
envelope does not yet provide for.

## 2. Current behaviour and evidence

- **The tier is the only grant.** Envelope spec §11 maps a tier onto every part of a
  grant: identity, operation and resource, scope, lifetime, revocation, approval, audit
  receipt and rollback. `publishes` is refused at open (§5). Budget enforcement,
  credential custody and network egress are deferred to autonomy-9e8a43.
- **The envelope's checks assume a corpus.** Tiers are kernel `WritePermit`s. The
  denied set comes from the world configuration (§7). The closing check compares chain
  intervals against the session ledger (§9). A development actor writes a git worktree,
  not a corpus. `autonomy run` is Plan B work (autonomy-641123) and does not exist yet.
  As designed, a development run would open a writer session it never uses, and its
  closing check would verify nothing about the worktree.
- **The sandbox does not need a world.** Plan A's pieces depend on no corpus: the
  sandbox spec, the static check, the `ENOENT` probe, the gated launch and the namespace
  kill (`python/src/autonomy/sandbox/`, ef18e81 to 8251584). The lease and kill-switch
  design has the same independence.
- **Actor stdio is unspecified, and the code closes stdin.** The spec never mentions
  stdio. Plan A's gate reads its release line on stdin and then runs `exec </dev/null`
  (`sandbox/bwrap.py`, `_GATE`). stdout and stderr are inherited from the orchestrator.
  crew's `pi-cli-rpc` runtime spawns pi with piped stdio and speaks RPC over those pipes
  (crew `src/scopes.ts`, `src/runtime/pi-rpc.ts`). The launch as built cannot carry it.
- **Probe results (autonomy-c5c566, 2026-10-15).** The probe used pi 1.1.0 and
  `claude-haiku-5-5`. It reused Plan A's `SandboxSpec`, `build_argv` and `prove()` with
  `--share-net`. A copy of the launch took the gate's release on its own fd, and the
  caller's pipes went to pi as its stdin and stdout. The scratch dir held a throwaway
  repository's linked worktree. Three runs together cost about US$0.005. The script is
  attached to the task.
  - **RPC works across the sandbox.** `get_state` answered in 0.6 s. One prompt ran six
    bash steps and settled in 15–39 s. An abort during `sleep 60` settled in 0.01–0.03 s
    with `aborted: true`. Closing stdin ended pi with exit 0.
  - **Binds and environment.** Beyond `/usr` and `/etc`, pi needed:
    - the node install and the pi install, both read-only;
    - the agent directory, read-write: pi's credential store locks with `mkdir
      auth.json.lock` beside `auth.json`, so a read-only agent dir fails every prompt with
      `EROFS`, and pi also writes `models-store.json` there;
    - the scratch dir, holding the worktree, the session directory and `HOME`.

    The environment was `PATH` with node's bin, `HOME`, `PI_CODING_AGENT_DIR`,
    `PI_SKIP_VERSION_CHECK`, `PI_TELEMETRY=0`, the git identity variables and `LANG`.
    hq's launcher was bypassed, because its version and lock check reads hq's checkout.
    The envelope's `--chdir` names the scratch root, so the actor's working directory had
    to be set to the worktree separately.
  - **A linked worktree needs metadata from outside it.**
    - Worktree only: every git command fails ("gitfile does not point to a valid
      repository"), while file edits land.
    - Main `.git` read-only plus the worktree's admin dir read-write: `status`, `log` and
      `rev-parse` work, and `git add` fails on the read-only object store.
    - Adding `objects`, `refs/heads` and `logs` read-write lets the actor commit. git
      then prints a non-fatal `packed-refs.lock` error. That bind set lets the actor move
      every branch, `main` included, and rewrite reflogs. A single branch ref cannot be
      bound on its own, because git updates a ref through a `.lock` file and a rename in
      its directory. The config and the hooks stay read-only; a writable hook would run
      on the host's next git command.
    - Plan A's static check refuses a bind of the main checkout's `.git` while the main
      checkout is denied (`bind-overlaps-denied`). Its ancestry rule cannot express "deny
      the working files, allow `.git`".
  - **Credential.** It is readable inside: a plain shell in the identical sandbox read
    the 153-byte `auth.json`. This is inherent while pi holds the key in its own process.
    Separately, the key appeared nowhere in pi's session files, RPC records, stdout,
    stderr or `models-store.json` (47 files scanned in each run). Keeping it out of the
    actor's reach needs a proxy that substitutes the credential, as pi's
    containerization guide describes. That belongs to autonomy-9e8a43's credential
    custody. Passing it with `--setenv` would also put it in bwrap's command line,
    visible to every same-uid process.
- **crew computes its own grants.** A grant is the kind's request intersected with the
  user's `policy.toml`, which lives outside every repository. Each attempt records the
  policy digest and every narrowing. Each limit is recorded as enforced or advisory, and
  unattended runs are off for every source. The first development slice is supervised:
  the filesystem and network are advisory, and the model credential is in the trajectory
  (crew core design §4.2–4.3).
- **The boundary is stated, but nothing enforces it.**
  - ops agent-layer split §5.5: a gate authorizes the next task state, and nothing else.
  - relay typed-interaction spec §4.3: an `authorization`-class answer comes only from a
    local surface and "grants nothing".
  - Today these authorizations are instructions in the global agent rules.
- **A shape to borrow.** The harness-engineering authority thesis (autonomy-1aac03's
  note of 2026-10-11) gives the parts of a grant, staged consequential effects, and one
  policy decision point that returns a precise denial and the safe next action.

## 3. Constraints

- No kernel import. The envelope names no harness, and anything specific to a harness
  belongs to the caller (envelope §10).
- The envelope spec is approved. A development mode or a change to actor stdio is a
  spec amendment.
- autonomy-9e8a43 owns budget enforcement, credential custody and egress policy.
  Development work reuses those answers rather than forking them.
- Publication is never unattended.
- **Prevention, not detection.** A push, a host change or a credential use leaves no
  trace in the worktree. A diff after the run cannot establish that such an effect did
  not happen, so these effects must be made unavailable at the boundary.

## 4. Decisions and alternatives

**Decided by the user, 2026-10-15.**

1. **Contract first, enforcement class by class.** autonomy writes the authorization
   contract: who may grant what, how delegation narrows authority, and where each limit
   is enforced. Concrete classes are enforced as they come, the tier first and the
   budget allowance (autonomy-9e8a43) next. A general grant service waits for a
   consumer that needs one.
2. **crew's grant sits beneath an autonomy grant.** The effective permission is
   `autonomy ceiling ∩ the user's crew policy ∩ the kind's request`. crew may narrow
   authority and never enlarge it. The user, as operator, owns the policy, kept outside
   storage any actor can write, and each attempt records its snapshot. crew's design
   already specifies most of this.
3. **A relay answer grants nothing, for now.** The contract separates the surface where
   approval is given from the issuer of a grant. A future authenticated approval through
   relay could ask autonomy to issue a bounded grant, with relay still only carrying the
   decision. Running an autonomy command never establishes authority by itself: an
   orchestrator needs permission delegated beforehand, and an actor that invokes the
   CLI gains nothing.

**Development actors.**

- A. A development mode of `autonomy run`. It needs no world, binds the task worktree
  as scratch, and keeps the sandbox, lease, kill and run directory.
- B. autonomy exposes the sandbox and lease as a primitive, and crew drives the run's
  lifecycle itself.

Under both, autonomy enforces the confinement and crew judges whether the result is
useful and correct, so neither makes crew vouch for its own boundary. *Lean (user's):*
A, for one lifecycle, cancellation path and evidence record across science and
development. In that mode:

- Pushes, host changes and credential use are prevented at the boundary, never
  inferred from the worktree afterwards.
- `quarantined` keeps the result and blocks its promotion (no merge, no close), and
  records what could not be established.
- A `clean` boundary verdict says only that the run stayed in its envelope. Passing
  tests and acceptable code are crew's acceptance, judged separately.

**Stdio.**

1. Pass-through. The gate takes its release on its own fd, and the actor inherits the
   caller's stdin and stdout. `autonomy run` writes its own reports only to stderr and
   the run directory.
2. A channel socket bound into scratch.
3. pi-durable running in the actor's process inside the sandbox, which moves crew's
   driver and metering to the constrained side.

*Recommendation (autonomy-c5c566):* 1, pass-through. It worked unchanged across bwrap
`--new-session --unshare-all`, abort included. The amendment must also say:
- the gate's release travels on its own fd;
- pi reserves stdout for protocol records, so `autonomy run` never writes to the actor's
  stdout;
- the actor's working directory is named separately from the scratch root;
- the spec allows read-write binds beyond scratch (pi's agent dir, at least), each one
  under the static check.

Alternative 2 adds a channel without a benefit the probe found. Alternative 3 remains for
the science path if ops-fbc3d9 picks pi-durable. The approved amendment (autonomy-a41de4)
is a prerequisite of Plan B's launch interface. Plan B does not wait on the contract or on the
development mode.

*Amendment (autonomy-a41de4, under review):* envelope decision 12 takes pass-through. The
gate is released on its own fd, and `autonomy run` never reads stdin or writes stdout.
Each of fds 0–2 must be a pipe, a socket or `/dev/null`. stderr starts with a run line and
is otherwise diagnostic only. Row E20 tests it. Two of the points above went the other
way. The agent directory and the working directory stay in scratch, set up by the actor
argv, so the sandbox spec gains neither a read-write bind nor a separate working
directory. Binds beyond scratch are left to autonomy-d5c1cb.

## 5. Unanswered questions

1. *Answered by autonomy-c5c566 (§2):* RPC works with stdio held by the caller. A linked
   worktree needs its admin dir and the shared metadata. The credential is readable
   inside and appeared in no log.
2. How does the development mode make pushes and host changes unavailable? Its network
   must reach only the model endpoint, and push credentials stay out. Shared git metadata
   cannot be narrowed to one branch: committing needs `refs/heads` writable, which
   exposes every branch. One option, not yet tested: give the actor a clone in scratch
   (`git clone --shared` reads objects through alternates, with the shared object store
   bound read-only), and have the host fetch the branch only after a clean verdict. Then
   no shared metadata is writable. What does the closing check still verify? *Design in
   autonomy-d5c1cb.*
3. Is credential custody shared between development and science runs? *autonomy-9e8a43's
   spec.*

## 6. Proposed decomposition

- autonomy-d9adef, the goal, holds everything below.
- autonomy-c5c566, the probe of RPC, workspace and credentials, is done (§2). It wakes
  autonomy-d5c1cb, and autonomy-a41de4 depends on it.
- autonomy-a41de4 is the actor stdio amendment to the envelope spec. autonomy-641123
  (Plan B) depends on it.
- autonomy-1aac03 is scoped as the design of the authorization contract, from decisions
  1–3.
- autonomy-d5c1cb stays an idea until the probe answers. It then becomes the design of
  the development-mode amendment.
