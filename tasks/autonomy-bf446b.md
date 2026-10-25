---
id: autonomy-bf446b
title: "Specialist panels: role agents discussing a research question"
status: idea
priority: 2
reviewed: true
reviewed_at: 2026-10-23T18:27:16Z
created: 2026-10-09T17:39:25Z
updated: 2026-10-25T18:34:58Z
depends: [autonomy-9e8a43]
tags: [quick-add]
source: "mindful:thought:47f2f857a23d382e61fa6f4bb210b109"
agent: claude-code/claude-opus-5-5
---

Apply an agent roles system (as in hq-91e028's pairwise flow: leader/follower, asker/answerer, critic, reviewer) to research: a group of specialists (geneticist, evolutionary biologist, bioinformatician, biochemist, physicist, ...) discusses one research question.

## Notes

- 2026-10-11T20:44:07Z (main): 2026-10-11, from the science-harness-on-pi goal (ops): this is step 4, parallel analysts, and starts only after a bounded unattended run exists and is compared against a single-agent baseline. Two constraints to carry: (1) the envelope's writer session is exclusive over its corpora (governing design §7.1), so panels are parallel readers and analysts feeding one admitting writer, never independent writers; concurrent writers need a banked design amendment. (2) Reader diversity across model families and blind reading reduce correlated judgment error; they are not evidential independence, which is about data and which the kernel already tracks. Two blind readers of one paper are one source assertion. State which of the two a panel buys.
- 2026-10-17T09:40:51Z (main): shelved: Wake when autonomy-9e8a43's bounded unattended run has run with its evidence report, giving the single-agent baseline that ops-3f5aa6 step 4 measures panels against. On wake, also settle the home: crew runs the analysts, autonomy keeps the one admitting writer.
- 2026-10-17T09:40:51Z (main): scope: shelved; step 4 of ops-3f5aa6 (which depends on it), after the step 3 run autonomy-9e8a43 (todo, blocked on Plan B2 autonomy-f6efe8 and the science slices); the 2026-10-11 constraints (parallel readers feeding one admitting writer; model diversity is not evidential independence) stand; related crew-9b4b47 (cross-harness delegation) and hq-91e028 (pair flow, shelved)
- 2026-10-23T18:27:15Z (main): unshelved
- 2026-10-23T18:27:16Z (main): scope: briefed; correction with user agreement 2026-10-23: the 2026-10-17 shelf waited on a task (autonomy-9e8a43's bounded unattended run and evidence report), so the wait is now a dependency edge instead and the task is an idea again; it re-enters review by itself when autonomy-9e8a43 closes. ops-3f5aa6 keeps its edge to this step, and its shelved_dep warning clears. The 2026-10-11 constraints and the on-wake home question (crew runs the analysts, autonomy keeps the one admitting writer) stand.
- 2026-10-25T18:34:58Z (main): Accepted boundary handoff from crew-aaab30, 2026-10-25: crew amendment revision 2 (4406de0), docs/specs/2026-10-25-orchestration-boundaries-design.md, integrated into crew authority at d7dcc92. Crew owns participant/team composition and execution references; lore owns role/context contracts, domains own specialized scientific knowledge. Parallel analysts still feed one admitting writer; science owns outcomes and autonomy owns authorization/enforcement and research-specific action selection. Preserve the bounded-run prerequisite, measured single-agent baseline, envelope/recovery gates and this idea’s lifecycle. This records composition ownership, not permission for a panel or research run.
