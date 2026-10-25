# Authorization contract — design

**Date:** 2026-10-25
**Status:** draft, for the user's review. Four fresh-context agent review rounds
preceded it: round 1 found 7 Important and 7 Minor, round 2 found 2 Important and 5
Minor, round 3 found 1 Important and 5 Minor, round 4 accepted with 1 Minor; all are
addressed in this text. A builder check between rounds 1 and 2 asked five questions,
answered in §4, §5, §8 and §9.
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
- **Publication's own design.** It stays attended (governing §7.1 states the rule;
  §6.1 defines the act; envelope §5 refuses the tier). This document only places it.

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
   An effect that cannot be held or undone is never left to the closing check. It has
   one of three dispositions, named by its class (§5):
   - **unavailable at the boundary:** a push, a host change, a credential used outside
     the proxy. Nothing to roll back, because the effect cannot happen;
   - **bounded before the effect:** a spend. An admission point decides each unit
     before it is caused, exhaustion stops the run with its disposition recorded, and
     the receipt records every admission. What was admitted is spent and stays spent;
     the bound is the rollback;
   - **attended and staged:** a publication, a cutover. The operator's own act (§6).

A grant missing a part is not narrower, it is unbounded in that part. The tier
refuses an empty mints map and a non-reachable family rather than defaulting them
(envelope §5 gives its own reasons: an empty map is `coordination` by another name);
read under this contract, each refusal keeps a part from being filled by a default
nobody named.

## 4. Issuers and delegation

There are three principals, in a fixed order. Each holds a ceiling, issues grants no
wider than it, and the last issues none.

**The operator** is the person who owns the host, the credentials, the corpora and
the policy. The operator is the root of every grant and the only principal that can
make an attended effect. The operator's authority is expressed in two forms:

- **Configuration the operator owns**, kept where no actor and no orchestrator can
  write it: the world configuration (which corpora exist and which are denied), the
  model routes under `<config>/routes/` and each route's credential file (envelope
  decision 13), and crew's `policy.toml` under the user's configuration directory,
  outside every repository and every attempt's workspace (crew §4.2). The envelope
  adds `<config>` and every credential file to the denied set, so this configuration
  is unreachable from inside a run by construction.
- **Invocation**: running `autonomy run` with a tier, a route and a lease (chosen
  above autonomy's own floor, which is a constant of the code, not configuration), or
  running crew on a kind. An invocation is an approval (§3 part 5) only when the operator makes it, or
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
inside its sandbox is refused before a run directory exists on the host, in the
order step 2 checks. The tier, lease and stdio checks come first and pass for a
nested invocation that inherits the actor's stdio; then `runtime-dir-unset`, the first
check that reads the environment, which the sandbox clears; if the actor exports an
absolute `XDG_RUNTIME_DIR` itself, `route-unknown` for any route the operator
configured, because `<config>` is denied; without a route, `allocation-failed` unless
the actor also points the state and cache directories into scratch. A route the
actor writes under a scratch `XDG_CONFIG_HOME`, with a scratch credential file,
passes step 2's checks on its own bytes and buys nothing: the run closes at step 3 or
4, before step 9 would start its proxy, and that proxy would hold only the actor's
own credential inside the actor's own network namespace, whose only way out is the
outer route's listener. A nested run that allocates under scratch opens no session of
its own: the `science` it can reach either runs in handle mode under the outer
session's permit (envelope §4), where `science serve --run` is refused `handle-mode`,
or, with the handle variables unset, from host configuration the sandbox does not
bind (E19's negative); either way it has no endpoint, and the chains are denied to it
as to any actor. It closes `unwired`, or is refused at step 2 by a world check B2
places there, with no run directory on the host. §12 row A3 tests each step.

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
each limit **enforced** or **advisory** (crew §4.3). Under this contract one test
decides the mark: a limit is *enforced* when its enforcement point is outside the
worker's reach, whether that point is the envelope's (§5) or crew's own runner. Applied
to crew's first slice, which marks three limits enforced (crew §4.3, §6.3):

- **wall-clock time per scope is a cooperative timeout, advisory until its deadline
  leaves crew's process.** The deadline is a timer in crew's own process (crew's
  `src/scopes.ts`, `setTimeout` around the scope's stop); systemd receives only a
  stop timeout, which bounds the stop, not the run. A worker under the same account
  can `SIGSTOP` crew and keep running inside its existing scope past the deadline,
  without the scope escape crew already marks advisory. It becomes enforced when the
  deadline leaves crew's process: a unit property such as `RuntimeMaxSec` on the
  scope, which the user manager applies whatever happens to crew (on a single-user
  host still within the account's reach, as the limit below states), or the
  envelope's lease under `autonomy run`, which the sandbox's pid namespace keeps out
  of the actor's reach.
- **the token and dollar ceilings are advisory while the credential is in the
  trajectory.** crew meters pi's own usage report after each turn; a worker holding
  the key can call the provider directly, outside the meter. The ceilings become
  enforced only under a run whose requests all pass the proxy, where the allowance
  admits each one (§5's spend row). crew's "one turn can run past a ceiling" (§6.3)
  is the bounded-overrun shape §9 asks the allowance design to decide for itself.
- **the environment allowlist is an enforced starting state and bounds no reach.** It
  is scope (§3 part 3): the worker starts with exactly that environment, and can still
  read every path and host the account can. It is recorded as what it is, not as a
  limit on effects.

Everything else crew does (its git and `gh` speed bumps, its `tasks` shim, its
post-hoc digests) is advisory, whatever it prevents in practice. So in the first
slice as built, the two limits crew marks enforced on the worker's run, wall-clock
time and the ceilings, are advisory under a hostile worker; the third, the
environment allowlist, is enforced as a starting state and bounds no effect. This
relabels two rows of crew §4.3's table (the
token and dollar ceilings, and wall-clock time) and is handed to crew as an
amendment to review there, not applied from here (§13). The attempt's snapshot of the
autonomy term is the run's receipt identity (its run id and the digest of
`baseline.json`), not a restatement.

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
not this one (decision 1). The ordering rule for autonomy-9e8a43 follows: its first
run is an operator invocation whether the operator types it or crew starts it in its
supervised mode, where the user starts every attempt (crew §4.3); the manifest class
becomes due before the first start no person makes, and not before.

## 5. Consequence classes and their enforcement points

Each class is a kind of effect with its own consequence and recovery. For each, the
table gives who issues the grant and from which ceiling, the enforcement point, what
the approved designs say, and what runs today. The last two columns differ because
every science run still closes `unwired` before its actor starts, until Plan B2 lands;
a reader who needs to know where a limit is enforced *now* reads the *built* column.
"Attended" means no grant exists and none is planned: the effect is the operator's own
act.

| class | effect | issuer and ceiling | enforcement point | designed | built |
|---|---|---|---|---|---|
| **governed writes** | minting kernel kinds into a corpus or the store root | operator (world configuration; tier at invocation); an orchestrator may choose a lower tier | the kernel writer's permit, bound in the endpoint and checked at every act (`permit-exceeded`); the closing check's interval and ledger comparison | the tier (envelope §5, §9, approved) | the tier's data and refusals (`tiers`, E1) and the closing comparison (E2, E17); the endpoint and kernel arms (E7, E19) wait on Plan B2 (autonomy-f6efe8) and the science and beliefs slices |
| **unattended operation** | an actor running with no person watching | operator (invocation; crew policy's `unattended` flag beneath) | the envelope as a whole: the sandbox proven twice, the lease, the seal, the kill switch, the dispositions; `unwired` whenever a guard cannot see | science runs (envelope, approved); development actors wait on autonomy-d5c1cb | the launch side (Plan B1: steps 1–2, the sandbox, the gate, the report fd; E1, E4–E6, E20's launch arm); every run still closes `unwired` at step 3 until B2 |
| **model spend** | requests to a provider, which models, and how much; kernel analysis jobs the run starts | operator (the route; the allowance's limits); an orchestrator or policy may set a lower budget | two admission points, one per road to a spend: the model proxy's `admit`, where autonomy-9e8a43's allowance check joins (envelope decision 13), and the endpoint's dispatch of a `run` act for analysis jobs, which the same allowance must count (autonomy-9e8a43's criterion names both) | the route (decision 13, approved); the allowance is the next class | the route's checks and the proxy's refusals (the egress plan, E21–E22 launch arms); no allowance |
| **credential use** | any use of an operator secret | operator; never delegated below the proxy | the proxy's custody: the credential is outside the actor's filesystem, environment and process; the denied set holds the file and `<config>` | decision 13, approved | the proxy and its credential checks (E21–E22 launch arms); the full-run arms wait on B2 |
| **network egress** | reaching any destination | operator (the route) | the actor's own network namespace, whose only listener is the route's; the proxy's body and header checks | decision 13, approved | the namespace, the listener, the probe's network check (E21–E22 launch arms) |
| **publication** | `publish` acts; anything that leaves the operator's custody for a commons | operator, in person | `publishes` is refused at open; the publish permit exists only on the interactive path under a full permit | attended, always (governing §7.1, envelope §5) | the refusal at open (E1) |
| **host changes** | writes outside the run: a push, a merge, a PR, a service, a global tool or configuration, a repointed launcher | operator, in person | inside the envelope: the denied set, no host network, no credential, so the effect is unavailable, not detected; for development actors, autonomy-d5c1cb makes pushes and host metadata unavailable at the boundary; in an attended agent session: the operator's instructions, which are not mechanical | attended; unavailable inside the envelope | the denied set and the network namespace (E4–E5, E21); development actors: nothing yet |

Two rules hold across the table.

**Prevention, not detection.** An effect that leaves no trace in what the closing check
reads (a push, a spend, a host change, a credential used elsewhere) cannot be
quarantined after the fact, so it is decided before it happens: made unavailable at
the boundary, or bounded at an admission point, by §3 part 7's dispositions (brief
§3). A check that finds a breach afterwards is evidence, never enforcement: crew's
digests of user files are observations for a person (crew §5.4), and the contract
never lists them as an enforcement point.

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
crew's rule that nothing an attempt produces is merged, pushed or closed without the
user (crew §4.3) is the same rule from the orchestrator's side.

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
   declared origin, not proof: the socket's mode is its only local authentication
   (relay §7.2), the HTTP guard sets `surface` from the request path and overwrites
   what a client sent (relay §7.3), and relay's detached-ask design (2026-10-24, a draft
   in relay's records) keeps it so. Until a surface proves the person's
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

This document keeps no registry of codes. Each class's codes are defined and tested
where its enforcement point lives, and the table below says where that is, with
representative codes so a reader can recognise the class. The envelope's own lists are
the catalogs for the classes it enforces: step 2's refusals (envelope §3), the closing
check's findings (§9) and decision 13's proxy refusals; the code's `closing.SEVERITY`
and the `TierRefused`, `RunRefused` and `SandboxUnproven` codes carry what is built.

| class | where the codes are defined and tested | representative codes (built unless marked) |
|---|---|---|
| governed writes | `tiers` at open (E1); the endpoint and kernel at declaration and at each act (E19, pending the science slice); the closing check (E2, E17) | `publishes-unattended`, `mints-empty`, `unknown-kind`, `route-not-admitted`, `family-unreachable`; `permit-exceeded` *(pending)*; `permit-mismatch`, `entry-foreign`, `chain-discontinuous`, `world-moved`, `basis-moved` |
| unattended operation | step 2 (E1); the static check and probe (E4, E5); steps 3–7 (pending B2) and the seal (pending B2 and the science slice); the closing check | `runtime-dir-unset`, `allocation-failed`, `lease-below-floor`, `stdio-refused`; `bind-overlaps-denied`, `bind-missing`, `probe-failed`; `orphaned-run`, `baseline-pending`, `baseline-raced`, `endpoint-unavailable` *(pending)*; `run-sealed` *(pending)*, `seal-timeout`, `seal-missing`, `orchestrator-lost` |
| model spend, credential use, egress | step 2's route and credential checks and the proxy (E21, E22 launch arms); the allowance *(pending, autonomy-9e8a43)* | `route-unknown`, `route-invalid`, `credential-unavailable`, `route-closed`, `egress-unproven`, `egress-lost`; decision 13's body, header and path refusals; the allowance's codes, to be named |

A class design names its codes in its own table, tests each in a verification row
with a negative arm as the envelope's rows do, and says for each whether the bound is
hard or admits a bounded overrun. Where a refusal has a safe next action, the message
names it: `publishes-unattended` says that publication is the operator's;
`permit-exceeded` names the tier that would admit the kind; `route-closed` names the
run's close. The completeness check of §1 is applied by citing this document's §3, §5
and §8 in the review dispatch for the class design; it needs no document of its own.
If the codes a class ships drift from its design, a reference document under `docs/`
is the remedy then, filed by that class.

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
  run's; its operations are a model request and an analysis job; its resource is the
  allowance's pool; its scope is the run's network namespace, whose only way out is the
  route's listener, and the endpoint's dispatch, so that no request and no job has
  another road; its enforcement points are the proxy's `admit` and the endpoint's
  dispatch of a `run` act; its lifetime is the run's or the pool's; its revocation is
  the route's close and the seal; its approval is the operator's allowance
  configuration, which an orchestrator may lower; its receipt is `egress.jsonl` with
  the admission decision per request, and the ledger for jobs; its rollback is bounded
  before the effect (§3 part 7): a run at its allowance stops with its disposition
  recorded. Three calls the contract makes for it, each mine and each open to that
  design's review:
  - **once the class exists, a routed run names an allowance** (its own, or a default
    the route's operator configuration carries), and a routed run with none is refused
    at step 2, because a spend with no amount is a grant unbounded in part 2. Until
    then, decision 13's `admit` stays as it is;
  - **the allowance lives where its admission point reads it**: operator configuration
    under `<config>`, read once at step 2 and digested into `baseline.json` like the
    route, so that an orchestrator's lowering is recorded and an actor cannot reach it;
  - **the design states its unit and its overrun**: `admit` sees a request's model and
    size before any response, so a token or dollar bound is either reserved up front or
    admits a bounded overrun by requests in flight, and the design says which, names
    the bound in its refusal code, and says what the first slice counts (per run, as
    crew §10 decision 3 leaves cross-run pooling to whoever schedules).

  That design fills in the rest and names its codes; this contract only shows that
  the table closes.

## 10. Consumers

| consumer | takes from this contract | may not |
|---|---|---|
| **crew's policy grant** (crew §4.2–4.3; crew-799319) | the intersection rule and the enforced-or-advisory test of §4; the receipt identity as its autonomy snapshot | mark a limit enforced when the worker can reach around its enforcement point; widen a run beyond the operator's configuration; treat a successful review as a grant |
| **relay's authorization class** (relay §4.3; relay-f58531) | §7.2: local-only, grants nothing; §7.3's conditions for the future path | store or deliver anything an enforcement point reads; authenticate a surface by declaration |
| **flows' gates** (ops §5.5; flows-912ac5) | §7.1: a gate authorizes the next task state only | be read by any enforcement point; become the record of an `authorization` answer |
| **the budget allowance** (autonomy-9e8a43) | §9's pre-filled table and its three calls; §8's requirement for codes with a safe next action and a stated overrun; §5's two admission points | enforce in the actor's process; account without the receipt; count model requests and leave analysis jobs uncounted |
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
| A2 | the tier fills §9's table from existing records | every cell of §9 names a record or mechanism that envelope §5–§9 and §12 already test: identity and approval E1, E7; operation E7, E19; scope E4–E6, E14, E15, E21; lifetime and revocation E9–E11, E20, E22; receipt E20 (the report lines match `disposition.json`), E21 (no credential in `baseline.json`), E22 (the recorded route digest); rollback E2, E17; the enforcement point E8, E19 | a cell that names nothing testable is a gap in this document |
| A3 *(pending, Plan B2)* | an actor that invokes `autonomy run` inside its sandbox gains nothing (§4): it is refused before any run directory exists on the host and can open no session | under real `bwrap`, an actor whose argv runs the same `autonomy` package under `python3 -I` with `--tier coordination -- true`: exit 2 `runtime-dir-unset` (the environment is cleared), no run directory on the host, nothing on the host's report fd; the same with `--model-route <name>` still exits 2 `runtime-dir-unset`; with the actor exporting an absolute `XDG_RUNTIME_DIR` under scratch and `--model-route <name>`, exit 2 `route-unknown` and no run directory anywhere, the refusal preceding allocation; with `XDG_RUNTIME_DIR`, `XDG_STATE_HOME` and `XDG_CACHE_HOME` all under scratch and no route, the nested run either is refused at step 2 by a world check B2 places there, or allocates under scratch and closes `unwired` at step 3 or 4 with no endpoint of its own (`baseline-unavailable` when its `science` read fails, or `endpoint-unavailable` when `science serve --run` is refused `handle-mode` by the CLI in handle mode); in both cases it opens no session and the host's `<state>/runs/` gains no directory; with all four XDG directories under scratch, an actor-written route and credential file, and `--model-route` naming it, step 2 passes on the actor's bytes, the run ends the same way, no proxy start is recorded, and the host's `<config>` and `<state>` are untouched | a sandbox that binds the host's `$XDG_RUNTIME_DIR`, `<state>` or `<config>` (a test hook) lets the nested run allocate on the host or load an operator route; one that lets the nested `science` run outside handle mode against bound host configuration and corpora (a test hook), with the outer run at `report-only` or the nested run naming a write corpus the outer run does not claim, so that `corpus-claimed` cannot mask the result, lets it launch an endpoint and open a session |
| A4 *(pending, science)* | an `authorization` answer from any surface changes no permit | a run at `coordination` whose actor receives an `authorization` answer of yes over its stdio and then runs a declared command minting `proposition` through the handle is refused before the body runs, and a body that lies is refused again at the act, `permit-exceeded` (governing §5.2; E19's refusal reached from the surface side); the same actor running a declared `publish`-class command is refused the same way; the answer appears in no run record | a run opened at `mints:{proposition: corpus-write}` admits the proposition, which is the tier's business, not the answer's, and still refuses the `publish`-class command, because no unattended tier admits the `publish` family (envelope §5); a test that drives the act without the declaration misses the first refusal |
| A5 *(crew)* | crew's attempt record marks a limit enforced only when its enforcement point is outside the worker's reach (§4) | crew's tests, after crew reviews §4's relabeling: an attempt without an autonomy run records wall-clock time and the token and dollar ceilings advisory, with the environment recorded as its starting state, until the scope carries a deadline the user manager applies on its own, outside crew's process; one under `autonomy run` with a route records the tier, route, lease and sandbox enforced, the ceilings enforced only once the allowance class exists, and the run id and `baseline.json` digest as the snapshot | an attempt that records a metered ceiling as enforced while the credential is in the trajectory, or wall-clock time as enforced while the deadline is a timer in crew's process, fails |

A4's actor-side half needs no new code: the answer is bytes on stdio (decision 12),
and the refusal is E19's, which waits on the science slice. A5 is filed to crew with
this document (§13).

## 13. Delivery

This document asks for no code of its own. It lands as a design spec here, and it
names what each consumer does with it:

1. **This repository:** row A3 joins Plan B2's rows (autonomy-f6efe8), since it needs
   a sandboxed actor that can reach the `autonomy` package and a host-side check of
   the run directory. Row A4 joins E19 when the science slice lands. The README's
   usage section gains a sentence pointing at this contract when the next class lands;
   no behaviour changes now.
2. **autonomy-9e8a43:** fills §9's second table, including the three calls made there,
   and names its codes under §8; its criterion's analysis jobs keep their admission
   point in the endpoint's dispatch (§5), which is a science slice that design orders.
3. **autonomy-d5c1cb:** fills §5's host-changes row for development actors and keeps
   §6's split between the boundary verdict and crew's acceptance.
4. **crew:** an amendment to crew core §4.3 and §6.3, filed as a task citing this
   document's §4: the token and dollar ceilings are advisory while the credential is
   in the trajectory, wall-clock time is advisory while its deadline is a timer in
   crew's process (a scope `RuntimeMaxSec`, applied by the user manager, would make
   it enforced against the worker, though not against the account), the environment
   allowlist is a starting state; row A5 follows it. crew-799319 records the route and the run's
   receipt identity as the autonomy term.
5. **relay and flows:** nothing to build; §7 restates their stated boundaries with the
   reason. relay-f58531's and flows-912ac5's designs are not amended by this document.

## 14. Alternatives rejected

- **Grants carried in requests** (a token or permit in each call). Governing §5.2
  rejects it for the permit: a request names a command and its inputs and nothing
  else, and the endpoint supplies the permit and the actor, so neither is ever
  caller-supplied. An unauthenticated grant the actor carries it can alter; an
  authenticated one is the next bullet. The identity and the grant are bound at the
  enforcement point, outside the actor.
- **Capability tokens (macaroons, signed caveats) as the grant shape.** They are
  sound: an authenticated token is verified at the endpoint, outside the actor, and a
  macaroon's caveats support the narrowing §4 asks of operations, resources, scope
  and lifetime. They are
  not taken because no current consumer needs their machinery (minting, caveat
  verification, key custody for the verifier) beyond what the stack's enforcement
  points already bind without a token: a permit fixed in another process, a
  namespace, a proxy. The endpoint-bound design is kept; a token scheme stays open
  for a consumer that needs delegation across hosts or processes the endpoint cannot
  see.
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
