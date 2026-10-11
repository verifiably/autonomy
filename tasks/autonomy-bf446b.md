---
id: autonomy-bf446b
title: "Specialist panels: role agents discussing a research question"
status: idea
priority: 2
created: 2026-10-09T17:39:25Z
updated: 2026-10-11T20:44:07Z
depends: []
tags: [quick-add]
source: "mindful:thought:47f2f857a23d382e61fa6f4bb210b109"
agent: claude-code/claude-opus-5-5
---

Apply an agent roles system (as in hq-91e028's pairwise flow: leader/follower, asker/answerer, critic, reviewer) to research: a group of specialists (geneticist, evolutionary biologist, bioinformatician, biochemist, physicist, ...) discusses one research question.

## Notes

- 2026-10-11T20:44:07Z (main): 2026-10-11, from the science-harness-on-pi goal (ops): this is step 4, parallel analysts, and starts only after a bounded unattended run exists and is compared against a single-agent baseline. Two constraints to carry: (1) the envelope's writer session is exclusive over its corpora (governing design §7.1), so panels are parallel readers and analysts feeding one admitting writer, never independent writers; concurrent writers need a banked design amendment. (2) Reader diversity across model families and blind reading reduce correlated judgment error; they are not evidential independence, which is about data and which the kernel already tracks. Two blind readers of one paper are one source assertion. State which of the two a panel buys.
