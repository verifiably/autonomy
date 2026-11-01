---
id: autonomy-d0fce7
title: "autonomy analyst: take an explicit thinking level and record it; '--thinking off' is not what current Claude models run"
status: doing
priority: 2
size: s
complexity: mid
process: direct
owner: autonomy-d0fce7
created: 2026-11-01T15:35:53Z
updated: 2026-11-01T16:28:27Z
started: 2026-11-01T15:42:44Z
depends: []
tags: [sandbox]
source: mm-62e2da
agent: claude-code/claude-opus-5-5
origin: mixed
---

Why: a caller (mm-62e2da, the phase-2 blinded describer) must pin its generation settings before any live run, and the launch record must state them truthfully. Today `autonomy analyst` passes a fixed `--thinking off` to pi (python/src/autonomy/analyst/launch.py:92). In pi 1.1.0 the model registry (pi-ai dist/providers/data/anthropic.json) maps `off` to null for claude-haiku-5-5, claude-sonnet-5-5, claude-opus-5-5 and claude-fable-5-1, and pi-ai dist/api/anthropic-messages.js:967 then omits the thinking parameter. Those models therefore run adaptive thinking at their default effort (medium on Opus 5.5 and Haiku 5.5), not with thinking off, and the caller cannot choose the level. Read from code; no live call made.

Wanted: a caller-declared thinking level (pi's levels: low, medium, high, xhigh, max; reject one the chosen model's thinkingLevelMap maps to null) passed to pi in place of the fixed `off`, and recorded in the run's epoch/launch record with the model, so a run record states what the model actually ran with. Decide whether the default stays as today (and is recorded as "model default") or becomes required; E24's epoch notes may need a line.

Done: the flag exists, is validated against pi's registry for the routed model, reaches pi's argv, and is recorded; a unit test covers the argv and the record; README documents it.

## Notes

- 2026-11-01T15:35:53Z (add): created
  provenance: {"harness_session":"claude-code:d2f6936f-5a00-44ba-bd5b-50a8c3d96fff","harness_session_source":"CLAUDE_CODE_SESSION_ID","origin":"mixed"}
- 2026-11-01T15:42:44Z (main): started
- 2026-11-01T15:43:49Z (autonomy-d0fce7): resumed
- 2026-11-01T15:43:49Z (autonomy-d0fce7): took over Unix session (owner main, stale)
- 2026-11-01T15:49:16Z (autonomy-d0fce7): retained: {"host":"titan","kind":"worktree","path":".worktrees/autonomy-d0fce7","state":"kept","verification":"verified","purpose":"Implement and verify autonomy-d0fce7","next_owner":"task:autonomy-d0fce7","cleanup_trigger":"After review passes and the branch merges locally into main, inspect ignored files, run tt-report, check host pointers and remove the worktree"}
- 2026-11-01T15:49:20Z (autonomy-d0fce7): process: direct; workspace .worktrees/autonomy-d0fce7 (branch autonomy-d0fce7, locked, just setup done). Focused baseline (automatic_broad = false, broad baseline deliberately omitted under policy-off): just test-one tests/test_analyst_toolchain.py tests/test_analyst_launch.py tests/test_cli.py tests/test_analyst_check.py — 98 passed in 70.54s. Origin read: mm-62e2da and filing session claude-code:d2f6936f-5a00-44ba-bd5b-50a8c3d96fff (user asked to pin generation settings in Amendment 4 point 3 and agreed on claude-opus-5-5; agent found autonomy analyst hardcodes --thinking off and filed autonomy-d0fce7).
- 2026-11-01T16:00:34Z (autonomy-d0fce7): decision: make --thinking LEVEL required on autonomy analyst and AnalystRequest, validated against pi 1.1.0's anthropic-messages registry (pi-ai dist/providers/data/anthropic.json) so any level pi would clamp, omit or collapse (including 'off' and 'minimal' on current adaptive-thinking Claude models, and 'xhigh'/'max' on older models without thinkingLevelMap entries) is refused at step 1 as thinking-unsupported (and an unlisted model as model-unknown), and record both model and thinking in epoch.json and events.jsonl. Rejected alternative: keeping a default ('off' or omitted, recorded as 'model default'), because in pi 1.1.0 '--thinking off' is silently clamped by clampThinkingLevel to 'low' on Haiku/Sonnet/Opus 5.5 and omitting '--thinking' substitutes DEFAULT_THINKING_LEVEL = 'medium' in pi-coding-agent sdk.js:136, so neither runs an unpinned provider default.
- 2026-11-01T16:28:05Z (autonomy-d0fce7): review: impl round 1 — verdict: accept; findings: minor 2; reviewer: agy
- 2026-11-01T16:28:25Z (autonomy-d0fce7): Ruling (impl round 1 declined-to-judge 1, dbd0fcd802043c5a0c7de7584872aaf3ec051a76..b7b7b3cf4f65529a91670956c920d9fa0eee5e63): leave python/scripts/egress_live.py:129 unchanged ('--thinking off' under autonomy run). Why: egress_live.py is row E21's manual live-egress smoke recipe for decision 13 (autonomy run), not autonomy analyst (decision 14), and only checks that one prompt crosses the egress proxy. Cost: if wrong, someone reading egress_live.py as an example of pi generation pinning could assume '--thinking off' disables thinking on 5.5 models, though egress_live.py claims no generation pinning.
- 2026-11-01T16:28:26Z (autonomy-d0fce7): Ruling (impl round 1 declined-to-judge 2, dbd0fcd802043c5a0c7de7584872aaf3ec051a76..b7b7b3cf4f65529a91670956c920d9fa0eee5e63): keep mid-session pi RPC commands (set_thinking_level, cycle_thinking_level, set_model) unmediated on fd 0. Why: under decision 12 and decision 14 step 4, fds 0 and 1 belong directly to the caller with no orchestrator relay, so epoch.json and events.jsonl record launch configuration while scratch/sessions records mid-session RPC state. Cost: if wrong, a caller that mutates thinking mid-session over RPC diverges from epoch.json's launch-time thinking field unless read alongside scratch/sessions.
- 2026-11-01T16:28:27Z (autonomy-d0fce7): Ruling (impl round 1 declined-to-judge 3, dbd0fcd802043c5a0c7de7584872aaf3ec051a76..b7b7b3cf4f65529a91670956c920d9fa0eee5e63): keep refuse() scoped to route validity, credential checks and MODEL membership without pre-checking operations[0].fields or anthropic-beta tokens for thinking/output_config. Why: decision 14 step 1 delegates body-field and header-token enforcement to decision 13's per-request egress proxy. Cost: if wrong, a route missing 'output_config' or pi 1.1.0's effort beta tokens fails on the first proxied request (exit 3) rather than step 1 (exit 2).
