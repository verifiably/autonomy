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

*Lean:* 1, pending autonomy-c5c566. The approved amendment (autonomy-a41de4) is a
prerequisite of Plan B's launch interface. Plan B does not wait on the contract or on the
development mode.

## 5. Unanswered questions

1. Does pi over RPC run in the sandbox with stdio held by the caller? Can it inspect and
   edit a linked worktree, whose `.git` file points at metadata outside the worktree? What
   must be bound? Is the credential readable inside, and does it appear in any log?
   *autonomy-c5c566.*
2. How does the development mode make pushes and host changes unavailable: no network
   beyond the model endpoint, no push credentials, git metadata bound read-only except
   the branch ref? What does its closing check still verify? *Design in autonomy-d5c1cb,
   after autonomy-c5c566.*
3. Is credential custody shared between development and science runs? *autonomy-9e8a43's
   spec.*

## 6. Proposed decomposition

- autonomy-d9adef, the goal, holds everything below.
- autonomy-c5c566 is the probe of RPC, workspace and credentials. It wakes
  autonomy-d5c1cb, and autonomy-a41de4 depends on it.
- autonomy-a41de4 is the actor stdio amendment to the envelope spec. autonomy-641123
  (Plan B) depends on it.
- autonomy-1aac03 is scoped as the design of the authorization contract, from decisions
  1–3.
- autonomy-d5c1cb stays an idea until the probe answers. It then becomes the design of
  the development-mode amendment.
