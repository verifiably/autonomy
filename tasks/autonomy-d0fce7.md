---
id: autonomy-d0fce7
title: "autonomy analyst: take an explicit thinking level and record it; '--thinking off' is not what current Claude models run"
status: doing
priority: 2
size: s
complexity: mid
process: direct
owner: main
created: 2026-11-01T15:35:53Z
updated: 2026-11-01T15:42:44Z
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
