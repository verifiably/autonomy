# autonomy

The envelope and orchestrator of **Science** — what may run unattended, under
what tier, and how the next research action is chosen: the run baseline and
dispositions (`clean` / `quarantined` / `unwired`), tiers as write-class
permits, the actor sandbox and session ledger, behavioral profiles, and the
versioned priority function (`science.priority.v1`).

This repository is the `autonomy` layer of the five-layer stack
(`atoms` → `nodes` → `beliefs` → `science` → `autonomy`). It is split from
`science` on code-lineage independence: the envelope must not share a package
with the surface it constrains. Its only seam is `science`'s commands as
tools; it holds no private kernel access.

The governing design is the kernel repository's
[`docs/superpowers/specs/2026-08-29-user-and-autonomy-layer-design.md`](../beliefs/docs/superpowers/specs/2026-08-29-user-and-autonomy-layer-design.md)
(§7 is this layer; §8 orders the sub-projects). Nothing is built yet; work
here starts at sub-project **#6, the envelope**, after the command framework
exists, and **#7, the loop and priority function**, last.
