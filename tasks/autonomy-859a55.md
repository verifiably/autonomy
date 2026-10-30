---
id: autonomy-859a55
title: "e21 lease renewal: deferred review minors"
status: todo
priority: 3
size: xs
complexity: low
process: direct
created: 2026-10-30T22:58:06Z
updated: 2026-10-30T22:58:06Z
depends: []
tags: [egress]
source: autonomy-1ba43a
agent: claude-code/claude-opus-5-5
origin: agent
---

Deferred minors from autonomy-1ba43a's reviews (claude-code/claude-opus-5-5; round 2 by codex/gpt-6.1-sol via the user). (1) Renew once immediately when the actor starts, so a short lease does not depend on launch latency. (2) Two e21 comments in python/tests/test_egress_session.py (at proxy_started and the timings print) still describe a 30 s budget; the lease is now renewed every 10 s while the actor runs. (3) The short-lease control and renewal tests do not assert that the 2.5 s sleep ran (world.actor_timings['steps']['slow'] >= 2.5); the actor ignores unknown step kinds. (4) E21_RENEW_EVERY is tied to World.start's 30 s default lease only by a comment. (5) An asynchronous exception between thread.start() and assigning renewer leaves a started thread unjoined (stop.set() still ends it). (6) run_actor raises a bare StopIteration when the actor crashes before printing its timings line; and e21's timing print is not reached when run_actor itself raises (e.g. the 120 s wait timeout).

## Notes

- 2026-10-30T22:58:06Z (add): created
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID","origin":"agent"}
