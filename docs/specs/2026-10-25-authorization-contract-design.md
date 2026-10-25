# Authorization contract — design

**Date:** 2026-10-25
**Status:** draft, for the user's review.
**Task:** autonomy-1aac03, under the goal autonomy-d9adef. Source: ops-cb9749, the
agent-layer split that handed autonomy the authority boundary.

**Scope:** the contract under which anything in this stack acts on authority it was
given rather than authority it has: who may grant what, how a grant narrows as it is
delegated from the operator through an orchestrator to an actor, and where each limit
is enforced. It defines the parts of a grant, the issuers, the consequence classes with
their enforcement points, the difference between a gate, an approval surface and a
grant, and the tier as the contract's first instance. It is a contract, not a
mechanism: the classes it names are enforced one at a time, by designs that cite it.

**Inherits:** the governing design is the
[user and autonomy layer design](https://github.com/verifiably/beliefs/blob/main/docs/superpowers/specs/2026-08-29-user-and-autonomy-layer-design.md),
whose §5.2 (the permit bound in the writer endpoint; the sandbox denial as the
boundary) and §7.1 (the envelope, tiers as permits never granted wider) this document
builds on. The envelope design (`docs/specs/2026-10-12-envelope-design.md`) is the
first enforced instance; its §11 maps a tier onto the parts named here. The shape of a
grant is taken from the harness-engineering authority thesis
([Maximize autonomy inside explicit authority](https://github.com/lopopolo/harness-engineering/blob/main/docs/authority/README.md)).

**Decided by the user, 2026-10-15** (brief
`docs/notes/2026-10-15-authority-and-development-actors-brief.md` §4), and taken here
as given:

1. Contract first, enforcement class by class. No general grant service until a
   consumer needs one.
2. crew's grant sits beneath an autonomy grant: effective permission is the autonomy
   ceiling ∩ the user's crew policy ∩ the kind's request. crew narrows and never
   enlarges.
3. A relay answer grants nothing. The approval surface is distinct from the issuer.
   Running an autonomy command never establishes authority by itself.

**Out of scope:**

- **The mechanism of any class** beyond the tier: the budget allowance
  (autonomy-9e8a43), the development mode (autonomy-d5c1cb), a grant that a remote
  approval asks for (§7.3). Each is designed against this contract and cites it.
- **Task state.** A flow gate authorizes the next state of a task and nothing else
  (ops `docs/specs/2026-10-03-agent-layer-split-design.md` §5.5). Which evidence a
  gate demands is flows' (flows-912ac5).
- **Question policy:** when to ask a person and how (lore). This document says what
  an answer can and cannot do, not when to ask for one.
- **Publication's own design.** It stays attended (governing §6; envelope §5). This
  document only places it.

## 1. Problem

Several designs name autonomy as the owner of authority to act, and each states the
same boundary without a mechanism:

- ops' agent-layer split §5.5: a gate authorizes the next task state, and never
  spending, publishing, repointing a host or operating unattended; "those are
  authorizations, held today by the user's rules and later by autonomy".
- relay's typed-interaction spec §3 and §4.3: an inbox answer is never an
  authorization; an `authorization`-class answer is accepted only from a local
  surface and "grants nothing".
- crew's core design §4.2–4.3 and §10 decision 1: crew computes a grant as the
  kind's request ∩ the user's policy, records each limit as enforced or advisory,
  and recommends autonomy's envelope as the boundary for unattended work; crew's
  orchestration-boundaries amendment of 2026-10-25 §4 gives autonomy "authorization
  and enforcement, including the envelope" and says crew never infers authority from
  a successful review.
- crew's amendment §3: "role or flow content cannot widen" external grants.

The only authority autonomy defines is a tier on a science run (envelope §5, §11). The
tier is well formed: it is a closed permit, fixed before the session exists, enforced
by the kernel writer at every act, verified by the closing check. But nothing says what
a tier is an instance *of*: what every grant in the stack must name, who may issue one,
what an orchestrator holds when it runs `autonomy run`, which effects are unattendable
at all, and why an answer tapped on a phone cannot be one. Without that, each new
consumer (the budget allowance, the development mode, crew's policy, a remote approval)
would define authority in its own terms, and the boundary each design states would be
held together by prose.

This document is that statement. It is written so that a later design can be checked
against it: a class design that cannot fill §3's parts, name its enforcement point
(§5) and its refusal codes (§8) is not finished.

## 2. Vocabulary

Capability and authority are kept apart, as the thesis has it. **Capability** is a
way to cause an effect: a tool, a CLI, a socket, an API. **Authority** is permission
for an identity to cause a class of effect on a resource, within a scope, for a time,
under an approval and a recovery contract. A **grant** is one unit of authority. A
**ceiling** is the widest grant its holder may pass down.

Three things look alike and are not:

| thing | what it is | what it does | example |
|---|---|---|---|
| **gate** | a recorded judgment that an artifact meets a bar | authorizes the next state of a task, nothing else | `gate: verified` in flows; a review verdict |
| **approval surface** | where a person states a decision, and the channel that carries it | carries a decision from a person to the asker, with its provenance | the terminal; the desktop; relay's inbox on a phone |
| **grant** | authority issued by an issuer and bound at an enforcement point | makes an effect available to an identity, and makes everything outside it unavailable | a tier on `autonomy run`; a model route |

A gate is read by the thing that advances the task. An approval surface is read by the
asker. A grant is read by an enforcement point. None of the three stands in for
another: a gate record is never read as a grant (ops §5.5), an answer is never a grant
(relay §4.3, decision 3), and a grant is never inferred from a review having passed
(crew amendment §4).

An **issuer** is a principal that may create a grant. An **enforcement point** is a
mechanism that makes an effect outside the grant unavailable, placed where the
constrained party cannot reach around it; every enforcement point has a **decision
point** that refuses with a code and the safe next action (§8). An **audit receipt**
is the record a grant leaves, written before the effect and never rewritten.

An effect is **attended** when a person causes or confirms it at that moment, in their
own session, under their own identity, and **unattended** when an actor causes it
under a grant. "Never unattended" means no grant for it exists, so no actor can cause
it, whatever it is told.

## 3. The parts of a grant

Every grant names these parts. A class design fills each one or says, in writing, why
the part does not apply. The list is the thesis's, with each part given its meaning
in this stack.

1. **Identity.** Who the grant is for. Identity narrows down the delegation chain: the
   operator is a person; an orchestrator is a program the operator runs; an actor is a
   process with an identity that exists only for one run (`session:<id>`, envelope
   decision 2). An identity is something an enforcement point can check, not a name a
   request carries: the writer endpoint sets the actor itself and ignores what a
   request says (governing §5.2).
2. **Operation and resource.** Which effects, on what. Operations are typed and closed
   (a permit's kinds and act families; a route's methods, paths, models and body
   positions), never a free description. The resource is named by something the
   enforcement point can compare (a chain's genesis and tip; a route's upstream).
3. **Scope.** The environment the effect may happen in: which paths are reachable, which
   network, which processes, which concurrency. Scope is what the sandbox, the denied
   set, the network namespace and the claim express. Scope is the part most often
   confused with operation: a tool allowlist is scope, and it bounds nothing an actor
   can reach by another road.
4. **Lifetime and revocation.** When the grant ends on its own, and how it is ended
   early by someone other than its holder. A lifetime that the holder renews is not a
   lifetime (envelope §14: "the constrained party extends its own authority").
   Revocation is a path the issuer or the operator holds; it reaches the enforcement
   point, not the actor, so a hung or hostile actor cannot ignore it. Changing the
   operator's configuration affects later grants, not a running one (envelope decision
   13), so revocation of a running grant is its own path and is named.
5. **Approval.** Which principal issued it, by which act, under which separation of
   duties. "The person who ran the command" is an approval only when the command is
   theirs to run (§4). An approval is a hop in the delegation chain, and each hop is
   recorded.
6. **Audit receipt.** What the grant wrote, where, before the first effect. The receipt
   lives outside the reach of the identity it covers (the run directory is never bound
   into the sandbox, envelope §6), names every part above, and is never rewritten. A
   consumer that keeps a snapshot records the receipt's identity (a run id, a digest),
   not a copy that can drift.
7. **Rollback.** What happens to the effects when the grant is found to have been
   exceeded or wrong. The contract distinguishes **held** from **rolled back**: a
   `quarantined` run holds its effects and lists them; undoing them is a person's act.
   An effect that cannot be held or undone (a push, a publication, a host change, a
   spend) is not made unattended; it is made unavailable at the boundary (§5) or kept
   attended and staged (§6).

A grant missing a part is not narrower, it is unbounded in that part. That is why the
tier refuses an empty mints map and a non-reachable family rather than defaulting them
(envelope §5): a default is a part nobody named.

## 4. Issuers and delegation

There are three principals, in a fixed order. Each holds a ceiling, issues grants no
wider than it, and the last issues none.

**The operator** is the person who owns the host, the credentials, the corpora and
the policy. The operator is the root of every grant and the only principal that can
make an attended effect. The operator's authority is expressed in two forms:

- **Configuration the operator owns**, kept where no actor and no orchestrator can
  write it: the world configuration (which corpora exist and which are denied), the
  model routes and credential files under `<config>/routes/` (envelope decision 13),
  the lease floor, and crew's `policy.toml` under the user's configuration directory,
  outside every repository and every attempt's workspace (crew §4.2). The envelope
  adds `<config>` and every credential file to the denied set, so this configuration
  is unreachable from inside a run by construction.
- **Invocation**: running `autonomy run` with a tier and a route, or running crew on a
  kind. An invocation is an approval (§3 part 5) only when the operator makes it, or
  when an orchestrator makes it under a ceiling the operator delegated beforehand.

**An orchestrator** is a program that composes runs and never reaches inside one
(envelope decision 1): crew, the loop of sub-project 7, or a person's script. An
orchestrator holds what the operator's configuration lets it reach, and nothing more.
It may narrow: choose a lower tier than it could, a shorter lease, a tighter route,
a smaller budget. It may not widen, and it has no path by which to try: the tier is
data the orchestrator hands to the endpoint and the kernel enforces (envelope decision
7), and the route is read once and digested into the receipt (decision 13).

**An actor** is the process in the sandbox. It holds what its run gives it: the
endpoint handle, the model URL, scratch, and its stdio. It issues nothing, and it can
reach nothing that carries authority: the corpora, the world root, the run directory,
`<config>`, the credential, the host network and `$XDG_RUNTIME_DIR` are all outside
its namespaces. This is what decision 3's last clause means mechanically. **Running an
autonomy command establishes no authority**, because the command is a capability and
the authority is in what the caller can reach: an actor that runs `autonomy run`
inside its sandbox is refused before a run directory exists (`runtime-dir-unset`,
since the sandbox clears the environment; `allocation-failed` if the actor sets the
variable to a path its namespaces do not hold; `route-unknown` for any route) and can
open no session, because the chains it would write are denied to it. §12 row A3 tests
that.

**Delegation narrows every part.** Writing grant(x) for the grant a principal holds:

    grant(actor) ⊆ grant(orchestrator) ⊆ ceiling(operator)

part by part: identity becomes more specific (a person, a program, a session);
operations and resources are subsets; scope is a subset; lifetime is no longer and
revocation gains a path and loses none; approval records the hop; receipts chain to
the hop above; rollback stays the operator's. A grant that is wider in any part than
the one above it is not a grant, and an enforcement point that finds one refuses
(`permit-mismatch` at envelope step 5 is this check for the tier).

**crew's place in the chain.** By decision 2, crew's grant to a worker is

    ceiling(autonomy) ∩ policy(user) ∩ request(kind)

The three are different kinds of thing, and the intersection is taken part by part:

- **ceiling(autonomy)** is what the envelope enforces for the run crew starts: the
  tier, the route, the lease, the sandbox. It is the only term with a boundary the
  worker cannot reach around.
- **policy(user)** is the operator's configuration for crew, which may only choose
  within the ceiling: which tiers, routes, models, budgets, tools and projects a
  source may ask for, and whether unattended runs are allowed at all (false for every
  source today, crew §4.2).
- **request(kind)** is what the reviewed kind asks for. A `required` request that the
  intersection does not grant ends the attempt `refused-at-start` (crew §4.2).

crew records the request, the policy digest, the grant and every narrowing, and marks
each limit **enforced** or **advisory** (crew §4.3). Under this contract, a limit is
*enforced* only when its enforcement point is in §5's table with state *enforced* and
the run is under it; everything else crew does (its environment allowlist, its git and
`gh` speed bumps, its `tasks` shim, its post-hoc digests) is advisory, whatever it
prevents in practice, because the worker could reach around it. The attempt's snapshot
of the autonomy term is the run's receipt identity (its run id and `baseline.json`),
not a restatement.

**Limit, stated.** On a single-user host, the operator and every orchestrator run under
one account, and the operator → orchestrator hop is enforced by configuration
ownership (where the policy and routes live), not by identity: any program running as
the user can run `autonomy run --tier mints` with any route the operator has
configured. The orchestrator → actor hop is the one enforced mechanically today. The
contract does not pretend otherwise. The first orchestrator the operator does not
start by hand (the loop, or crew with `unattended` on for a source) is the consumer
that needs the operator → orchestrator hop made mechanical: an operator-owned
manifest naming, per orchestrator, the tiers, routes, corpora and lease it may ask for,
read at step 2 and digested into the receipt. That is a class design of its own, and
not this one (decision 1).

## 5. Consequence classes and their enforcement points

Each class is a kind of effect with its own consequence and recovery. For each, the
table gives who issues the grant and from which ceiling, the enforcement point, and the
state today. "Attended" means no grant exists and none is planned: the effect is the
operator's own act.

| class | effect | issuer and ceiling | enforcement point | state |
|---|---|---|---|---|
| **governed writes** | minting kernel kinds into a corpus or the store root | operator (world configuration; tier at invocation); an orchestrator may choose a lower tier | the kernel writer's permit, bound in the endpoint and checked at every act (`permit-exceeded`); the closing check's interval and ledger comparison | enforced: the tier (envelope §5, §9) |
| **unattended operation** | an actor running with no person watching | operator (invocation; crew policy's `unattended` flag beneath) | the envelope as a whole: the sandbox proven twice, the lease, the seal, the kill switch, the dispositions; `unwired` whenever a guard cannot see | enforced for science runs; development actors wait on autonomy-d5c1cb |
| **model spend** | requests to a provider, which models, and how much | operator (the route; the allowance's limits); an orchestrator or policy may set a lower budget | the model proxy's admission point, where autonomy-9e8a43's allowance check joins (envelope decision 13) | the route is enforced; the allowance is the next class |
| **credential use** | any use of an operator secret | operator; never delegated below the proxy | the proxy's custody: the credential is outside the actor's filesystem, environment and process; the denied set holds the file and `<config>` | enforced (decision 13) |
| **network egress** | reaching any destination | operator (the route) | the actor's own network namespace, whose only listener is the route's; the proxy's body and header checks | enforced (decision 13) |
| **publication** | `publish` acts; anything that leaves the operator's custody for a commons | operator, in person | `publishes` is refused at open; the publish permit exists only on the interactive path under a full permit | attended, always (governing §6, envelope §5) |
| **host changes** | writes outside the run: a push, a merge, a PR, a service, a global tool or configuration, a repointed launcher | operator, in person | inside the envelope: the denied set, no host network, no credential, so the effect is unavailable, not detected; for development actors, autonomy-d5c1cb makes pushes and host metadata unavailable at the boundary; in an attended agent session: the operator's instructions, which are not mechanical | attended; unavailable inside the envelope |

Two rules hold across the table.

**Prevention, not detection.** An effect that leaves no trace in what the closing check
reads (a push, a spend, a host change, a credential used elsewhere) cannot be
quarantined after the fact, so it is made unavailable at the boundary (brief §3). A
check that finds a breach afterwards is evidence, never enforcement: crew's digests of
user files are observations for a person (crew §5.4), and the contract never lists
them as an enforcement point.

**The boundary is the one the constrained party cannot reach around.** A tool hook, an
allowlist in the actor's own process, an environment variable it can unset, or a
configuration it can rewrite is a policy decision point for feedback and precise
denials (§8), never the boundary (autonomy-9e8a43's statement of the same rule; pi's
own security guide, cited in crew §4.3). The enforcement points above are a kernel
check in another process, an operating-system namespace, or a proxy in a sandbox of
its own.

What is deliberately absent from the table: task state (a gate's business, out of
scope), and the interactive session's own writes. A person at the interactive launcher
holds a full permit (governing §5.2); that is the operator acting, not a grant.

## 6. Staged consequential effects

An effect in an attended class is still mostly preparable. The thesis's staging
(assess, prepare, canary, approve, cut over, verify, roll back) is how the contract
lets an actor do the work without holding the consequence:

- **Unattended stages:** assess and prepare. An actor may draft a publication's
  content, build a candidate, compute a diff, write a proposal. All of it lands in
  places the envelope already holds (scratch, a written chain under its tier, a
  quarantined result).
- **Attended stages:** approve, cut over, and roll back. Each is the operator's act
  under their own identity, and each is a separate approval: canary proof does not
  imply cutover authority, and cutover does not prove health (the thesis's vacuum
  example).
- **Verify** may be either, and its result is evidence for the next approval, never
  the approval.

So the development mode's `quarantined` holds a result and blocks its promotion
(brief §4): "no merge, no close" is cut over and the task's closing gate kept attended.
crew's "nothing an attempt produces is merged, pushed or closed without the user"
(crew §4.3) is the same rule from the orchestrator's side.

## 7. Gates, approval surfaces and the issuer

### 7.1 A gate authorizes the next state, and nothing else

This is ops §5.5, kept whole. A flow gate's record (`gate: designed`, `gate:
verified`, a review verdict bound to a tree) is read by `flow-state` and by the
person advancing the task. No enforcement point in §5 reads a gate record, and none
ever will: a gate is prose plus a hash in a task note, in a repository the actor may
be able to write. A class design that proposes reading a gate as a grant is refused
by this contract.

### 7.2 An approval surface carries decisions

A surface (a terminal, the desktop, relay's inbox on a phone) carries a decision from
a person to an asker, with the surface's provenance (relay §4.3's `surface`, and
`artifactRevision` for what the person saw). What the decision *does* is the asker's
question, judged under this contract:

- an answer to a `clarification` or `artifact-review` question settles what the asker
  does next, within the authority it already holds;
- an answer to an `authorization` question records that a person said yes or no. It
  grants nothing (decision 3). relay accepts such an answer only from a local
  surface and lets a remote surface defer or decline (relay §4.3).

An asker that holds no grant for an effect does not gain one by asking: an actor in
a `coordination` run that is told "yes, publish" by any surface still has no
`publish` permit, and the kernel refuses the act. The question was a gate-shaped
thing asked of a person; the refusal is the enforcement point doing its job. The safe
next action is for the asker to leave the effect to the operator (§6).

### 7.3 A future path: an approval that asks an issuer for a grant

Decision 3 leaves a door: an authenticated approval through relay may one day *ask
autonomy to issue* a bounded grant, with relay carrying only the decision. The
contract fixes what that path must look like before anyone builds it:

1. **The request names the grant's parts** (§3) in full, including the receipt and
   rollback, and the person answers that request, not a free question.
2. **The answer binds to the request's revision.** An answer to an earlier text of the
   request is stale and refused, as relay already does for artifacts.
3. **The surface is authenticated.** relay's local socket takes `surface` as a
   declared origin, not proof (relay's detached-ask design, 2026-10-24), and its HTTP
   guard assigns phone or desktop from the path. Until a surface proves the person's
   identity to the issuer, no remote answer reaches this path, local answers stay
   under 7.2, and the whole path waits.
4. **The issuer decides.** autonomy reads the answer and its provenance and issues, or
   refuses, under its own ceiling; relay issues nothing, stores nothing that an
   enforcement point reads, and cannot widen what autonomy would have issued.
5. **The grant is still an instance of §3 and §5:** it has an enforcement point, a
   receipt and a lifetime. "The person approved it on the phone" is a part of the
   receipt, never the whole of the grant.

Nothing here is built. The first consumer that wants it writes the class design.

## 8. Decision points and refusals

Every enforcement point refuses with a code, and the contract requires three things of
each code: it names the class and the limit crossed, it is stable enough to test
against, and the refusal says the safe next action where one exists. One decision
point per enforcement point; a request is decoded into a typed operation there and
judged against the grant (the thesis's "encode settled boundaries mechanically").

The codes that exist today, by class:

| class | where | codes |
|---|---|---|
| governed writes | `tiers` at open; the kernel writer at each act; the closing check | `publishes-unattended`, `mints-empty`, `unknown-kind`, `route-not-admitted`, `family-unreachable`, `routes-unexpected`, `unknown-tier`; `permit-exceeded`, `run-sealed`; `permit-mismatch`, `actor-mismatch`, `entry-foreign` |
| unattended operation | step 2; steps 3–7; the seal | `lease-below-floor`, `orphaned-run`, `stdio-refused`; `baseline-*`, `endpoint-unavailable`, `sandbox-unproven`, `egress-unproven`; `seal-timeout`, `orchestrator-lost` |
| model spend, credential use, egress | step 2; the proxy | `route-unknown`, `route-invalid`, `credential-unavailable`; the proxy's per-request refusals (`route-closed`, and decision 13's body, header and path refusals) |

A class design adds its codes to this catalog and to a verification row with a
negative arm, as the envelope's rows do. Where a refusal has a safe next action, the
message names it: `publishes-unattended` says that publication is the operator's;
`permit-exceeded` names the tier that would admit the kind; `route-closed` names the
run's close.

## 9. The tier, recast as the contract's first instance

Envelope §11 maps a tier onto the parts. The contract restates it with the chain and
the enforcement point filled in, so that the next class has a worked example.

| part | the tier |
|---|---|
| identity | operator: the person whose world configuration names the corpora; orchestrator: the program that ran `autonomy run`; actor: `session:<id>`, set by the endpoint, fresh per run |
| operation and resource | the permit (kinds, routes, families) over the written chains named by genesis and tip in `baseline.json`; with a route, the route's operations and models |
| scope | the claims on the written chains; the sandbox's denied set and binds; path-input confinement by descriptor; a network namespace whose only way out is the route's listener |
| lifetime and revocation | the lease, held by the endpoint and the proxy, renewed by the orchestrator and never by the actor; `run stop`, EOF and SIGTERM seal and close the route; the orchestrator's wall-clock bound; editing a route or credential affects later runs only |
| approval | the invocation, under configuration the operator owns; a lower tier than the ceiling is a narrowing the orchestrator may make; `publishes` is not approvable unattended by anyone |
| audit receipt | `baseline.json` (tier, permit, chains, binds, route digest, lease) before the actor starts; `events.jsonl`; the session ledger; `egress.jsonl`; `seal.json`; `disposition.json`; none rewritten, none bound into the sandbox |
| rollback | held, not undone: a `quarantined` run lists its members and effects for the operator; `unwired` says the guard could not see |
| enforcement point | the kernel writer's permit at every act; the closing check; the sandbox proven statically and by probe |
| decision point and codes | §8's governed-writes row |

Two things the recasting makes visible:

- **The tier is a grant to the actor, approved by the orchestrator's invocation, under
  the operator's configuration.** All three hops are present. The receipt records the
  tier and the route digest, so the hop from orchestrator to actor is auditable; the
  hop from operator to orchestrator is the limit stated in §4.
- **The budget allowance (autonomy-9e8a43) fills the same table.** Its identity is the
  run's; its operation is a model request; its resource is the allowance's pool; its
  scope is the proxy's admission point; its lifetime is the run's or the pool's; its
  revocation is the route's close; its approval is the operator's allowance
  configuration, which an orchestrator may lower; its receipt is `egress.jsonl` with
  the admission decision per request; its rollback is held (a run at its allowance
  stops with its disposition recorded, autonomy-9e8a43). That design fills in the
  blanks and names its codes; this contract only shows that the table closes.

## 10. Consumers

| consumer | takes from this contract | may not |
|---|---|---|
| **crew's policy grant** (crew §4.2–4.3; crew-799319) | the intersection rule of §4; the enforced-or-advisory test of §5; the receipt identity as its autonomy snapshot | mark a limit enforced without an enforcement point in §5; widen a run beyond the operator's configuration; treat a successful review as a grant |
| **relay's authorization class** (relay §4.3; relay-f58531) | §7.2: local-only, grants nothing; §7.3's conditions for the future path | store or deliver anything an enforcement point reads; authenticate a surface by declaration |
| **flows' gates** (ops §5.5; flows-912ac5) | §7.1: a gate authorizes the next task state only | be read by any enforcement point; become the record of an `authorization` answer |
| **the budget allowance** (autonomy-9e8a43) | §9's pre-filled table; §8's requirement for codes with a safe next action; §5's admission point | enforce in the actor's process; account without the receipt |
| **the development mode** (autonomy-d5c1cb) | §5's host-changes row and §6's staging: pushes and host metadata unavailable, `quarantined` holds and blocks promotion, acceptance separate from the boundary verdict | infer a clean boundary from a worktree diff; let crew vouch for its own boundary |
| **the loop** (sub-project 7) and any unattended orchestrator | §4's limit: it is the consumer that makes the operator → orchestrator hop mechanical | run under the operator's full ceiling by default |

## 11. Approaches

Three ways to settle this were considered.

- **A. A contract, with classes enforced one at a time, and the tier as the first
  instance.** The document states the parts, the chain, the classes and the
  boundaries, and each class design fills the table and cites it. Trade-off: nothing
  new is enforced by this document alone, and the operator → orchestrator hop stays a
  stated limit until a consumer needs it. **Taken**, by the user's decision 1, and
  because the two consumers in flight (the allowance and the development mode) each
  need a boundary of their own kind, not a shared service.
- **B. A grant mechanism now:** a grant record format, a store and a CLI (`autonomy
  grant …`) that every class consumes, with the tier migrated onto it. Trade-off: it
  would give one receipt shape and one revocation path, but no consumer has asked for
  a grant that the envelope's own records do not already carry, and a service that
  issues grants is a new boundary to prove. Rejected by decision 1; §7.3 and §4's
  limit name the triggers that would bring it back.
- **C. An amendment to the envelope spec** holding the same content. Trade-off: one
  document, but the envelope is the science run's design, and this contract binds
  consumers outside it (crew, relay, flows) and effects the envelope never sees
  (publication, host changes). Rejected; envelope §11 already cites this document as
  its companion.

Within A, one choice is mine: the parts of a grant are a checklist each class fills in
its own records, not a serialized record of their own. The tier's receipt is
`baseline.json` and the run directory, crew's is its attempt record, and the
allowance's will be `egress.jsonl`. A shared record would be approach B by another
name.

## 12. Verification

This document is a contract, so its verification is partly a checklist that reviewers
apply to class designs and partly rows that the code already makes or will make. Rows
marked *(pending)* land with the plan that builds the behaviour they test.

| row | claim | test | negative |
|---|---|---|---|
| A1 | a class design is complete only when it fills §3's seven parts, names its enforcement point under §5's two rules, and lists its codes under §8 | review checklist, applied to autonomy-9e8a43's and autonomy-d5c1cb's designs before approval | a design that leaves a part blank without a written reason is sent back |
| A2 | the tier fills §9's table from existing records | every cell of §9 names a record or mechanism that envelope §5–§9 and §12 already test (rows E1, E4–E6, E7, E8, E10, E21, E22) | a cell that names nothing testable is a gap in this document |
| A3 *(pending, Plan B2)* | an actor that invokes `autonomy run` inside its sandbox gains nothing (§4): it is refused before any run directory exists on the host and can open no session | under real `bwrap`, an actor whose argv runs the same `autonomy` package under `python3 -I` with `--tier coordination -- true`: exit 2 `runtime-dir-unset` (the environment is cleared), no run directory on the host, nothing on the host's report fd; the same with `--model-route <name>` exits 2 `route-unknown`; with the actor exporting `XDG_RUNTIME_DIR`, `XDG_STATE_HOME` and `XDG_CACHE_HOME` under scratch, the nested run allocates there, reaches step 3 at most and closes `unwired` (`baseline-unavailable`), because `science` and the chains are denied, and the host's `<state>/runs/` gains no directory | a sandbox that binds the host's `$XDG_RUNTIME_DIR`, `<state>` or `<config>` (a test hook) lets the nested run allocate on the host or find a route |
| A4 | an `authorization` answer from any surface changes no permit | a run at `coordination` whose actor receives an `authorization` answer of yes over its stdio and then requests a `publication` kind is refused `permit-exceeded`; the answer appears in no run record | this is E7's permit check reached from the surface side; a run opened at a wider tier admits the kind, which is the tier's business, not the answer's |
| A5 | crew's attempt record marks a limit enforced only for a run under an enforcement point in §5 | crew's tests (crew-owned): an attempt without an autonomy run records every limit advisory; one under `autonomy run` records the tier, route, lease and sandbox enforced and the rest advisory, with the run id as the snapshot | an attempt that records its environment allowlist as enforced fails |

A4's actor-side half needs no new code: the answer is bytes on stdio (decision 12),
and the kernel's refusal is E7's. A5 is filed to crew with this document (§13).

## 13. Delivery

This document asks for no code of its own. It lands as a design spec here, and it
names what each consumer does with it:

1. **This repository:** row A3 joins Plan B2's rows (autonomy-f6efe8), since it needs
   a sandboxed actor that can reach the vendored CLI and a host-side check of the run
   directory. Row A4's assertion joins E7 when the endpoint exists. The README's usage
   section gains a sentence pointing at this contract when the next class lands; no
   behaviour changes now.
2. **autonomy-9e8a43:** fills §9's second table and §8's codes for the allowance.
3. **autonomy-d5c1cb:** fills §5's host-changes row for development actors and keeps
   §6's split between the boundary verdict and crew's acceptance.
4. **crew:** row A5 and the enforced-or-advisory test of §5, filed as a task citing
   this document; crew-799319 records the route and run id as the autonomy term.
5. **relay and flows:** nothing to build; §7 restates their stated boundaries with the
   reason. relay-f58531's and flows-912ac5's designs are not amended by this document.

## 14. Alternatives rejected

- **Grants carried in requests** (a token or permit in each call). Governing §5.2
  rejects it for the permit, and the reason generalizes: whatever the actor can
  carry, it can alter. The identity and the grant are bound at the enforcement point,
  outside the actor.
- **Capability tokens (macaroons, signed caveats) as the grant shape.** They attenuate
  well, but their verification would sit in the actor's reach or need a service that
  is approach B, and the stack's enforcement points already have a stronger form: a
  permit in another process, a namespace, a proxy.
- **An inbox answer as a grant for low-consequence classes.** Even a small class
  would need the surface authenticated and the answer bound to a request with all of
  §3's parts; that is §7.3, and it is not smaller for a small class.
- **A gate record as the approval part of a grant.** A gate lives in a task note the
  actor's repository may hold; reading it would put the approval inside the
  constrained party's reach.
- **A crew-owned sandbox or a crew-computed ceiling.** The runner would grant its own
  limits (crew §10 decision 1); under this contract the term that binds is the one
  with an enforcement point the worker cannot reach, and that is autonomy's.
- **One policy file for every class.** The classes have different owners of their
  enforcement points (the kernel, the sandbox, the proxy, the operator in person), and
  one file would either describe what it cannot enforce or move every mechanism behind
  one reader. Each class keeps its configuration where its enforcement point reads it,
  all of it under the operator's ownership rule in §4.
- **Reading a worktree diff as proof that no host change happened.** Prevention, not
  detection (§5): the effects that matter leave no trace there.
