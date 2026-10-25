---
id: autonomy-1aac03
title: "Design autonomy's authorization contract: who may grant what, how delegation narrows it, and where each limit is enforced"
status: doing
priority: 2
size: m
complexity: high
process: planned
owner: authorization-contract
created: 2026-10-04T10:54:36Z
updated: 2026-10-25T22:59:23Z
started: 2026-10-25T21:14:55Z
depends: []
parent: autonomy-d9adef
tags: []
source: ops-cb9749
agent: claude-code
spec: docs/specs/2026-10-25-authorization-contract-design.md
---

Why: designs across the stack name autonomy as the owner of authority to act: spending, publication, host changes, unattended operation (ops docs/specs/2026-10-03-agent-layer-split-design.md §5.5 and §9; relay's typed-interaction spec §4.3; crew core design §4.2-4.3 and §10 decision 1; goal ops-cb50a8). The only grant autonomy defines today is a tier on a science run (envelope spec §11). The agent-layer split handed autonomy this boundary (source ops-cb9749).

Decided by the user, 2026-10-15 (brief §4):
1. Contract first, enforcement class by class. The contract states who may grant what, how delegation narrows authority, and where each limit is enforced. The tier is the first enforced class and the budget allowance (autonomy-9e8a43) the next. No general grant service until a consumer needs one.
2. crew's grant sits beneath an autonomy grant: effective permission = autonomy ceiling ∩ the user's crew policy ∩ the kind's request. crew narrows and never enlarges. The user, as operator, owns the policy, outside actor-writable storage, and each attempt records its snapshot.
3. A relay answer grants nothing for now. The contract separates the approval surface from the issuer: a future authenticated approval through relay may ask autonomy to issue a bounded grant, with relay only carrying the decision. Running an autonomy command never establishes authority by itself: an orchestrator needs delegated permission beforehand, and an actor that invokes the CLI gains nothing.

Done: a design spec under docs/specs/, reviewed and approved by the user. It defines the parts of a grant (shape from harness-engineering's authority thesis, see the note of 2026-10-11: identity, operation and resource, scope, lifetime and revocation, approval, audit receipt, rollback); the issuers and how delegation narrows from operator to orchestrator to actor; the consequence classes (unattended operation, spend, publication, host changes), each with its enforcement point or a statement that it stays attended; the distinction between a gate, an approval surface and a grant; and the tier recast as the contract's first instance. A plan is needed only for the code the spec asks for. Consumers named: crew's policy grant, relay's authorization class, flows' gates, the budget allowance.

Where: brief docs/notes/2026-10-15-authority-and-development-actors-brief.md; envelope spec §5 and §11; the documents above.

## Notes

- 2026-10-11T17:54:14Z (main): Related: ops-cb50a8 (typed exchanges; phone inbox). A typed question answered from a phone is still a gate, not an authorization: relay-f58531's answer kind must not become the way spend, publication or host changes are granted; this idea's boundary applies to it.
- 2026-10-11T20:44:08Z (main): 2026-10-11: shape to take from harness-engineering's authority thesis (~/software/harness-engineering/docs/authority/README.md): an authority grant names identity, operation and resource, scope, lifetime and revocation, approval, audit receipt and rollback; consequential effects are staged (assess, prepare, canary, approve, cut over, verify, roll back); wrong actions are made unavailable by one policy decision point returning a precise denial and the safe next action. Companion of the envelope design autonomy-250f4d: a tier is an authorization, a gate never is.
- 2026-10-15T10:40:03Z (main): scope: briefed; parented under goal autonomy-d9adef; envelope §11 already maps a tier onto every grant part, and ops split §5.5, relay §4.3 and crew §4.2-4.3 each state the gate-is-not-a-grant boundary without a mechanism; framed contract-first (i) vs mechanism (ii), lean i with the budget allowance in autonomy-9e8a43 as the first mechanical class; waits on user questions: contract or mechanism, whether crew's policy grant is an autonomy grant, whether a relay authorization answer can ever grant; brief: docs/notes/2026-10-15-authority-and-development-actors-brief.md
- 2026-10-15T10:51:31Z (main): scope: scoped; the user settled the brief's three questions on 2026-10-15 (contract first with enforcement class by class; crew's grant beneath an autonomy ceiling; a relay answer never grants, and the approval surface is distinct from the issuer); promoted to todo as the contract design, P2, m, high, planned; checked against the envelope spec at 409dae7, crew core design revision 9 and relay's typed-interaction spec
- 2026-10-25T21:14:55Z (main): started
  provenance: {"harness_session":"claude-code:f55d5b38-7219-4d59-ae77-05c40bbf0d6f","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-25T21:15:11Z (authorization-contract): resumed
  provenance: {"harness_session":"claude-code:f55d5b38-7219-4d59-ae77-05c40bbf0d6f","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-25T21:23:44Z (authorization-contract): Spec drafted at docs/specs/2026-10-25-authorization-contract-design.md (8db5593 on authorization-contract, worktree .worktrees/authorization-contract). Shape: vocabulary (gate, approval surface, grant); seven parts of a grant; operator > orchestrator > actor with part-by-part narrowing and the stated single-user-host limit; a class table (governed writes, unattended operation, spend, credential, egress, publication, host changes) with enforcement points; staging; relay's future grant-request path with conditions; refusal-code catalog; the tier recast; consumers; rows A1-A5. Asks for no code; A3 joins Plan B2. Builder check and fresh-context spec review round 1 dispatched next.
- 2026-10-25T21:30:22Z (authorization-contract): review: spec round 1 — verdict: revise; findings: Important 7, Minor 7; reviewer: claude-code/claude-fable-5-1
- 2026-10-25T21:33:57Z (authorization-contract): Builder check (fresh subagent, 0ae2f43) asked five questions; none needs the user. Rulings written into revision 26e4b17: (1) the spend class has two admission points, the proxy's admit and the endpoint's dispatch of run acts, from autonomy-9e8a43's own criterion; (2) crew's three enforced limits judged by one test (outside the worker's reach): wall-clock stays enforced, token and dollar ceilings advisory while the credential is in the trajectory, the environment allowlist is a starting state; handed to crew as an amendment to review there, not applied from here; (3) autonomy-9e8a43's first run is an operator invocation whether typed or started by crew supervised, so the operator-to-orchestrator manifest class is due before the first start no person makes; (4) once the allowance class exists a routed run names an allowance or is refused at step 2, the allowance lives under <config> and is digested into baseline.json, and the design states its unit and overrun; (5) no code registry or checklist document: §8 maps classes to where their codes live, and the review dispatch cites §3, §5 and §8. Calls 2 and 4 are mine and flagged for the user's review.
- 2026-10-25T21:42:28Z (authorization-contract): review: spec round 2 — verdict: revise; findings: Important 2, Minor 5; reviewer: claude-code/claude-fable-5-1
- 2026-10-25T21:49:08Z (authorization-contract): review: spec round 3 — verdict: revise; findings: Important 1, Minor 5; reviewer: claude-code/claude-fable-5-1
- 2026-10-25T21:53:16Z (authorization-contract): review: spec round 4 — verdict: accept; findings: Minor 1; reviewer: claude-code/claude-fable-5-1
- 2026-10-25T21:53:29Z (authorization-contract): parked (waiting on user, review): User reviews docs/specs/2026-10-25-authorization-contract-design.md (revision a1c9664 on branch authorization-contract, worktree .worktrees/authorization-contract), including the two calls flagged as mine: crew's token and dollar ceilings relabelled advisory while the credential is in the trajectory (§4, handed to crew as an amendment), and a routed run naming an allowance or being refused once the allowance class exists (§9). On approval: mark the spec approved, merge authorization-contract into main (personal profile allows a local merge), file the crew amendment task citing §4 and §13 item 4, add row A3 to Plan B2 (autonomy-f6efe8) and row A4 to the science slice, then tasks done. No plan is needed: the spec asks for no code.
  provenance: {"harness_session":"claude-code:f55d5b38-7219-4d59-ae77-05c40bbf0d6f","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-25T22:44:27Z (authorization-contract): resumed
  provenance: {"harness_session":"claude-code:f55d5b38-7219-4d59-ae77-05c40bbf0d6f","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-25T22:44:28Z (authorization-contract): review: spec round 5 — verdict: revise; findings: Important 1, Minor 2; reviewer: codex/gpt-6-astra
- 2026-10-25T22:49:44Z (authorization-contract): review: spec round 6 — verdict: revise; findings: Important 1, Minor 4; reviewer: claude-code/claude-fable-5-1
- 2026-10-25T22:54:14Z (authorization-contract): review: spec round 7 — verdict: revise; findings: Important 1, Minor 2; reviewer: claude-code/claude-fable-5-1
- 2026-10-25T22:57:17Z (authorization-contract): review: spec round 8 — verdict: revise; findings: Important 1, Minor 2; reviewer: claude-code/claude-fable-5-1
- 2026-10-25T22:59:09Z (authorization-contract): review: spec round 9 — verdict: accept; findings: Minor 2; reviewer: claude-code/claude-fable-5-1
- 2026-10-25T22:59:23Z (authorization-contract): parked (waiting on user, review): User re-reviews docs/specs/2026-10-25-authorization-contract-design.md (revision fb322df on branch authorization-contract, worktree .worktrees/authorization-contract) after the round-5 corrections: crew's wall-clock limit reclassified as a cooperative timeout, advisory under a same-account worker (§4, A5, §13 item 4); A4 compares proposition under mints and keeps publish always refused; §14's token rejection now rests on no consumer needing the machinery. On approval: mark the spec approved, merge authorization-contract into main locally, file the crew amendment task citing §4 and §13 item 4 (two rows relabelled: the ceilings and wall-clock time), add row A3 to Plan B2 (autonomy-f6efe8) and row A4 to the science slice, then tasks done. No plan: the spec asks for no code.
  provenance: {"harness_session":"claude-code:f55d5b38-7219-4d59-ae77-05c40bbf0d6f","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
