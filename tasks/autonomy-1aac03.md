---
id: autonomy-1aac03
title: "Authorization model: what a flow gate never grants (spend, publication, host changes, unattended operation)"
status: idea
priority: 2
created: 2026-10-04T10:54:36Z
updated: 2026-10-11T17:54:14Z
depends: []
tags: []
source: ops-cb9749
agent: claude-code
---

The agent layer split hands autonomy this boundary (ops docs/specs/2026-10-03-agent-layer-split-design.md §5.5, §9).

## Notes

- 2026-10-11T17:54:14Z (main): Related: ops-cb50a8 (typed exchanges; phone inbox). A typed question answered from a phone is still a gate, not an authorization: relay-f58531's answer kind must not become the way spend, publication or host changes are granted; this idea's boundary applies to it.
