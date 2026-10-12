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
updated: 2026-10-12T15:48:29Z
started: 2026-10-12T10:47:24Z
depends: []
tags: [design]
agent: claude-code
spec: docs/specs/2026-10-12-envelope-design.md
plan: docs/plans/2026-10-12-envelope-plan-a.md
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
- 2026-10-12T11:10:25Z (envelope-design): review: spec round 2 — verdict: revise; findings: Important 7, Minor 2; reviewer: claude-code/claude-opus-5-5
- 2026-10-12T11:13:04Z (envelope-design): review: spec round 3 — verdict: revise; findings: Important 2, Minor 5; reviewer: claude-code/claude-opus-5-5
- 2026-10-12T11:16:35Z (envelope-design): review: spec round 4 — verdict: revise; findings: Important 2, Minor 2; reviewer: claude-code/claude-opus-5-5
- 2026-10-12T11:19:35Z (envelope-design): review: spec round 5 — verdict: revise; findings: Important 1, Minor 5; reviewer: claude-code/claude-opus-5-5
- 2026-10-12T11:19:44Z (envelope-design): parked (waiting on user, review): User reviews docs/specs/2026-10-12-envelope-design.md in .worktrees/envelope-design (5 subagent review rounds done; round-5 fixes not re-reviewed). On approval: writing-plans for Plan A (autonomy, buildable now) and file the beliefs and science slices.
  provenance: {"harness_session":"claude-code:cf736119-9fea-4ff1-af51-5dd74be0a1c0","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-12T11:26:25Z (envelope-design): review: spec round 6 — verdict: revise; findings: P1 3, P2 3; reviewer: codex
- 2026-10-12T11:30:15Z (envelope-design): resumed
  provenance: {"harness_session":"claude-code:cf736119-9fea-4ff1-af51-5dd74be0a1c0","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-12T11:34:59Z (envelope-design): review: spec round 7 — verdict: revise; findings: P2 2, P3 5; reviewer: claude-code/claude-opus-5-5
- 2026-10-12T11:36:00Z (envelope-design): parked (waiting on user, review): User reviews the revised spec docs/specs/2026-10-12-envelope-design.md in .worktrees/envelope-design (round 6 addressed; round 7 subagent findings fixed in 5febb2f, not re-reviewed). On approval: writing-plans for Plan A and file the beliefs and science slices.
  provenance: {"harness_session":"claude-code:cf736119-9fea-4ff1-af51-5dd74be0a1c0","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-12T11:45:35Z (envelope-design): review: spec round 8 — verdict: revise; findings: P2 3; reviewer: codex
- 2026-10-12T11:48:06Z (envelope-design): resumed
  provenance: {"harness_session":"claude-code:cf736119-9fea-4ff1-af51-5dd74be0a1c0","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-12T11:49:12Z (envelope-design): parked (waiting on user, review): User reviews the round-8 revision of docs/specs/2026-10-12-envelope-design.md in .worktrees/envelope-design (closing rules: one-transaction crash allowance, later-session boundary evidence). On approval: writing-plans for Plan A and file the beliefs and science slices.
  provenance: {"harness_session":"claude-code:cf736119-9fea-4ff1-af51-5dd74be0a1c0","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-12T11:52:39Z (envelope-design): review: spec round 9 — verdict: revise; findings: P2 1; reviewer: codex
- 2026-10-12T11:57:20Z (envelope-design): resumed
  provenance: {"harness_session":"claude-code:cf736119-9fea-4ff1-af51-5dd74be0a1c0","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-12T11:57:37Z (envelope-design): spec approved by user after round-9 fix (9a28272): proceed to Plan A and file the beliefs and science slices
- 2026-10-12T12:10:48Z (envelope-design): Plan A written (docs/plans/2026-10-12-envelope-plan-a.md, steps autonomy-c264b2…f6b551); filed beliefs-7a56ef (kernel run-session slice), sci-a1d45f (run endpoint slice, depends on beliefs-7a56ef), autonomy-641123 (Plan B, depends on both); autonomy-9e8a43 now depends on autonomy-641123
- 2026-10-12T12:10:49Z (envelope-design): parked (waiting on user, review): User reviews Plan A (docs/plans/2026-10-12-envelope-plan-a.md in .worktrees/envelope-design) and picks an execution method; then execute Task 1 (autonomy-c264b2) in this worktree.
  provenance: {"harness_session":"claude-code:cf736119-9fea-4ff1-af51-5dd74be0a1c0","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-12T12:30:22Z (envelope-design): review: spec round 10 — verdict: accept; findings: none; reviewer: codex
- 2026-10-12T12:30:23Z (envelope-design): review: plan round 1 — verdict: revise; findings: P2 3; reviewer: codex
- 2026-10-12T12:30:24Z (envelope-design): Plan A review details: P2 ledger parser raises TypeError for a complete JSON line whose line value is [] or {}; P2 close omits chain-discontinuous and returns unwired when on_chain=false is combined with a missing or malformed ledger; P2 launch races pidfd_open against child exit (reproduced with /usr/bin/true and a 200 ms acquisition delay, raising ProcessLookupError despite exit 0). Add focused regression cases and correct the supplied code before execution. Execution choice: native, then a fresh whole-branch reviewer. Round-9 ownership accepted for the current science command surface; kernel acquisition/recheck outer-report crashes need nested-intent handling before those routes are exposed. just check passed; review reproductions ran directly from plan snippets, including one real bwrap child; all child processes reaped.
- 2026-10-12T15:19:36Z (envelope-design): resumed
  provenance: {"harness_session":"claude-code:cf736119-9fea-4ff1-af51-5dd74be0a1c0","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-12T15:20:55Z (envelope-design): execution: native (user choice), then a fresh whole-branch review
- 2026-10-12T15:36:02Z (envelope-design): review: impl round 1 — verdict: revise; findings: Critical 0, Important 5, Minor 8; reviewer: claude-code/claude-opus-5-5
- 2026-10-12T15:43:32Z (envelope-design): review: impl round 2 — verdict: revise; findings: Important 2, Minor 4; reviewer: claude-code/claude-opus-5-5
- 2026-10-12T15:48:29Z (envelope-design): review: impl round 3 — verdict: accept; findings: Minor 4; reviewer: claude-code/claude-opus-5-5
