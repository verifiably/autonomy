---
id: autonomy-58799c
title: "Dialect: close fallbacks and the message- and block-level positions the route does not check"
status: idea
priority: 2
reviewed: true
reviewed_at: 2026-10-19T00:11:45Z
created: 2026-10-17T18:24:01Z
updated: 2026-10-19T00:37:34Z
depends: [autonomy-d0387e]
parent: autonomy-3a06d3
tags: []
agent: claude-code/claude-opus-5-5
---

The anthropic-messages dialect closes top-level fields but checks only `model` against the route's `models`. pi 1.1.0 sends `fallbacks: [{model: ...}]` when a model's compat lists allowedFallbackModels; a route that listed `fallbacks` in `fields` would let the upstream answer with models outside `models`. Today the README warns never to list it. Options: treat `fallbacks[].model` as a model position checked against `models`, or refuse `fallbacks` in route parsing. Also check whether keys on message objects (pi's mid-conversation `{role: system, output_config}` messages) are closed. Found during autonomy-e4c0b5's live run (2026-10-17).

## Notes

- 2026-10-19T00:11:45Z (main): scope: briefed; 316c68b confirms fallback models and message-object keys/roles are unchecked; retained the captured live finding and framed fail-closed refusal versus explicit fallback validation; brief: docs/notes/2026-10-18-egress-proof-gaps-brief.md; waits on autonomy-d0387e
