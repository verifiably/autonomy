---
id: autonomy-d5c1cb
title: "Design a development mode of autonomy run: unattended development actors confined by the envelope, with acceptance left to crew"
status: idea
priority: 2
created: 2026-10-14T01:44:16Z
updated: 2026-10-17T09:40:50Z
depends: [autonomy-c5c566, autonomy-a94e95]
parent: autonomy-d9adef
tags: []
agent: claude-code/claude-opus-5-5
---

Why: crew runs pi on development tasks and, later, on science actions through autonomy run. Its design recommends autonomy's envelope, specified to constrain any actor identically, as the owner of limits for unattended development work too (a development tier), with crew as the caller. Named in crew's core design (crew docs/specs/2026-10-13-crew-core-design.md §9; task crew-3fc20c), §10 decision 1 and §8.2.

The second question this idea first carried, how the actor's stdio is handled under autonomy run (crew drives pi over RPC stdio; the answer may favour pi-durable in-process), moved on 2026-10-15 to autonomy-a41de4, an envelope amendment that Plan B (autonomy-641123) depends on.

Direction (user, 2026-10-15; brief §4): a development mode of autonomy run, with no world, the task worktree as scratch, and the sandbox, lease, kill and run directory kept. Pushes, host changes and credential use are prevented at the boundary. quarantined keeps the result and blocks its promotion. A clean boundary verdict is separate from crew's acceptance (tests, review).

Done: a design for the development mode, as an envelope amendment, that says how pushes and host changes are made unavailable, what the closing check still verifies, and what quarantined holds. It is written after autonomy-a94e95 (shared clone in scratch and a host import route that runs nothing the actor wrote) answers and the brief's §5 question 4 (when egress and credential custody are designed, ahead of or within autonomy-9e8a43) is settled. autonomy-c5c566 answered the first probe (brief §2): pi RPC works in the sandbox, and a linked worktree cannot commit without exposing every branch.

Where: brief docs/notes/2026-10-15-authority-and-development-actors-brief.md; envelope spec §2, §7, §9.

## Notes

- 2026-10-15T10:40:03Z (main): scope: briefed; parented under goal autonomy-d9adef; the stdio half is half-answered by the code: Plan A's gate reopens the actor's stdin on /dev/null (sandbox/bwrap.py _GATE) while crew's pi-cli-rpc pipes stdio, so autonomy run cannot carry pi RPC as built; filed probe autonomy-c5c566 (pass-through stdio, binds, credential exposure) and depends on it; development coverage framed as A dev mode of autonomy run / B sandbox primitive with crew-judged disposition / C attended-only, lean A, open question what a dev run's closing check verifies; stdio recommendation goes to autonomy-641123; brief: docs/notes/2026-10-15-authority-and-development-actors-brief.md
- 2026-10-15T10:51:32Z (main): Direction from the user's review of the brief, 2026-10-15: lean A (a development mode of autonomy run) for one lifecycle, cancellation path and evidence record; autonomy enforces confinement and crew judges whether the result is useful and correct, so B's ownership conflict was overstated. Pushes, host changes and credential use are prevented at the boundary, never inferred from a worktree diff. quarantined keeps the result and blocks its promotion, recording what could not be established. A clean boundary verdict is distinct from passing tests or acceptable code. The stdio half moved to autonomy-a41de4, which Plan B depends on; this idea still waits on the probe autonomy-c5c566.
- 2026-10-15T11:23:22Z (main): autonomy-c5c566 finding: pi over RPC runs in the envelope's sandbox with caller-held stdio, but a linked worktree needs shared git metadata. Read-only git needs main .git ro plus the worktree admin dir rw. Committing also needs objects, refs/heads and logs rw, which lets the actor move every branch including main, and Plan A's static check refuses binding main/.git while the main checkout is denied. The credential is readable inside (inherent while pi holds it) and appeared in no log. Untested option for the design: an actor-side clone in scratch (git clone --shared, object store ro) that the host fetches from after a clean verdict. See brief §2 and §5 question 2.
