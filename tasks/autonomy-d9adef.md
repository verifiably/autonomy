---
id: autonomy-d9adef
title: "Authority beyond the science run: autonomy's authorization model and unattended development actors"
status: todo
priority: 2
process: direct
created: 2026-10-15T10:39:12Z
updated: 2026-10-17T09:50:53Z
depends: []
tags: []
source: docs/notes/2026-10-15-authority-and-development-actors-brief.md
agent: claude-code/claude-opus-5-5
---

Why: several designs name autonomy as the owner of authority to act (ops agent-layer split §5.5, relay typed-interaction §4.3, crew core design §10 decision 1), but the only authority autonomy defines is a tier on a science run (envelope spec §5, §11). This goal holds the work that closes that gap: autonomy's authorization contract, a development mode of autonomy run for unattended development actors, and how an actor's stdio is handled under autonomy run.

Done: autonomy-1aac03 (contract design) and autonomy-d5c1cb (development mode) resolved, and the stdio amendment autonomy-a41de4 approved, which unblocks Plan B's launch interface (autonomy-641123). The egress and credential-custody amendment autonomy-efa755 approved (added 2026-10-17); both the development mode and autonomy-9e8a43 consume it.

Where: the brief at docs/notes/2026-10-15-authority-and-development-actors-brief.md.
