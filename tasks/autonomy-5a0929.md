---
id: autonomy-5a0929
title: "autonomy run takes decision 14's declarations (inputs, denied paths, release) once Plan B2 lands, and autonomy analyst becomes a composition over run with an endpoint"
status: todo
priority: 3
size: m
complexity: high
process: planned
created: 2026-10-31T23:48:00Z
updated: 2026-10-31T23:48:01Z
depends: [autonomy-f6efe8]
tags: [sandbox]
source: autonomy-2e2519
agent: claude-code/claude-fable-5-1
origin: agent
---

Outcome: one launch path. autonomy run gains --input, --deny and --release with the walk and the no-follow release, and autonomy analyst is rebuilt as a composition over run (an analyst with an endpoint, writing a corpus under a tier), so the analyst-only run directory under <state>/analyst and the duplicate supervision loop go away.

Why: decision 14's 'Approaches considered' chose a separate subcommand only because run closes unwired before launch until B2 (autonomy-f6efe8) lands and its run directory is the orphan scan's domain; it says the destination is run and that this is filed then. Needs a design amendment (where the walk and release sit in §3's steps, how the release interacts with the closing check and disposition, whether an analyst run owns a corpus at all) and the migration of the E23/E24 tests.

Blocked on autonomy-f6efe8.

## Notes

- 2026-10-31T23:48:00Z (add): created
  provenance: {"harness_session":"claude-code:fc4eb4dd-05c5-441e-9e3b-34ef5c547637","harness_session_source":"CLAUDE_CODE_SESSION_ID","origin":"agent"}
