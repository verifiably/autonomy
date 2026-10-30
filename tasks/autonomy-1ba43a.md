---
id: autonomy-1ba43a
title: "Egress e21 test outlives its 30 s proxy lease on GitHub's ubuntu runner (closes by lease, not close)"
status: doing
priority: 1
size: s
complexity: mid
process: direct
owner: main
created: 2026-10-30T18:15:10Z
updated: 2026-10-30T18:32:11Z
started: 2026-10-30T18:20:33Z
depends: []
tags: [egress]
source: autonomy-23aeff
agent: claude-code/claude-opus-5-5
origin: agent
---

Observed 2026-10-30 in main's hosted run 41104200861 (verifiably/autonomy, ubuntu-24.04, head 3c5f272): tests/test_egress_session.py::test_e21_the_model_route_is_the_actors_only_way_out failed at its last assertion, (closed.cause, timed_out, findings) == ('lease', False, ()) instead of ('close', ...). Every earlier assertion in the test passed. The proxy returns 'lease' only when 30 s (World.start default lease) elapse without renew or close (egress/proxy.py control_loop), so on the runner the span from proxy start to session.close exceeded 30 s. The same code passed in runs 41095831866 and 41101402802; the only code change since is tools/ops-check. Locally the test takes 1.7 s (3 runs). Per-module time on the runner (from log line timestamps): test_egress_session.py 58.8 s in the passing run 41101402802, 76.1 s in the failing run, so e21 alone runs near or past the lease there. Which actor step is slow on the runner is not yet known: pytest prints no per-test durations and the report's per-step seconds are not logged. Next: capture per-test and per-step timings on the runner (e.g. PYTEST_ADDOPTS -rs --durations=30 in the workflow, and print the actor report on failure), find the slow step, then fix the cause, or give the test a lease that states what it is bounding. Do not just raise the lease without knowing what is slow. Blocks a green main for autonomy-23aeff.

## Notes

- 2026-10-30T18:15:10Z (add): created
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID","origin":"agent"}
- 2026-10-30T18:20:33Z (main): started
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T18:23:15Z (main): Diagnostic prepared on the pilot branch, frozen at d4a6baeb4cdc6686b45059bb9f7d9eb1175a80a6 (code = main 3c5f272 plus this change): PYTEST_ADDOPTS -rs --durations=30; the e21 actor times every step with time.monotonic and its own span; run_actor adds launch-to-exit; e21 prints prove, proxy_start_to_close and those timings to stdout before its assertions (pytest shows it on failure). Lease and every assertion unchanged (0 removed test lines). New test_the_actor_times_every_step RED (World has no actor_timings) then GREEN; test_egress_session.py + test_front_door.py 52 passed; just check 0. Locally e21 proxy_start_to_close 1.57 s. Awaits user approval for pilot push 5/5.
- 2026-10-30T18:23:16Z (main): parked (waiting on user, approval): User approves pilot push 5/5 of d4a6baeb4cdc6686b45059bb9f7d9eb1175a80a6; then the agent pushes the pilot branch, reads --durations and the e21 timings from the hosted log (rerunning only with approval if e21 passes), and diagnoses the slow step.
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T18:32:11Z (main): resumed
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
