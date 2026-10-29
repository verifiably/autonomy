---
id: autonomy-26f787
title: Wait for request completion before closing successful framing-test proxies
status: todo
priority: 3
size: xs
complexity: low
process: direct
created: 2026-10-29T09:55:37Z
updated: 2026-10-29T10:11:10Z
depends: []
tags: []
source: autonomy-c9508e
agent: codex
origin: agent
---

The merged baseline for the closed-messages policy (no code edits) failed test_successful_responses_have_valid_http_framing[empty304]: 805 passed, 1 failed. HTTPResponse.read returns immediately for 204/304; the test calls server.close before the worker finishes its post-response gate check, so the request can be recorded route-closed rather than complete. The same test was added in ecd5858. Make the success test synchronize with worker completion/recording before explicitly closing the route, with a bounded existing join/event rather than a sleep; retain all framing assertions. Keep the separate deliberate route-stop tests unchanged. Reproduce the ordering deterministically and verify both empty status variants. This is a test-ordering finding, not evidence of a provider capability escape.

## Notes

- 2026-10-29T09:55:37Z (add): created
  provenance: {"harness_session":"codex:01a186e7-b040-7ec0-b7e3-b46b220e04a6","harness_session_source":"CODEX_THREAD_ID","origin":"agent"}
- 2026-10-29T09:55:52Z (fix/closed-messages): concerns: autonomy-c9508e defect — successful empty-body framing tests can close the route before their worker records completion, making the baseline intermittently fail.
- 2026-10-29T10:10:49Z (fix/closed-messages): Created persistent scratch on titan at $WORK_ROOT/autonomy/autonomy-26f787 for the original failed baseline log. Owner autonomy-26f787; contents mutable and not yet checkpointed. The raw log contains the host worktree root, which the executing layout checker bans (WORK_ROOT); preserve it here and attach a portable derivative.
- 2026-10-29T10:10:50Z (fix/closed-messages): attached: initial-baseline-portable.txt (4345 bytes): Portable derivative of the initial 805-pass/1-failure baseline; original host-path bytes retained under this task on titan
- 2026-10-29T10:11:09Z (fix/closed-messages): Portable attachment mapping: <WORKTREE> = /mnt/ssd3/work/autonomy/.worktrees/closed-messages on titan (main-checkout spelling .worktrees/closed-messages). Original raw bytes at $WORK_ROOT/autonomy/autonomy-26f787/baseline.log; SHA-256 8f56d4435d3149e29afbd7de96f04b8954520ceb1f349e68dcd45a792f4bc175. The portable derivative is attached and does not replace the raw evidence.
- 2026-10-29T10:11:09Z (fix/closed-messages): retained: {"host":"titan","kind":"evidence","path":"$WORK_ROOT/autonomy/autonomy-26f787/baseline.log","state":"kept","verification":"verified","purpose":"Exact initial merged-baseline failure, 805 passed and empty304 route-closed versus complete; portable derivative attached because raw bytes contain banned host layout","next_owner":"task:autonomy-26f787","cleanup_trigger":"After resolving and reviewing the framing-test ordering defect, preserve raw evidence through the executing layout checker if possible and recheck disposition; do not discard the only raw copy","sha256":"8f56d4435d3149e29afbd7de96f04b8954520ceb1f349e68dcd45a792f4bc175"}
