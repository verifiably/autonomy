---
id: autonomy-1aac03
title: "Authorization model: what a flow gate never grants (spend, publication, host changes, unattended operation)"
status: idea
priority: 2
created: 2026-10-04T10:54:36Z
updated: 2026-10-11T20:44:08Z
depends: []
tags: []
source: ops-cb9749
agent: claude-code
---

The agent layer split hands autonomy this boundary (ops docs/specs/2026-10-03-agent-layer-split-design.md §5.5, §9).

## Notes

- 2026-10-11T17:54:14Z (main): Related: ops-cb50a8 (typed exchanges; phone inbox). A typed question answered from a phone is still a gate, not an authorization: relay-f58531's answer kind must not become the way spend, publication or host changes are granted; this idea's boundary applies to it.
- 2026-10-11T20:44:08Z (main): 2026-10-11: shape to take from harness-engineering's authority thesis (~/software/harness-engineering/docs/authority/README.md): an authority grant names identity, operation and resource, scope, lifetime and revocation, approval, audit receipt and rollback; consequential effects are staged (assess, prepare, canary, approve, cut over, verify, roll back); wrong actions are made unavailable by one policy decision point returning a precise denial and the safe next action. Companion of the envelope design autonomy-250f4d: a tier is an authorization, a gate never is.
