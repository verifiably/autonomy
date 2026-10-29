---
id: autonomy-26f787
title: Wait for request completion before closing successful framing-test proxies
status: todo
priority: 3
size: xs
complexity: low
process: direct
created: 2026-10-29T09:55:37Z
updated: 2026-10-29T10:10:49Z
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
