---
id: autonomy-641123
title: "Envelope Plan B1: the run CLI's launch side, independent of the slices (step 1–2 refusals incl. stdio-refused, report fd, gate release fd, /dev/null child stdin; E1 CLI arm, E20 launch arm)"
status: doing
priority: 2
size: m
complexity: high
process: planned
owner: main
created: 2026-10-12T12:10:25Z
updated: 2026-10-15T13:05:50Z
started: 2026-10-15T13:05:33Z
depends: [autonomy-250f4d, autonomy-a41de4]
tags: []
agent: claude-code/claude-opus-5-5
---

Spec §13 item 4, first half: the parts of Plan B that need nothing from the beliefs or science slices, so they can land before beliefs-7a56ef and sci-a1d45f. Scope: the `autonomy run` CLI shell and argument parsing; step 1 (run, scratch and socket directories); step 2's configuration refusals (publishes = E1's CLI arm, lease floor, orphaned-run scan, stdio-refused per decision 12); the report fd's first and closing lines with non-blocking writes to it and to stderr; the gate's own release fd under python3; /dev/null as stdin for the preflight and the probe; the orchestrator's fd hand-off at step 9; row E20's launch arm. A run in this plan closes unwired at step 3 when science is unavailable, which exercises the closing-line path. Also picks the wall-clock bound value the spec leaves open (§3 Close, decision 12) if the CLI surface needs it. The endpoint side is the sibling Plan B2 task.

## Notes

- 2026-10-15T11:50:33Z (spec/stdio): From autonomy-a41de4's review: the envelope spec leans on a wall-clock bound (§3 Close, decision 12) but gives it no value or option anywhere; Plan B picks one.
- 2026-10-15T13:05:33Z (main): started
  provenance: {"harness_session":"claude-code:7c29ea9f-08a9-4ac1-a899-6dcc9586cd0a","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
