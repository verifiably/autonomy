---
id: autonomy-e4c0b5
title: "Envelope egress plan: model route, namespace listener, sandboxed model proxy and its close transition (decision 13; rows E21-E22 launch arms, live pi recipe)"
status: doing
priority: 2
size: l
complexity: high
process: planned
owner: main
created: 2026-10-17T11:25:57Z
updated: 2026-10-17T15:54:55Z
started: 2026-10-17T11:26:48Z
depends: []
parent: autonomy-d9adef
tags: []
source: docs/specs/2026-10-12-envelope-design.md
agent: claude-code/claude-opus-5-5
spec: docs/specs/2026-10-12-envelope-design.md
---

Spec §13 item 5, from the approved amendment autonomy-efa755 (decision 13, approved 2026-10-17). Independent of the beliefs and science slices; lands before Plan B2 (autonomy-f6efe8) is needed.

Scope: the `egress` module (route parsing with the `anthropic-messages` dialect and its closed lists, step 2's `route-unknown`/`route-invalid`/`credential-unavailable`); `--model-route` on `autonomy run`; the denied set's `<config>` and credential entries; the probe's IPv4 and IPv6 `ENETUNREACH` check; removal of Plan A's `network` field and `host` value; the single-threaded namespace helper (NS_GET_USERNS, then the netns, listener on 127.0.0.1:4780 passed back over SCM_RIGHTS, the orchestrator keeping no copy); the model proxy in its own bwrap (fixed builder, no --die-with-parent, static check at step 7) with strict HTTP/1.1, the body and header checks, its own upstream framing, streaming, `egress.jsonl` and `proxy.log`, the lease, and the close transition (non-blocking upstream writes under the lock, waits outside it); step 9's proxy start and listener hand-off before the release (`egress-unproven`); close step 0 concurrent with the seal; the orphan path; the `admit`/`settle` join points as no-ops. Rows E21 and E22 on their launch arms, and a live recipe running pi through B1's launch path with its proxy to the real API (never in the suite). Full-run arms join B2.

Where: envelope spec decision 13, §3 steps 2, 7, 9 and Close, §6, §7, §8, §9 rows, §12 E20-E22, §13 item 5, §14; python/src/autonomy/sandbox/ (spec.py network, bwrap.py launch and _GATE), run.py, cli.py; autonomy-efa755's attached helper.py and host.py (the namespace listener as checked). Overlap risk: autonomy-6b1f9f also edits the sandbox launch.

## Notes

- 2026-10-17T11:26:48Z (main): started
  provenance: {"harness_session":"claude-code:8d3345f1-e50f-41b0-b5f0-0aedb418be65","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-17T11:55:58Z (main): plan drafted: docs/plans/2026-10-17-envelope-plan-egress.md on branch plan-egress (8387070), 10 tasks; B2 wiring items noted on autonomy-f6efe8. Agent plan review and a dry run of the plan's code in a /tmp copy dispatched before the user's review.
- 2026-10-17T12:12:34Z (main): review: plan round 1 — verdict: revise; findings: P1 5, P2 7, P3 10; reviewer: claude-code
- 2026-10-17T12:44:19Z (main): review: plan round 2 — verdict: revise; findings: P2 2, P3 10; reviewer: claude-code
- 2026-10-17T13:00:22Z (main): dry run 2 (plan at 4111619): 740 passed, no fixes, no flakiness; mutation pass found 2 untested E22 boundaries (Gate.call flag, 16 KiB slice) and 3 more (settle, recorder after closing line, actor read-side shutdown); tests added in the next commit.
- 2026-10-17T13:17:31Z (main): dry run 3 (final, cc830fb): all 10 tasks verbatim, 747 passed in 74 s, no flakiness, 6/6 boundary mutations caught.
- 2026-10-17T13:17:32Z (main): parked (waiting on user, review): User reviews docs/plans/2026-10-17-envelope-plan-egress.md (branch plan-egress, .worktrees/plan-egress) and picks an execution method; then the agent runs it in .worktrees/plan-egress starting with the baseline just test-fast, and asks before Task 10's live recipe.
  provenance: {"harness_session":"claude-code:8d3345f1-e50f-41b0-b5f0-0aedb418be65","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-17T14:40:29Z (main): resumed
  provenance: {"harness_session":"claude-code:8d3345f1-e50f-41b0-b5f0-0aedb418be65","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-17T14:40:30Z (main): review: plan round 3 — verdict: revise; findings: P2 6, P3 1; reviewer: human
- 2026-10-17T15:16:34Z (main): dry run 4 (09dd506): 771 passed in 82 s, no flakiness; 1 test bug (buffered wrapper kwargs) and 3 surviving mutations (start race, duplicate suppression, orphan post-signal wait, verdict stopReason); fixes applied in the next commit; _finalized dropped for an explicit outstanding check.
- 2026-10-17T15:17:02Z (main): parked (waiting on user, review): User re-reviews docs/plans/2026-10-17-envelope-plan-egress.md (branch plan-egress, 95ccf48; round 3 fixes in 09dd506, dry run 4's in 95ccf48) and picks an execution method; then the agent runs it in .worktrees/plan-egress starting with the baseline just test-fast, and asks before Task 10's live recipe.
  provenance: {"harness_session":"claude-code:8d3345f1-e50f-41b0-b5f0-0aedb418be65","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-17T15:36:36Z (main): resumed
  provenance: {"harness_session":"claude-code:8d3345f1-e50f-41b0-b5f0-0aedb418be65","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-17T15:36:37Z (main): review: plan round 4 — verdict: revise; findings: P2 3; reviewer: human
- 2026-10-17T15:54:54Z (main): dry run 5 (e9fcf00): all 10 tasks unchanged, 774 passed in 81 s, no flakiness, 6/6 mutations caught; added its TCP-connect watch test.
- 2026-10-17T15:54:55Z (main): parked (waiting on user, review): User re-reviews docs/plans/2026-10-17-envelope-plan-egress.md (branch plan-egress; round 4 fixes in e9fcf00, dry run 5's test after it) and picks an execution method; then the agent runs it in .worktrees/plan-egress starting with the baseline just test-fast, and asks before Task 10's live recipe.
  provenance: {"harness_session":"claude-code:8d3345f1-e50f-41b0-b5f0-0aedb418be65","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
