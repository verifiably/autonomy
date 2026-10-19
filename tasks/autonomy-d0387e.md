---
id: autonomy-d0387e
title: Establish the minimal closed policy for fallback models and message-level provider fields
status: todo
priority: 2
size: s
complexity: mid
process: direct
created: 2026-10-19T00:11:43Z
updated: 2026-10-19T00:11:43Z
depends: []
parent: autonomy-3a06d3
tags: []
source: docs/notes/2026-10-18-egress-proof-gaps-brief.md
agent: codex
---

Question: Which fallback and message-object positions in the current anthropic-messages dialect can select a model or provider feature outside its checked lists, and should the minimal fix reject fallbacks at route load or validate them?

Where to start: python/src/autonomy/egress/dialect.py::check_body, egress/route.py operation parsing, python/tests/test_egress_dialect.py and test_egress_route.py; README model-route warning; envelope design decision 13; docs/notes/2026-10-18-egress-proof-gaps-brief.md. autonomy-58799c preserves the pi 1.1.0 live finding, but its complete supported message schema is not established.

Bound: trace these existing validation paths and use minimal synthetic request/route cases to establish unchecked model positions and message keys/roles, including the reported system/output_config shape. Compare refusing fallbacks with checking every fallback model, and name any message policy that needs a reviewed contract change. No proxy implementation, generalized schema walker, dependency change, live API call or unrelated provider audit.

Expected result: record the demonstrated accepted/refused shapes, coverage boundary and smallest recommended policy on this task and in the brief. Distinguish observed code behavior from unverified provider schema claims. Provide concrete acceptance cases so the waiting idea can be scoped without repeating the investigation.

Ideas it wakes: On completion, run tasks note autonomy-58799c --no-reviewed "<finding>" before this result's branch merges.
