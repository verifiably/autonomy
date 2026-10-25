---
id: autonomy-1aac03
title: "Design autonomy's authorization contract: who may grant what, how delegation narrows it, and where each limit is enforced"
status: doing
priority: 2
size: m
complexity: high
process: planned
owner: main
created: 2026-10-04T10:54:36Z
updated: 2026-10-25T21:14:55Z
started: 2026-10-25T21:14:55Z
depends: []
parent: autonomy-d9adef
tags: []
source: ops-cb9749
agent: claude-code
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
