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
updated: 2026-10-23T01:13:59Z
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
