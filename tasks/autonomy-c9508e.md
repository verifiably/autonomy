---
id: autonomy-c9508e
title: "Proxy: make a cut response detectable to any HTTP client"
status: done
priority: 2
size: s
complexity: mid
process: direct
owner: fix/response-completion
created: 2026-10-17T19:00:17Z
updated: 2026-10-29T09:32:09Z
started: 2026-10-29T09:22:15Z
completed: 2026-10-29T09:30:39Z
closed: 2026-10-29T09:30:39Z
depends: [autonomy-9570b0]
parent: autonomy-3a06d3
tags: [egress]
agent: claude-code/claude-opus-5-5
---

Why: Every current proxied response is close-delimited, so upstream framing failures and route stops look complete to HTTP clients. The original review proposed linger-zero resets; autonomy-9570b0 instead established proxy-owned chunking as the smaller reliable mechanism (30 loopback cases and 60 stop/survivor repeats). Reset needs both FIN paths replaced and synchronized closure. The brief records the evidence and limits.

Done: Send HTTP/1.1 chunked framing for every proxied response that permits a body; reframe nonempty decoded upstream pieces and emit the zero chunk only after successful body iteration while the route is open. No chunking or body for 204/304. A framing-validating HTTP client that consumes the response to its end must raise on a route cut or detectable upstream framing error. Preserve streaming with bounded buffers, the bounded close and survivor cut, readable length-delimited local 403/502 answers, payload-byte accounting, settlement exactly once per forwarded request, and the closing record last. Exercise real loopback raw and stdlib HTTP clients, normal length/chunk/close-delimited completion, malformed and truncated upstream bodies, stop during streaming and the survivor path. Unframed upstream EOF cannot prove semantic completeness; clients that do not validate framing are outside the guarantee. No route/schema/config expansion or new dependency.

Where: python/src/autonomy/egress/server.py::_handle; egress/upstream.py::response_head; python/tests/egress_fixtures.py, test_egress_server.py, test_egress_upstream.py; README model-route behavior. See docs/notes/2026-10-18-egress-proof-gaps-brief.md and autonomy-9570b0 attachments. Envelope decision 13 already permits framing owned by the proxy; direct execution settles this bounded bug fix without new design documents.

## Notes

- 2026-10-19T00:11:47Z (main): scope: briefed; 316c68b confirms close-delimited actor responses and shutdown-before-close on both completion paths; reset behavior and its shutdown interaction remain unproven; brief: docs/notes/2026-10-18-egress-proof-gaps-brief.md; waits on autonomy-9570b0
- 2026-10-19T00:37:49Z (main): scope: brief revised after review; an abortive close must replace the FIN from both _release and close()'s survivor cut and win the stop path's cross-thread race, so the brief now leans to proxy-owned chunked framing; mechanism follows autonomy-9570b0
- 2026-10-29T09:20:53Z (fix/response-completion): autonomy-9570b0: 30 real-loopback cases plus 60 stop/survivor repeats pass. Recommend proxy-owned chunked framing, terminal zero chunk only on successful body completion; reset requires both FIN paths replaced plus serialized descriptor closure. Unframed upstream EOF cannot establish semantic completeness. Brief updated; attachments on autonomy-9570b0.
- 2026-10-29T09:21:47Z (fix/response-completion): scope: scoped; autonomy-9570b0 loopback evidence settles chunking over resets, with upstream EOF and framing-validation limits retained; origin: original filing unavailable (no occurrence/session stamp); prior final review identifies this as an agent follow-up. This session user explicitly requests investigation then fix. Direct process: bounded framing change, existing contract, concrete regression checks.
  provenance: {"harness_session":"codex:01a186f1-2641-7801-acc1-95d7c06af15e","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:22:11Z (fix/response-completion): retained: {"host":"titan","kind":"worktree","path":".worktrees/response-completion","state":"kept","verification":"verified","purpose":"Implement and review the response framing fix after the completed loopback investigation","next_owner":"task:autonomy-c9508e","cleanup_trigger":"After the reviewed fix is locally merged, inspect ignored evidence and host pointers, harvest timings, then remove"}
- 2026-10-29T09:22:15Z (fix/response-completion): started
  provenance: {"harness_session":"codex:01a186f1-2641-7801-acc1-95d7c06af15e","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:24:22Z (fix/response-completion): RED: just test-one tests/test_egress_server.py -k "http_error or valid_http_framing or standard_http_client" -q --tb=short: 11 failed, 4 passed. Six failures explicitly showed DID NOT RAISE IncompleteRead for malformed/truncated upstream bodies and normal/forced-survivor route stops; five showed absent proxy chunking. Minimal fix touches server body writes and response_head; callers inspected with rg. Existing header-filter assertion updated for proxy-owned Transfer-Encoding.
- 2026-10-29T09:26:16Z (fix/response-completion): GREEN: just test-one tests/test_egress_server.py tests/test_egress_upstream.py -q --tb=short: 105 passed. just test-fast: 806 passed (all tests selected, new testmon DB), 87.23 s; one coverage warning that dynamic contexts are unsupported with sysmon. just check and git diff --check passed. Coverage includes body-bearing success, 204/304, local 403/502, four detectable upstream failures, route stop and held-worker survivor cut, once-only settle and final closing record. Payload counts exclude chunk framing. No production shutdown-path changes.
- 2026-10-29T09:30:05Z (fix/response-completion): review: impl round 1 — verdict: accept; findings: none; reviewer: codex/gpt-6.1-sol
- 2026-10-29T09:30:06Z (fix/response-completion): Review dispositions at 66d846f: (1) Accept unframed EOF as outside semantic-completeness guarantee. Why: EOF supplies no evidence of intended additional bytes. Cost if wrong: silently accepting an unframed partial application payload. (2) Accept arbitrary-schedule/platform reset reliability as outside implementation. Why: production uses chunking; bounded prototype evidence is explicitly limited. Cost if wrong: research would overstate reset reliability, without changing shipped framing. (3) Accept close after successful body iteration/final open check. Why: all payload has already been sent; a terminal chunk racing close cannot hide missing payload. Cost if wrong: client completion could disagree with a route-close record. (4) Leave general HEAD handling and stricter trailer validation unchanged. Why: the configured operations are POST and trailer parsing predates this framing fix. Cost if wrong: a future HEAD route or malformed trailer needs separate handling. No deferred Minor finding; these are reviewed scope/boundary dispositions.
- 2026-10-29T09:30:37Z (fix/response-completion): attached: completion-review-report.md (3477 bytes): Full read-only whole-branch review by codex/gpt-6.1-sol at 66d846f; accepted with no findings; boundary dispositions recorded in task notes.
- 2026-10-29T09:30:38Z (fix/response-completion): retained: {"host":"titan","kind":"worktree","path":".worktrees/response-completion","state":"kept","verification":"verified","purpose":"Reviewed fix ready for immediate authorized local merge and checked worktree removal in this turn; no off-tree evidence remains","next_owner":"session:codex:01a186f1-2641-7801-acc1-95d7c06af15e","cleanup_trigger":"After local merge and merged-tree checks, inspect ignored files and host pointers, harvest timings, unlock and remove"}
- 2026-10-29T09:30:39Z (fix/response-completion): done
  provenance: {"harness_session":"codex:01a186f1-2641-7801-acc1-95d7c06af15e","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:30:39Z (fix/response-completion): Chunked responses now expose detectable upstream truncation and route cuts to framing-validating HTTP clients; bodyless/local errors preserved. RED 11 expected failures, GREEN 105 focused tests and 806 all-selected fast-suite tests; whole-branch review accepted without findings at 66d846f. Full report attached; next action this turn is authorized local merge and cleanup.
  provenance: {"harness_session":"codex:01a186f1-2641-7801-acc1-95d7c06af15e","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:32:09Z (main): Merged locally into main at ecd5858. Merged Python tree identical to reviewed 66d846f; just check passed and merged focused server/upstream tests: 105 passed (24.42 s). Removal dispositions for .worktrees/response-completion: discard .pytest_cache/ and python/.pytest_cache/ (regenerable pytest caches); discard python/.testmondata, python/.testmondata-shm, python/.testmondata-wal (regenerable coverage selection database); discard python/.venv/ (installed dependencies, just setup regenerates); discard python/src/autonomy/__pycache__/, python/src/autonomy/egress/__pycache__/, python/tests/__pycache__/ (bytecode). Four attached evidence/review files are listed by tasks show and byte-identical on main; no scratch/raw copies remain. Worktree clean, branch merged, no submodules; tt-report ran. No host pointer was introduced; launcher/user-systemd pointer scan found none.
