---
id: autonomy-d5c1cb
title: "Decide whether the envelope covers unattended development actors, and how an actor's stdio is handled under autonomy run"
status: idea
priority: 2
created: 2026-10-14T01:44:16Z
updated: 2026-10-15T10:40:02Z
depends: [autonomy-c5c566]
parent: autonomy-d9adef
tags: []
agent: claude-code/claude-opus-5-5
---

Why: crew runs pi on development tasks and, later, on science actions through autonomy run. Its design recommends autonomy's envelope, specified to constrain any actor identically, as the owner of limits for unattended development work too (a development tier), with crew as the caller. It also needs to know how the actor's stdio is handled under autonomy run, since crew drives pi over RPC stdio (the answer may favour pi-durable in-process). Named in crew's core design (crew docs/specs/2026-10-13-crew-core-design.md §9; task crew-3fc20c), §10 decision 1 and §8.2.

Done: a recorded decision on both questions; the stdio answer is also an input to autonomy-641123 (Plan B).
