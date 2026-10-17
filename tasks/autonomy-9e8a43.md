---
id: autonomy-9e8a43
title: "Bounded unattended run: one research action under the envelope with enforced permissions, budget, lease and cancellation, and a concise evidence report"
status: todo
priority: 2
size: l
complexity: high
process: planned
created: 2026-10-11T20:44:01Z
updated: 2026-10-17T11:26:08Z
depends: [autonomy-250f4d, ops-fbc3d9, sci-bef251, sci-a45f10, autonomy-641123, autonomy-6b1f9f, autonomy-f6efe8, autonomy-efa755, autonomy-e4c0b5]
tags: [unattended]
agent: claude-code
---

Step 3 of the science-harness-on-pi goal (ops, filed 2026-10-11). The first run nobody watches: one candidate from the derived queue, run by the pi harness under the envelope (autonomy-250f4d), after the recovery probe (ops-fbc3d9) has shown how the runtime's recovery joins science's ledger. Not the loop and not the priority function: those are sub-project 7 and get their own spec after this run exists.

Two acceptance criteria, kept separate because they are different claims. Accounting: the run's joined usage totals (the harness's per-conversation tokens and cost including children, plus the analysis jobs the kernel ran) say what the run consumed, attributed to the run's actor. Enforcement: a shared allowance decides whether another model call or analysis job may start, counting concurrent children and work already in flight, and a run at its allowance stops cleanly with its disposition recorded; a total that is merely reported after the fact does not satisfy this criterion.

Permissions are enforced at boundaries the agent cannot reach around: the kernel writer's permit for governed writes, and an operating-system or container boundary for the shell, filesystem, network and credentials, as pi's own security doc requires; a tool hook is a policy decision point for feedback and precise denials, never the boundary. Credentials stay outside the trajectory.

Not owned here (user, 2026-10-17): the design of network egress and credential custody moved to autonomy-efa755, the shared envelope amendment (a per-run trusted proxy that is the actor's only network path and holds the provider credential), which this run and the development mode (autonomy-d5c1cb) both consume. This task keeps allowance enforcement, accounting and the science integration, and implements its allowance check at the join point that amendment defines on the proxy.

Outcomes: the run ends in one of the envelope's dispositions and, inside clean, in a stated outcome shape (nothing needed, proposed, proved, approval requested, recovery required). An inconclusive or refused scientific result with its evidence is an eligible success; a refusal from a broken integration is a failure. The expected evidence is written before the run.

The evidence report is what a person reads afterwards: disposition, outcome, what was consumed against what was allowed, the records written, the questions asked and how they were answered, and the smallest unresolved choice if one remains.

Deliver a reviewed spec and plan here; the harness-side pieces are filed to their owners from the plan.

## Notes

- 2026-10-11T20:45:03Z (main): Goal: ops-3f5aa6 (a science harness on pi). Report the done note there.
- 2026-10-17T09:50:41Z (main): Narrowed (user, 2026-10-17): egress and credential-custody design moved to autonomy-efa755 and this task depends on it; allowance enforcement, accounting and science integration stay here, with the allowance check joining the proxy where autonomy-efa755 places it.
