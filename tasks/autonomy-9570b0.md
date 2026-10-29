---
id: autonomy-9570b0
title: "Establish how a cut proxy response can reliably signal an HTTP client error: framing or abortive close"
status: doing
priority: 2
size: s
complexity: mid
process: direct
owner: fix/response-completion
created: 2026-10-19T00:11:46Z
updated: 2026-10-29T09:16:49Z
started: 2026-10-29T09:16:11Z
depends: []
parent: autonomy-3a06d3
tags: []
source: docs/notes/2026-10-18-egress-proof-gaps-brief.md
agent: codex
---

Question: Does proxy-owned chunked framing, with a terminator only on completion, make every detectable cut of a proxied response an HTTP client error, and can an abortive close (SO_LINGER {1,0}) match it once both FIN paths change?

Where to start: python/src/autonomy/egress/server.py::_handle, _release and close; egress/upstream.py::cut and response_head; python/tests/egress_fixtures.py and test_egress_server.py (badchunk and route-close cases); envelope design decision 13 ("in framing of its own"); docs/notes/2026-10-18-egress-proof-gaps-brief.md; autonomy-e4c0b5's attached final review. Two paths send a FIN today: _release shuts with SHUT_RDWR before close, and close() shuts survivors with SHUT_RDWR from its own thread after the join. A client sees that FIN as a clean end before any RST.

Bound: one small real-loopback matrix covering route stop mid-body (first), an upstream framing failure after the head, and normal completion, observed with a raw TCP reader and a standard-library HTTP client. Test minimal chunk framing and an abortive close that replaces both FIN paths; for the reset, record whether the stop path's race can be won reliably. Preserve readable pre-response 403/502 answers. Identify the limit where the upstream itself ends an unframed body without detectable failure. No production proxy redesign, benchmark, paid API or live desktop use.

Expected result: record client results and reproducible commands/test cases on this task and in the brief, then recommend the smallest reliable mechanism (the brief leans to framing) and explicit limits. Keep the bounded close, streaming, settle callback and final-record behavior as acceptance constraints for later implementation.

Ideas it wakes: On completion, run tasks note autonomy-c9508e --no-reviewed "<finding>" before this result's branch merges.

## Notes

- 2026-10-29T09:16:11Z (main): started
  provenance: {"harness_session":"codex:01a186f1-2641-7801-acc1-95d7c06af15e","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:16:49Z (fix/response-completion): resumed
  provenance: {"harness_session":"codex:01a186f1-2641-7801-acc1-95d7c06af15e","harness_session_source":"CODEX_THREAD_ID"}
