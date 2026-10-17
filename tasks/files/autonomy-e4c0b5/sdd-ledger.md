# SDD ledger — plan: docs/plans/2026-10-17-envelope-plan-egress.md

Spec: docs/specs/2026-10-12-envelope-design.md (reachable). Branch plan-egress; main merged in (5fc8f6e, task records only). Baseline just test-fast: 443 passed.
Branch start for final review: 626730d's merge-base with main (use `git merge-base main HEAD`).

## Pre-flight scan

Evidence base: five dry runs applied the plan's code verbatim to a scratch copy; dry run 5 (e9fcf00 text) applied all ten tasks unchanged, 774 passed, no flakiness. One test (TCP-connect watch, Task 9) was added after dry run 5 and has not been through a dry run.

| pair / task | produces → consumes | finding |
|---|---|---|
| T1 → T9 | bwrap `launch(before_release=)`, `read_info`, static `check_sources(sources, denied, exempt)` → session start/attach | consistent (dry run 5) |
| T2 → T3 | `load_route`, `RouteRefused`, `egress_denied` → run.py step 2, cli `--model-route` | consistent |
| T2 → T6/T7/T8/T9 | `Route`, `Operation`, `errors.Refused`/`EgressUnproven`, `always_dropped` → upstream/server/proxy/session | consistent |
| T2, T6, T7 share egress_fixtures.py | T2 creates (pi_route, to_toml, write_route, write_credential); T6 appends Tls/tls/Seen/FakeUpstream; T7 appends request helpers + serve/served | additive, no overlap |
| T4 → T7 | request.py `parse_head`, `forwarded_headers`, `frame`, `refusal`, `MAX_HEAD` → server | consistent |
| T5 → T7 | dialect `parse_body`, `check_body` → server | consistent |
| T6 → T7/T8/T9 | `Gate`, `RouteClosed`, `UpstreamError`, `connect`, `read_response` → server, proxy, session | consistent |
| T7 → T8 | `ProxyServer`, `Recorder`, `Hooks`, `Allowance` → proxy.py | consistent |
| T8 → T9 | proxy `main`/`BOOT`/control messages, helper `make_listener`/`MODEL_URL` → session | consistent |
| T9 closing.py | SEVERITY gains egress-unproven/-lost/-close-timeout | only T9 touches closing.py |
| T10 | consumes all; adds test_egress_live.py (not in the File structure list — doc omission only) | noted, no ruling needed |
| each task T1–T10 self-consistency | tests specified vs code specified | verified by dry runs 1–5 (all tests pass verbatim) |

Ruling: implementers run on sonnet, not the cheapest tier, though the plan carries complete code — tasks are 200–1150 plan lines with bwrap/TLS/concurrency tests where a stumble costs turns — costs some tokens if haiku would have sufficed.
Ruling: task reviews for T6–T9 (gate, server, proxy process, session: concurrency and security boundaries) run on opus; T1–T5 and T10 on sonnet — risk-scaled per Model Selection — if wrong, a sonnet review misses a subtle T1–T5 defect that the opus final review must catch.

## Tasks
Task 1: dispatched implementer (sonnet), BASE c27da02
Task 1: review (sonnet) — Spec ✅, Approved; ⚠️ items (no `_read_info`, no `network=` callers) checked by controller: clean.
Task 1: minor (deferred): test_stdio.py test name `..._under_network_none` refers to the removed network mode.
Task 1: minor (deferred): launch hook tests use 0.5 s sleeps to show "not yet released"; weak on a slow host.
Task 1: complete (commits c27da02..c66a9dc, review clean)
Task 2: dispatched implementer (sonnet), BASE c66a9dc
Task 2: implementer DONE_WITH_CONCERNS (RED run after writing code, by moving package aside; test-fast warning = baseline coverage sysmon warning) — observations, proceed to review
Task 2: review (sonnet) — Spec ✅ (verbatim vs brief), Approved; ⚠️ (check_binds/SandboxSpec signatures) resolved by the implementer's passing E22 test against real check_binds.
Task 2: minor (deferred): route.py `port or 443` turns explicit `:0` into 443 (silent fallback); trailing-colon authority accepted.
Task 2: minor (deferred): route.py header_tokens keys lowercased — case-variant duplicate TOML keys silently overwrite.
Task 2: minor (deferred): route.py duplicate operations keyed on (method, path) — same path with different queries must be merged (likely intended).
Task 2: minor (deferred): route.py upstream hostname not validated as DNS name/IP (no CRLF possible).
Task 2: minor (deferred): test_egress_route invalid cases assert only the code, not the message; RED shown only by hiding the package.
Task 2: minor (deferred): test_a_credential_owned_by_someone_else fails when run as root.
Task 2: minor (deferred): load_route reads data then resolves path separately (TOCTOU on operator config).
Task 2: complete (commits c66a9dc..9767fc6, review clean)
Task 3: dispatched implementer (sonnet), BASE 9767fc6
Task 3: review (sonnet) — Spec ✅, Approved; ⚠️ (RouteRefused .code/.message, load_route signature, test helpers request()/runs()) checked by controller in Task 2's code and test_run.py.
Task 3: minor (deferred): run.py execute docstring line ~105 chars (brief wording).
Task 3: complete (commits 9767fc6..5f41b37, review clean)
Task 4: dispatched implementer (sonnet), BASE 5f41b37
Task 4: implementer DONE (RED after code via stash; notes brief lists always_dropped as consumed but code doesn't use it)
Task 4: review (sonnet) — Spec ✅, Approved; ⚠️ always_dropped unused in request.py: route.py rejects such names at parse time (reviewer checked); ⚠️ MAX_HEAD enforcement lives in Task 7's reader (brief uses it) — carried to Task 7 review.
Task 4: minor (deferred): no tests for bare \n/\r in header values or empty tokens (`a,,b`) — code handles them.
Task 4: minor (deferred): header-refused message echoes actor tokens via %r (JSON body only).
Task 4: complete (commits 5f41b37..85cdd88, review clean)
Task 5: dispatched implementer (sonnet), BASE 85cdd88
Task 5: review (sonnet) — Spec ✅, Approved; ⚠️ Operation fields/pi_route defaults: resolved by the passing tests against Task 2's code.
Task 5: minor (deferred): dialect json.loads accepts overflowing floats (1e999 → inf); harmless (bytes forwarded, no numeric checked position).
Task 5: minor (deferred): image/document block without `source` passes with sibling keys unchecked (closed lists bound it).
Task 5: minor (deferred): no tests for string system/content passing, wrong-type messages/tools/content, non-string source.type.
Task 5: minor (deferred): test_a_whole_body_walk_would_refuse_the_clients_data partly tautological local walk (plan-mandated; the check_body call is the real assertion).
Task 5: complete (commits 85cdd88..3d20c6e, review clean)
Task 6: dispatched implementer (sonnet), BASE 3d20c6e
Task 6: review (opus) — Spec ✅, Needs fixes: 1 Important (plan-mandated).
Task 6: Ruling: fix the plan-mandated reader gap (header names not token-checked, CTL/NUL in values, bare CR in reason phrase pass through response_head) — spec decision 13 requires strict HTTP/1.1 and the always-dropped filter in both directions; the values check shows the plan meant it — if wrong, a few lines of stricter parsing refuse an upstream the plan would have relayed.
Task 6: Ruling: OP_NO_RENEGOTIATION (reviewer's Minor) enters the fix round — a TLS 1.2 renegotiation ClientHello from recv outside the gate breaks the Global Constraint "no call that can put a byte upstream runs after the close transition"; that is a constraint violation, not polish — if wrong, a one-line option forbids renegotiation the API never uses.
Task 6: minor (deferred): reader RouteClosed.attempted inconsistent (wait-path False vs EOF-path True); Task 7 tracks `forwarded` itself.
Task 6: minor (deferred): SSLEOFError treated as clean EOF — truncated close-delimited body indistinguishable; deserves a comment.
Task 6: minor (deferred): `transfer-encoding: gzip, chunked` accepted; only chunked decoded, gzip label dropped (silent loss).
Task 6: minor (deferred): select.select fails for fds >= 1024 (ValueError → upstream error).
Task 6: minor (deferred): TCP-connect hangup test doesn't pin the connect phase.
Task 6: minor (deferred): E22 lock negative test exercises threading.Lock, not production code (plan-mandated).
Task 6: minor (deferred): missing coverage for ActorGone(attempted=True)/RouteClosed in read_response, SendFailed on reset, cut.
Task 6: minor (deferred): FakeUpstream leaks listener/accept thread when tests don't call stop(); stop() doesn't wake accept().
Task 6: fix round 1/5 (2 addressed, 0 open — strict response heads; OP_NO_RENEGOTIATION; commits 62466b5..71e7efe)
Task 6: minor (deferred): upstream.py imports route.py's private `_TOKEN` across modules.
Task 6: complete (commits 3d20c6e..71e7efe, review clean)
Task 7: dispatched implementer (sonnet), BASE 71e7efe
Task 7: implementer DONE (5138adf); untracked python/.testmondata-shm/-wal appear (.gitignore names only python/.testmondata — pre-existing gap, not this plan's)
Task 7: review (opus) — Spec ✅ (byte-for-byte), MAX_HEAD enforced (server.py:244-253), reader OSError/RouteClosed handled; Needs fixes: 2 Important (both plan-mandated).
Task 7: Ruling: fix the accept loop (any OSError from accept() ends accepting silently; reproduced with fd exhaustion — later connects hang unrecorded) — retry with a short backoff while the server is open, exit only when shut or the gate is closed; append a worker thread to _threads only after start() succeeds, and close the conn if start fails — the actor is untrusted and the core rule forbids silent failure — if wrong, a dead listener's error path loops with backoff until close.
Task 7: Ruling: make the worker's finally robust — _finish (the record line) runs before settle, settle and the recorder are guarded so _release(conn) always runs — spec §decision 13 says settle runs "when the response stream ends" and does nothing beyond the record line until an allowance exists, so its order relative to the line is not pinned; line-first means a slow settle can't let the close overwrite a completed line with route-closed — if wrong, a future allowance that wants its result in the line reorders two calls (B2 / autonomy-9e8a43).
Task 7: minor (deferred): route-closed refusals recorded inconsistently by stage (ended complete/403 vs route-closed vs route-closed/status null); oversize head gets no seq.
Task 7: minor (deferred): pre-body refusals (request-too-large, header-refused, operation-refused) close without draining — a client still writing may see a reset instead of the 403.
Task 7: minor (deferred): actor-hang-up test checks _actors/_upstreams after close and never checks worker threads (Review Focus 3 says "no worker thread is left").
Task 7: minor (deferred): make_served leaks the records fd per instance.
Task 7: minor (deferred): _finish and the close's finalization hold the server lock across disk writes (serializes on I/O).
Task 7: ⚠️ concurrent close() returns False before the first close has written the closing line — Task 8's control loop must not exit/report on False; carried to Task 8 review.
Task 7: fix round 1/5 (2 addressed, 0 open — accept retry + start-after-register; finally writes line before settle and always releases; commits 5138adf..d37ec3a)
Task 7: minor (deferred): serve() silently closes the listener and returns if the accept thread cannot start (was a raised RuntimeError).
Task 7: minor (deferred): if _release(upstream) raises in the finally, _finish/settle are skipped and close() backfills route-closed.
Task 7: minor (deferred): a persistent accept error retries every 50 ms with no proxy.log line (invisible to operator).
Task 7: complete (commits 71e7efe..d37ec3a, review clean)
Task 8: dispatched implementer (sonnet), BASE d37ec3a
Task 8: implementer DONE_WITH_CONCERNS (5abb6c8; RED by deleting impl files after scripted extraction — process only)
Task 8: review (opus) — Spec ✅ (byte-for-byte), Approved; Task 7's concurrent-close ⚠️ resolved: main is the only caller of server.close and reports `closed` only after it returns. ⚠️ carried to Task 9 review: session closes its listener copy after send on success and error paths; credential-invalid → egress-unproven mapping; ready 10 s / listening 5 s / close 5 s-then-kill timeouts; helper's no-os.setns branch (unexercised on 3.14).
Task 8: minor (deferred): fds received via recv_fds are inheritable (no MSG_CMSG_CLOEXEC) in helper.make_listener and proxy receive_message — latent (all spawns use close_fds=True).
Task 8: minor (deferred): renew/close/route control messages carrying fds leak them.
Task 8: minor (deferred): a second `listener` message is accepted; the first listener's accept thread keeps running until exit.
Task 8: minor (deferred): invalid JSON / non-object control message, bad base64 or missing "lease" crash main without a closed line.
Task 8: minor (deferred): a renew arriving at the deadline can extend a just-expired lease (deadline not re-checked after select).
Task 8: minor (deferred): SIGTERM before the route message is swallowed (no-op handler + PEP 475 retry).
Task 8: minor (deferred): proxy process tests call blocking receive_message with no timeout (a regression hangs the suite).
Task 8: minor (deferred): test hygiene — unclosed pipes/socketpairs, unused write_credential/upstream, timing-sensitive 0.9<…<1.5 lease bound.
Task 8: complete (commits d37ec3a..5abb6c8, review clean)
Task 9: dispatched implementer (sonnet), BASE 5abb6c8
Task 9: implementer DONE_WITH_CONCERNS (0f333ed): one unexplained failure of test_a_failed_start_leaves_no_proxy_and_no_descriptor[egress-ready] in the pre-commit test-fast (passed in every rerun: 4 file runs, 6 -k runs, 3 full suites); commit landed after the failing test-fast (chained with ;)
Task 9: review (opus) — Spec ✅ (byte-identical), Task 8 ⚠️ items verified (listener copy closed in finally; credential-invalid → egress-unproven; timeouts on this side; Popen close_fds covers inheritable fds). Needs fixes: 1 Important (plan-mandated, test-only): fd-count flake — orchestrator() PIPE never closed + pytest.raises-as cycle keeps it alive until GC, so the count drops mid-test.
Task 9: Ruling: fix the test's accounting (close orchestrator() pipes; gc.collect before measuring; compare fd sets: nothing new after) — a flaky pre-commit test erodes the gate and the production path was shown deterministic — if wrong, the set comparison misses a leak that also closes an older fd in the same window (unlikely).
Task 9: minor (deferred): kill_orphan re-settles an already-settled run (no check for a later egress-closed/-lost/-close-timeout); B2 must call it only for unsettled runs.
Task 9: minor (deferred): kill() after release raises OSError(EBADF) instead of close()'s RuntimeError.
Task 9: minor (deferred): start leaks fds if os.open/socketpair/pipe fail, or Popen raises non-OSError.
Task 9: minor (deferred): proxy EOF on control socket reported as "no answer within 10 s".
Task 9: minor (deferred): send_message swallows a failed listener send; surfaces only as the 5 s listening timeout.
Task 9: ⚠️ B2 wiring (check_proxy at step 7, attach as before_release, close with seal, exited() → egress-lost, kill_orphan from run close) — B2's scope, not verifiable here.
Task 9: fix round 1/5 (1 addressed, 0 open — orchestrator pipes closed, gc.collect + fd-set comparison; commits 0f333ed..c6bcafe)
Task 9: complete (commits 5abb6c8..c6bcafe, review clean)
Task 10: dispatched implementer (sonnet) for Steps 1–6 only, BASE c6bcafe; Step 7 (live recipe, real API) held for the user's go per plan
Task 10: review (sonnet) — Spec ✅ (Steps 1–6), Approved; ⚠️ live-script signatures (egress_denied, launch before_release, EgressSession.start/pidfd/kill) checked by controller against code: match.
Task 10: minor (deferred): egress_live.py docstring's exit-0 condition is looser than `verdict`.
Task 10: minor (deferred): spec status text sits mid-paragraph; "Revised after review round 1…" runs on; implemented-on date 2026-10-17 to recheck at landing.
Task 10: minor (deferred): egress_live._prompt leaks pipe fds if launch raises; to_pi double-closed if actor.wait fails.
Task 10: complete for Steps 1–6 (commits c6bcafe..d20efa1, review clean); Step 7 (live recipe) awaits the user's go.
Final review: dispatched (opus), range c27da02..d20efa1 (execution start → head; c27da02 is the branch after merging main's task records)
Full suite (just test) at d20efa1: 784 passed in 82 s
Final review (opus): With fixes — Critical 0, Important 1 (route-closed refusals recorded inconsistently: Refused path ended=complete/403 vs RouteClosed path ended=route-closed vs backfill status null), Minor 7; deferred-minor triage: all keep deferred except Task 6 `gzip, chunked` (fix before merge).
Final: Ruling: fix Important #1 (route-closed → ended "route-closed" on the Refused path; held-request test asserts ended/status; Recorder docstring documents null status in the backfill) — spec decision 13 / E22 say requests cut by the close end route-closed — if wrong, a field value changes before any consumer exists.
Final: Ruling: fix the `gzip, chunked` loss (transfer codings must be exactly ["chunked"], else UpstreamError) — reviewer triaged it fix-before-merge; fail-early rule and Task 6's strict-head precedent — if wrong, an upstream using stacked codings gets a 502 instead of mislabeled bytes.
Final: Ruling: fix final Minor 4 (serve() silently closes the listener if the accept thread can't start, yet the control loop answers `listening`) in the same fix pass — it contradicts decision 13 ("cannot take the listener makes the run unwired"); a bool return + `error` reply is small — if wrong, a few lines handle thread exhaustion nobody hits.
Final: minor (deferred): a cut stream ends in clean EOF indistinguishable from complete over HTTP (pi detects missing message_stop); abortive close (SO_LINGER 0) on non-complete endings is a hardening task.
Final: minor (deferred): upstream.py docstring/global constraint overstate the close boundary — OpenSSL can write protocol records (KeyUpdate reply, alerts) from recv; narrow to "no request byte".
Final: minor (deferred): probe's ENETUNREACH check can't distinguish shared/unshared net on a host without a default route; compare netns inode with the orchestrator's.
Final: minor (deferred): no pytest-timeout hang guard; with blocking receive_message in proxy tests a regression hangs the pre-commit hook.
Final: minor (deferred): Review Focus 3 "no worker thread is left" not asserted in the hang-up test (one-line assert).
Final: correction: Task 8's "SIGTERM before the route message is swallowed" note is inaccurate — set_wakeup_fd precedes the handler, the byte stays in the pipe, control_loop returns `term` on entry (postponed, not lost).
Final: B2 requirements carried to autonomy-f6efe8: kill_orphan only for unsettled runs (or rebuild from the recorded event); MSG_CMSG_CLOEXEC on received listener fds; split EgressSession.close into send/wait (close step 0 concurrent with the seal).
Final: deferred-to-live: Step 7 should also send one over-limit body through pi to settle the no-drain (reset vs 403) question.
Final: corrective round 1 — 3/3 findings addressed (commits d20efa1..80fd1ef); new Important: 80fd1ef committed python/.testmondata-shm/-wal (binary); .gitignore names only python/.testmondata (the pre-existing gap noted at Task 7).
Final: Ruling: round 2 removes the two files from the index and adds `python/.testmondata-*` to .gitignore — the ignore gap is the cause, and fixing only the index would recur on the next `git add -A` — if wrong, one ignore line too broad for files nobody else names that way.
Final: minor (deferred): test_egress_server failed-serve test calls serve() again on the fixture's served server — orphaned first listener + ~2.5 s join wait in teardown; use a fresh ProxyServer.
Final: minor (deferred): Recorder docstring says a backfilled line "has a null status", but the backfill copies a status a worker already set; say "usually null" or null it.
Final: corrective round 2/5 (1 addressed, 0 open — testmon WAL/shm untracked, .gitignore python/.testmondata-*; commits 80fd1ef..4ce4579). Final review clean.
