---
id: autonomy-9570b0
title: Establish how a cut proxy response can reliably signal an HTTP client error
status: todo
priority: 2
size: s
complexity: mid
process: direct
created: 2026-10-19T00:11:46Z
updated: 2026-10-19T00:11:46Z
depends: []
parent: autonomy-3a06d3
tags: []
source: docs/notes/2026-10-18-egress-proof-gaps-brief.md
agent: codex
---

Question: Does an abortive actor-socket close reliably expose detectable proxy response cuts through the current shutdown paths, or is proxy-owned chunked framing required?

Where to start: python/src/autonomy/egress/server.py::_handle, _release and close; egress/upstream.py::cut and response_head; python/tests/egress_fixtures.py and test_egress_server.py (badchunk and route-close cases); docs/notes/2026-10-18-egress-proof-gaps-brief.md; autonomy-e4c0b5's attached final review.

Bound: one small real-loopback matrix covering normal completion, an upstream framing failure after the head, and route stop mid-body, observed with a raw TCP reader and a standard-library HTTP client. Compare SO_LINGER {1,0} with the existing shutdown order; test a minimal chunk-framing alternative only if reset does not meet the acceptance cases. Preserve readable pre-response 403/502 answers. Identify the limit where the upstream itself ends an unframed body without detectable failure. No production proxy redesign, benchmark, paid API or live desktop use.

Expected result: record client results and reproducible commands/test cases on this task and in the brief, then recommend the smallest reliable mechanism and explicit limits. Keep the bounded close, streaming, settle callback and final-record behavior as acceptance constraints for later implementation.

Ideas it wakes: On completion, run tasks note autonomy-c9508e --no-reviewed "<finding>" before this result's branch merges.
