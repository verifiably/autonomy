# Authority beyond the science run — brief

**Date:** 2026-10-15. **Goal:** autonomy-d9adef. **Ideas:** autonomy-1aac03 (the
authorization model), autonomy-d5c1cb (unattended development actors and actor stdio).

## 1. Problem

Several designs name autonomy as the owner of authority to act: spending money,
publishing, changing a host, operating unattended. A flow gate or an inbox answer must
never grant any of these. But the only authority autonomy defines is a tier on a science
run. Two consumers are now waiting on more than that. crew wants autonomy to set the
limits for unattended development work, and crew drives pi over stdio, which
`autonomy run` does not yet allow.

## 2. Current behaviour and evidence

- **The tier is the only grant.** Envelope spec §11 maps a tier onto every part of a
  grant: identity, operation and resource, scope, lifetime, revocation, approval, audit
  receipt and rollback. A tier comes only from an `autonomy run` invocation, and
  `publishes` is refused at open (§5). Budget enforcement, credential custody and network
  egress are deferred to autonomy-9e8a43.
- **The envelope's checks assume a corpus.** Tiers are kernel `WritePermit`s. The
  denied set comes from the world configuration (§7). The closing check compares chain
  intervals against the session ledger (§9). A development actor writes a git worktree,
  not a corpus. Under today's design its run would open a writer session it never uses
  and close `clean` without checking anything.
- **The sandbox does not need a world.** Plan A's pieces depend on no corpus: the
  sandbox spec, the static check, the `ENOENT` probe, the gated launch and the namespace
  kill (`python/src/autonomy/sandbox/`, ef18e81 to 8251584). The lease and kill-switch
  design has the same independence.
- **Actor stdio is unspecified, and the code closes stdin.** The spec never mentions
  stdio. Plan A's gate reads its release line on stdin and then runs `exec </dev/null`
  (`sandbox/bwrap.py`, `_GATE`). stdout and stderr are inherited from the orchestrator.
  crew's `pi-cli-rpc` runtime spawns pi with piped stdio and speaks RPC over those pipes
  (crew `src/scopes.ts`, `src/runtime/pi-rpc.ts`). As built, `autonomy run` cannot carry
  it. crew core design §8.2 leaves this to autonomy-641123.
- **crew computes its own grants.** A grant is the kind's request intersected with the
  user's `policy.toml`. Each limit is recorded as enforced or advisory, and unattended
  runs are off for every source. The first development slice is supervised: the
  filesystem and network are advisory, and the model credential is in the trajectory
  (crew core design §4.2–4.3). The conditions crew names for unattended development work
  are an operating-system boundary and credentials kept out of the trajectory. These are
  the conditions autonomy-9e8a43 sets for science.
- **The boundary is stated, but nothing enforces it.**
  - ops agent-layer split §5.5: a gate authorizes the next task state, and nothing else.
  - relay typed-interaction spec §4.3: an `authorization`-class answer comes only from a
    local surface and "grants nothing". relay v1 excludes "any authorization semantics".
  - Today these authorizations are instructions in the global agent rules, not a
    mechanism.
- **A shape to borrow.** The harness-engineering authority thesis (autonomy-1aac03's
  note of 2026-10-11) gives the parts of a grant, staged consequential effects, and one
  policy decision point that returns a precise denial and the safe next action.

## 3. Constraints

- No kernel import. The envelope names no harness, and anything specific to a harness
  belongs to the caller (envelope §10).
- The envelope spec is approved. A non-world mode or a change to actor stdio is a spec
  amendment. Plan B (autonomy-641123) consumes it next and is blocked on beliefs-7a56ef
  and sci-a1d45f.
- autonomy-9e8a43 owns budget enforcement, credential custody and egress policy.
  Development work should reuse those answers, not fork them.
- Publication is never unattended. crew rejected a sandbox of its own, because the
  runner would grant its own limits (crew §10, decision 1).

## 4. Alternatives

**Development actors.**

- A. A development mode of `autonomy run`. It needs no world, binds the task worktree
  as scratch, and keeps the sandbox, lease and kill. A closing check over the worktree
  replaces chain membership.
- B. autonomy exposes the sandbox and lease as a primitive, and crew judges the
  development disposition. This is less autonomy code, but the runner then vouches for
  its own boundary.
- C. Development work stays attended until a container backend exists.

*Lean:* A. It needs a definition of what a development run's `quarantined` means.

**Stdio.**

1. Pass-through. The gate takes its release on its own fd, and the actor inherits the
   caller's stdin and stdout. `autonomy run` writes its own reports only to stderr and
   the run directory.
2. A channel socket bound into scratch.
3. pi-durable running in the actor's process inside the sandbox, which moves crew's
   driver and metering to the constrained side.

*Lean:* 1, pending autonomy-c5c566.

**Authorization model.**

- i. A written contract first. It defines the parts of a grant, says who may issue each
  class, and holds that a gate is never a grant. The tier stays its only mechanical
  instance.
- ii. A mechanism. autonomy issues and records grants, and one decision point serves
  crew, relay and flows.

*Lean:* i, then ii one consequence class at a time, as consumers need it. The budget
allowance in autonomy-9e8a43 is the first.

## 5. Unanswered questions

1. Is the first form of the authorization model a contract or a mechanism? *The user.*
2. Is crew's grant (request ∩ `policy.toml`) a grant under autonomy's model, or a
   narrower layer beneath it? For unattended attempts, who owns the policy? *The user,
   then a joint crew and autonomy design.*
3. Can a relay `authorization` answer ever become a grant, or does approval come only
   from an `autonomy` invocation, as §11 says? *The user.*
4. What does a development run's closing check verify (only the worktree and its branch
   changed, no push, no stray `tasks/` writes), and what is quarantined? *Design, after
   autonomy-c5c566.*
5. Does pi over RPC run in the sandbox with stdio held by the caller, and what must be
   bound? *autonomy-c5c566.*
6. Is credential custody shared between development and science runs? *autonomy-9e8a43's
   spec.*

## 6. Proposed decomposition

- autonomy-d9adef, the goal, owns both ideas and the research.
- autonomy-c5c566 is the stdio and bind probe. It wakes autonomy-d5c1cb, and its
  recommendation goes to autonomy-641123.
- autonomy-1aac03 waits on questions 1–3. Once they are answered it becomes the design
  of the contract.
- autonomy-d5c1cb waits on autonomy-c5c566 and question 4. If alternative A holds, it
  becomes an envelope amendment, a development mode, designed before Plan B is planned.
