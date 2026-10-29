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
updated: 2026-10-29T09:22:13Z
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
- 2026-10-29T09:19:33Z (fix/response-completion): Baseline in .worktrees/response-completion: just setup completed; just test ran 791 tests, all passed (85.93 s). Both shutdown-before-close paths verified in server.py; response_head removes upstream framing.
- 2026-10-29T09:20:05Z (fix/response-completion): attached: test_completion_probe.py (4203 bytes): Pre-fix loopback matrix: current framing, test-only chunked framing, and reset replacing both FIN paths; run against 5720ee9 with tests on PYTHONPATH.
- 2026-10-29T09:20:06Z (fix/response-completion): attached: completion-probe.txt (1364 bytes): 30 loopback cases: raw TCP and http.client, stop and forced-survivor stop, malformed chunk, Content-Length success, unframed EOF.
- 2026-10-29T09:20:52Z (fix/response-completion): attached: completion-races.txt (2975 bytes): Five repeats of 12 stop/survivor cases: 60 passed; reset calls serialized and already-closed descriptors checked.
- 2026-10-29T09:22:12Z (fix/response-completion): retained: {"host":"titan","kind":"worktree","path":".worktrees/response-completion","state":"kept","verification":"verified","purpose":"Investigation artifacts attached and byte-compared; worktree transferred to the follow-on fix","next_owner":"task:autonomy-c9508e","cleanup_trigger":"After the reviewed fix is locally merged, inspect ignored evidence and host pointers, harvest timings, then remove"}
- 2026-10-29T09:22:13Z (fix/response-completion): Result: attached probe reproduced via PYTHONPATH=tests just test-one ../tasks/files/autonomy-9570b0/test_completion_probe.py -q (30 passed); five stop/survivor repeats add 60 passed. Chunking yields IncompleteRead and preserves streamed bytes; reset yields ConnectionResetError only after replacing both FIN paths and serializing close to avoid EBADF. No finite loopback run proves reset reliability across arbitrary schedules. Local pre-response errors retain their existing separate length framing. Recommend chunking with zero chunk only after successful iteration; 204/304 stay bodyless; unframed upstream EOF has no semantic-completeness proof. Follow-on scoped as direct; no raw/scratch evidence remains outside attached files.
