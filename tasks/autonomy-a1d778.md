---
id: autonomy-a1d778
title: Design the closed anthropic-messages policy from the egress brief
status: doing
priority: 2
size: m
complexity: high
process: planned
owner: design/closed-messages-policy
created: 2026-10-29T09:02:18Z
updated: 2026-10-29T09:16:16Z
started: 2026-10-29T09:05:57Z
depends: [autonomy-d0387e]
parent: autonomy-3a06d3
tags: []
source: docs/notes/2026-10-18-egress-proof-gaps-brief.md
agent: codex
origin: agent
spec: docs/specs/2026-10-12-envelope-design.md
---

Why: autonomy-d0387e established the unchecked nested control positions and a finite supported-subset recommendation in research e8fdb3a, clarified in b76482d. The validator, route parser, README and decision 13 are unchanged from research baseline 7097495 at scope baseline 141f31a. Decision 13 currently permits operator-listed fields and server tool types; narrowing them requires a reviewed contract amendment. [ref:brief] contains the current/proposed matrix, pinned SDK provenance, precise proposed shapes and acceptance obligations. This is an agent-derived design follow-up, not approval to narrow the contract.

Decision to resolve: recommend finite key/value schemas at every admitted control object and refuse fallbacks at route load, including the server-selected default. Compare retaining broader operator-configured features through explicitly defined schemas. Model-name validation alone is insufficient because fallbacks also carry per-attempt overrides. Present the compatibility cost of excluding server tools, MCP/container and optional SDK features for user review; do not treat implemented behavior as the intended scope.

Done: produce and obtain the user's review of a written decision-13 amendment in the existing envelope design, following the project's frozen-revision review gates. Specify supported fields, message roles/keys, blocks, sources and pairings, client tools, cache/citation controls and top-level value variants, including required fields, primitive types and nullability. Preserve opaque client input/schema, pi plain/effort traffic, recursive content checks, route permissions, and unchanged request bytes. Distinguish provider behavior not verified by the offline evidence. Record a reviewable acceptance matrix and explicit unsupported features. No production implementation or implementation plan in this task; its reviewed design becomes input to a later scope pass for autonomy-58799c.

Where: [ref:brief], especially Nested-policy investigation / Smallest recommended policy / Contract, acceptance and remaining limits; [ref:envelope], decision 13; python/src/autonomy/egress/dialect.py and route.py; python/tests/test_egress_dialect.py and test_egress_route.py; README model route. autonomy-d0387e holds all eight evidence/review attachments, including 67 characterization cases and four offline pi 1.1.0 / SDK 0.129.0 captures. Those probes assert current verdicts and are not fix tests. No repeated research, paid API, desktop use, new provider dialect, general schema walker, route-schema expansion or accounting work.

Ideas it wakes: On completion, run tasks note autonomy-58799c --no-reviewed "<reviewed design outcome, revision and remaining implementation scope>" before this result's branch merges, so the idea is scoped against the reviewed contract.

## References

- brief (input, required, kind=brief): docs/notes/2026-10-18-egress-proof-gaps-brief.md — established nested-policy evidence, alternatives and acceptance obligations
- envelope (input, required, kind=spec): docs/specs/2026-10-12-envelope-design.md — decision 13 is the current contract to amend through review

## Notes

- 2026-10-29T09:02:18Z (add): created
  provenance: {"harness_session":"codex:01a186e3-3aaf-7182-859e-f668c80750f9","harness_session_source":"CODEX_THREAD_ID","origin":"agent"}
- 2026-10-29T09:05:57Z (main): started
  provenance: {"harness_session":"codex:01a186e7-b040-7ec0-b7e3-b46b220e04a6","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:06:41Z (design/closed-messages-policy): resumed
  provenance: {"harness_session":"codex:01a186e7-b040-7ec0-b7e3-b46b220e04a6","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:07:05Z (design/closed-messages-policy): Intent provenance: filing event matched to codex:01a186e3-3aaf-7182-859e-f668c80750f9, rollout lines 111/114 (add call and created result at 2026-10-29T09:02:18Z). Human ask was "$scope autonomy-58799c"; finite-schema recommendation and design follow-up were agent-added. Original idea filing event unavailable: no creation/session stamp; no origin_session. Using the recorded brief and decision 13 without treating that recommendation as human approval. Planned design-only work in .worktrees/closed-messages-policy, branch design/closed-messages-policy; just setup completed. Full-suite baseline deferred to implementation setup under the planned-work rule. No trial enrolled.
  provenance: {"harness_session":"codex:01a186e7-b040-7ec0-b7e3-b46b220e04a6","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:13:17Z (design/closed-messages-policy): review: spec round 1 — verdict: accept; findings: none; reviewer: codex/gpt-6.1-sol
- 2026-10-29T09:13:18Z (design/closed-messages-policy): attached: builder-check-report.md (706 bytes): Full read-only builder check of frozen b1a325b by codex/gpt-6.1-sol; no important unanswered questions
- 2026-10-29T09:13:19Z (design/closed-messages-policy): attached: review-ledger.md (1579 bytes): Spec review ledger, verification limits and pending human gate; no rulings or deferred minors
- 2026-10-29T09:13:57Z (design/closed-messages-policy): retained: {"host":"titan","kind":"worktree","path":".worktrees/closed-messages-policy","state":"kept","verification":"verified","purpose":"Frozen proposed decision-13 amendment b1a325b on design/closed-messages-policy, pending human design review; hydrated, clean, review report and ledger attached","next_owner":"task:autonomy-a1d778","cleanup_trigger":"After human approval and local integration, harvest timings and inspect ignored files, plan ledger and host pointers before removal"}
- 2026-10-29T09:13:58Z (design/closed-messages-policy): retained: {"host":"titan","kind":"scratch","path":".worktrees/closed-messages-policy/.superpowers/sdd/closed-messages-policy","state":"kept","verification":"verified","purpose":"Controller copies of the full builder report and review ledger; identical committed attachments verified","next_owner":"task:autonomy-a1d778","cleanup_trigger":"After human review, retain updated review evidence on the task and resolve the ledger before worktree cleanup","manifest":".worktrees/closed-messages-policy/.superpowers/sdd/closed-messages-policy/manifest.sha256","sha256":"35775b2be522900c2550ae2dfeeba7337d19d1f0b529e155d59fed02674d1e53"}
- 2026-10-29T09:13:59Z (design/closed-messages-policy): parked (waiting on user, review): User reviews autonomy repository frozen b1a325b6b10535de846441acc3c8f9f6375a5f45:docs/specs/2026-10-12-envelope-design.md in .worktrees/closed-messages-policy. After approval, agent records human review, completes the design task, wakes and scopes autonomy-58799c, and integrates design/closed-messages-policy locally; implementation plan needs separate review.
  provenance: {"harness_session":"codex:01a186e7-b040-7ec0-b7e3-b46b220e04a6","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:15:16Z (design/closed-messages-policy): resumed
  provenance: {"harness_session":"codex:01a186e7-b040-7ec0-b7e3-b46b220e04a6","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:15:36Z (design/closed-messages-policy): review: spec round 2 — verdict: accept; findings: none; reviewer: human
- 2026-10-29T09:15:36Z (design/closed-messages-policy): Human approved the proposed closed subset with "Approve" in this session, referring to frozen autonomy b1a325b6b10535de846441acc3c8f9f6375a5f45:docs/specs/2026-10-12-envelope-design.md. Approval includes finite control shapes, route-load fallback refusal and documented compatibility limits. Implementation plan remains separately gated.
  provenance: {"harness_session":"codex:01a186e7-b040-7ec0-b7e3-b46b220e04a6","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:16:16Z (design/closed-messages-policy): attached: review-ledger-approved.md (1995 bytes): Builder and human design review outcomes for b1a325b; approved, no rulings or deferred minors
