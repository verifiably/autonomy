---
id: autonomy-cb258b
title: Amend the envelope spec with autonomy run's configuration refusals and its exit on an unexpected failure
status: doing
priority: 2
size: s
complexity: mid
process: direct
owner: docs/spec-run-refusals
created: 2026-10-15T15:44:08Z
updated: 2026-10-23T01:41:25Z
started: 2026-10-23T01:13:49Z
depends: []
tags: []
source: autonomy-641123
agent: claude-code/claude-opus-5-5
---

Plan B1 (autonomy-641123) shipped behaviour the spec (docs/specs/2026-10-12-envelope-design.md) does not state, so B2's plan would argue from a spec that is behind the code:
- refusal codes at configuration, each exit 2 with no run directory: `runtime-dir-unset` (XDG_RUNTIME_DIR unset, empty or relative), `home-unknown` (HOME unusable and no passwd home), `allocation-failed` (step 1 cannot create a directory; what it created is removed);
- HOME, when relative or empty, is treated like a relative XDG value and falls back to the passwd entry;
- an unexpected failure exits 2 when no run directory remains and 4 when one does (the run is left for `run close`), with one diagnostic line and never a traceback.
Add them to §3 steps 1–2, decision 12's *On failure*, and the exit-code list; check rows E1/E20. Land before B2's plan is written.

## Notes

- 2026-10-23T01:13:49Z (main): started
  provenance: {"harness_session":"claude-code:32e73931-f581-4452-9364-51f207f4e015","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-23T01:13:59Z (docs/spec-run-refusals): resumed
  provenance: {"harness_session":"claude-code:32e73931-f581-4452-9364-51f207f4e015","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-23T01:18:49Z (docs/spec-run-refusals): amendment drafted at 7258138 (.worktrees/spec-run-refusals, branch docs/spec-run-refusals): §3 steps 1-2 (place resolution, runtime-dir-unset, home-unknown, allocation-failed, world-free checks before allocation), decision 12 'On an unexpected failure', close step 4's other codes, row E1 CLI arm; adds that a durable disposition keeps its exit code (B2's fix per the B1 re-review). Baseline: just test, 790 passed.
- 2026-10-23T01:22:35Z (docs/spec-run-refusals): review: spec round 1 — verdict: revise; findings: Important 2, Minor 7; reviewer: claude-code/claude-opus-5-5
- 2026-10-23T01:36:58Z (docs/spec-run-refusals): round 1 addressed at 9b9afc0: I1 durable vs published stated in three cases; I2 new test test_an_unexpected_error_before_allocation_exits_2_with_one_diagnostic (fails with the handler mutated to always exit 4); minors M1-M7 fixed. Suite: one unidentified failure in 1 of 6 full runs (102 s vs 85 s, load avg ~10); 5 later runs 791 passed; tt keeps no log to name it.
- 2026-10-23T01:41:25Z (docs/spec-run-refusals): review: spec round 2 — verdict: accept; findings: Minor 5; reviewer: claude-code/claude-opus-5-5
