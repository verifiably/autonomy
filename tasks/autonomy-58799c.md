---
id: autonomy-58799c
title: "Dialect: close fallbacks and the message- and block-level positions the route does not check"
status: idea
priority: 2
created: 2026-10-17T18:24:01Z
updated: 2026-10-29T02:18:41Z
depends: [autonomy-d0387e]
parent: autonomy-3a06d3
tags: []
agent: claude-code/claude-opus-5-5
---

The anthropic-messages dialect closes top-level fields but checks only `model` against the route's `models`. pi 1.1.0 sends `fallbacks: [{model: ...}]` when a model's compat lists allowedFallbackModels; a route that listed `fallbacks` in `fields` would let the upstream answer with models outside `models`. Today the README warns never to list it. Options: treat `fallbacks[].model` as a model position checked against `models`, or refuse `fallbacks` in route parsing. Also check whether keys on message objects (pi's mid-conversation `{role: system, output_config}` messages) are closed. Found during autonomy-e4c0b5's live run (2026-10-17).

## Notes

- 2026-10-19T00:11:45Z (main): scope: briefed; 316c68b confirms fallback models and message-object keys/roles are unchecked; retained the captured live finding and framed fail-closed refusal versus explicit fallback validation; brief: docs/notes/2026-10-18-egress-proof-gaps-brief.md; waits on autonomy-d0387e
- 2026-10-19T00:37:35Z (main): scope: brief revised after review; the gap widens past model selection to tool and source positions in open message and block keys (the example route's inline-tools and mid-conversation-output-config betas), and to values of allowed top-level fields; fallbacks is reachable only through operator misconfiguration; still waits on autonomy-d0387e
- 2026-10-29T02:18:41Z (research/egress-policy): autonomy-d0387e established the nested-policy result in docs/notes/2026-10-18-egress-proof-gaps-brief.md (research e8fdb3a, clarification b76482d); its task holds 67 current/proposed acceptance cases and four offline pi SDK captures. Inline tool_addition is already refused, while extra message/block/control keys pass; no provider escape demonstrated. Recommend explicit finite control schemas, preserving opaque input/schema and system effort; refuse fallbacks at route load including default. Scope a reviewed decision-13 amendment before implementing: restricting operator-listed fields/server tools and optional SDK features narrows the existing contract. Research independently accepted; one minor clarified, none deferred.
