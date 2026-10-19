---
id: autonomy-58799c
title: "Dialect: check a body's fallbacks models against the route's models"
status: idea
priority: 2
created: 2026-10-17T18:24:01Z
updated: 2026-10-19T00:11:43Z
depends: []
parent: autonomy-3a06d3
tags: []
agent: claude-code/claude-opus-5-5
---

The anthropic-messages dialect closes top-level fields but checks only `model` against the route's `models`. pi 1.1.0 sends `fallbacks: [{model: ...}]` when a model's compat lists allowedFallbackModels; a route that listed `fallbacks` in `fields` would let the upstream answer with models outside `models`. Today the README warns never to list it. Options: treat `fallbacks[].model` as a model position checked against `models`, or refuse `fallbacks` in route parsing. Also check whether keys on message objects (pi's mid-conversation `{role: system, output_config}` messages) are closed. Found during autonomy-e4c0b5's live run (2026-10-17).
