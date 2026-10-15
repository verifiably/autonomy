---
id: autonomy-d5c1cb
title: "Design a development mode of autonomy run: unattended development actors confined by the envelope, with acceptance left to crew"
status: idea
priority: 2
reviewed: true
created: 2026-10-14T01:44:16Z
updated: 2026-10-15T10:51:33Z
depends: [autonomy-c5c566]
parent: autonomy-d9adef
tags: []
agent: claude-code/claude-opus-5-5
---

Why: crew runs pi on development tasks and, later, on science actions through autonomy run. Its design recommends autonomy's envelope, specified to constrain any actor identically, as the owner of limits for unattended development work too (a development tier), with crew as the caller. It also needs to know how the actor's stdio is handled under autonomy run, since crew drives pi over RPC stdio (the answer may favour pi-durable in-process). Named in crew's core design (crew docs/specs/2026-10-13-crew-core-design.md §9; task crew-3fc20c), §10 decision 1 and §8.2.

Done: a recorded decision on both questions; the stdio answer is also an input to autonomy-641123 (Plan B).

## Notes

- 2026-10-15T10:40:03Z (main): scope: briefed; parented under goal autonomy-d9adef; the stdio half is half-answered by the code: Plan A's gate reopens the actor's stdin on /dev/null (sandbox/bwrap.py _GATE) while crew's pi-cli-rpc pipes stdio, so autonomy run cannot carry pi RPC as built; filed probe autonomy-c5c566 (pass-through stdio, binds, credential exposure) and depends on it; development coverage framed as A dev mode of autonomy run / B sandbox primitive with crew-judged disposition / C attended-only, lean A, open question what a dev run's closing check verifies; stdio recommendation goes to autonomy-641123; brief: docs/notes/2026-10-15-authority-and-development-actors-brief.md
- 2026-10-15T10:51:32Z (main): Direction from the user's review of the brief, 2026-10-15: lean A (a development mode of autonomy run) for one lifecycle, cancellation path and evidence record; autonomy enforces confinement and crew judges whether the result is useful and correct, so B's ownership conflict was overstated. Pushes, host changes and credential use are prevented at the boundary, never inferred from a worktree diff. quarantined keeps the result and blocks its promotion, recording what could not be established. A clean boundary verdict is distinct from passing tests or acceptable code. The stdio half moved to autonomy-a41de4, which Plan B depends on; this idea still waits on the probe autonomy-c5c566.
