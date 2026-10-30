---
id: autonomy-9092f2
title: "Test policy adoption: deferred review minors (gates docs and wiring tests)"
status: todo
priority: 3
size: xs
complexity: low
process: direct
created: 2026-10-30T23:02:11Z
updated: 2026-10-30T23:02:11Z
depends: []
tags: [gates]
source: autonomy-23aeff
agent: claude-code/claude-opus-5-5
origin: agent
---

Deferred minors from autonomy-23aeff's impl reviews (claude-code/claude-opus-5-5), recorded in its attached plan-ledger-progress.md. (1) justfile header still says 'three commands', says 'just gate' runs at pre-push and in CI, and says every recipe runs through the timing wrapper (false for check and test-full). (2) python/tests/test_front_door.py fixture subprocess calls set no timeout; a hung hook would show as a cancelled hosted job, not a failing test. (3) The workflow tests match substrings, not YAML structure; actionlint is in no gate. (4) AGENTS.md Layout does not list .github/workflows/. (5) AGENTS.md explains just test-full twice. (6) The AGENTS.md rollback text should name the adoption record autonomy-23aeff and its source tt-policy:autonomy. (7) The AGENTS.md sentence about justfile and hook edits still justifies its test-one rule by testmon, which is no longer the local route.

## Notes

- 2026-10-30T23:02:11Z (add): created
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID","origin":"agent"}
