---
id: autonomy-250f4d
title: "Envelope design (sub-project 6): actor sandbox, baseline with log heads, tiers as permits, ledger-checked interval membership, dispositions, lease"
status: doing
priority: 2
size: l
complexity: high
process: planned
owner: envelope-design
created: 2026-10-11T20:43:09Z
updated: 2026-10-12T11:03:43Z
started: 2026-10-12T10:47:24Z
depends: []
tags: [design]
agent: claude-code
spec: docs/specs/2026-10-12-envelope-design.md
---

The first autonomy work, and the condition for any unattended run. Piece of the science-harness-on-pi goal (ops, filed 2026-10-11): its step 3, a bounded unattended run, cannot start before this exists, so the envelope proceeds beside the attended probe rather than after it; the probe discovers practical requirements and this establishes the conditions.

Governing text: §7.1 and §7.4 of https://github.com/verifiably/beliefs/blob/main/docs/superpowers/specs/2026-08-29-user-and-autonomy-layer-design.md (cite by URL, never by a sibling-checkout path). Depends on science's sub-project 2, the command framework, which is delivered.

The spec decides: how a run opens (fresh run-unique actor identity; baseline of world head, every writable corpus's log head and the belief basis, written outside any corpus the actor can write; one exclusive beliefs writer session over the run's corpora); tiers as permits (report-only, coordination, mints, publishes; publishes never unattended), minted into the permit and enforced by the kernel writer so nothing downstream can widen one; the closing check (re-read heads and basis, compare the chain interval against the session ledger entry by entry: clean, quarantined, unwired, with unwired whenever a guard cannot see); the lease and kill switch (a dead orchestrator leaves its run unwired; how an expired lease stops the old worker from continuing consequential work); and the seam (science's commands as tools, no private kernel access, a process boundary around the same session API).

Keep the harness out of it: the envelope constrains any actor identically, a pi agent, a Claude Code session or a person's script. The authorization model (autonomy-1aac03) is the companion: a tier is an authorization, a gate never is.

Deliver a reviewed spec under docs/specs/ (the first file there), then a plan.

## Notes

- 2026-10-11T20:45:02Z (main): Goal: ops-3f5aa6 (a science harness on pi). Report the done note there.
- 2026-10-12T10:47:24Z (main): started
  provenance: {"harness_session":"claude-code:cf736119-9fea-4ff1-af51-5dd74be0a1c0","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-12T10:47:30Z (envelope-design): resumed
  provenance: {"harness_session":"claude-code:cf736119-9fea-4ff1-af51-5dd74be0a1c0","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-12T10:57:33Z (envelope-design): spec drafted at docs/specs/2026-10-12-envelope-design.md; drafting decisions: belief basis = derivation context digest (kernel has no concept), run writes one corpus, kernel cross-process corpus claim, lease at endpoint via control socket, bwrap sandbox, autonomy-owned closing comparison
- 2026-10-12T11:03:43Z (envelope-design): review: spec round 1 — verdict: revise; findings: Critical 3, Important 9, Minor 8; reviewer: claude-code/claude-opus-5-5
