---
id: autonomy-9c73d5
title: Make the egress close-race fixture wait until its closer thread has started
status: todo
priority: 3
size: xs
complexity: low
process: direct
created: 2026-10-28T19:57:23Z
updated: 2026-10-28T19:58:31Z
depends: []
tags: []
source: ops-2dee86
agent: codex
origin: agent
---

Incidental finding during ops-2dee86, not a publication regression. python/tests/test_egress_server.py::test_a_close_racing_a_new_worker_never_joins_an_unstarted_thread failed in the fast check with RuntimeError: cannot join thread before it is started; the unchanged baseline had passed 791 tests, and focused plus required fast reruns passed. The fixture assigns outcome['closer'] before calling closer.start(), while the test's main thread waits only for that dictionary entry before join(). Preserve the intended overlap of server worker startup and server close; coordinate fixture readiness so it cannot join its own closer before start. Keep the production close/start assertions and bounded cleanup, rather than widening timeouts or modifying product behavior. Verify the synchronization deterministically through the documented just test-one route, then just test-fast. Related test-maintenance task autonomy-1c355a covers other hang/leak findings, not this readiness race. Evidence: ops-2dee86 attachment autonomy-fast-failed.log.

## Notes

- 2026-10-28T19:57:23Z (add): created
  provenance: {"harness_session":"codex:01a183c3-cdb6-7bf0-bdee-ea9db2b6fb1b","harness_session_source":"CODEX_THREAD_ID","origin":"agent"}
- 2026-10-28T19:58:31Z (main): concerns: autonomy-e4c0b5 defect — the close-race regression fixture can publish its closer before start and then join an unstarted thread.
