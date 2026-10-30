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
updated: 2026-10-30T18:59:07Z
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
- 2026-10-30T18:32:12Z (main): User approved pilot push 5/5 of d4a6baeb4cdc6686b45059bb9f7d9eb1175a80a6; pushed; run 41107688532. Pilot push cap now exhausted; any further run or corrective push needs separate approval.
- 2026-10-30T18:37:12Z (main): Diagnostic run 41107688532 (head d4a6bae) succeeded: 1396/1396, proof 45/45; e21 1.56 s on the runner this time (passed, so its per-step timings were not printed). --durations=30: the slowest test was the new test_the_actor_times_every_step at 9.20 s (steps: dns resolve first, doc-v4 connect, sweep); locally it takes 0.31 s (2 runs). The 30 slowest are otherwise lease/timeout tests at their designed 2-5 s. So the slowness is intermittent and inside an actor step, not the proxy or the lease logic; the leading hypothesis (DNS resolution inside the sandbox on the runner, first lookup slow and variable) is unconfirmed. A docker ubuntu:24.04 reproduction failed to model the runner (docker bind-mounts its own resolv.conf). Next evidence needs a hosted run: per-step timings recorded on pass too (run_actor appends to a file a final always() workflow step prints), plus the runner's /etc/resolv.conf target and nsswitch hosts line, and a timed getaddrinfo inside an actor-shaped bwrap sandbox. Log sha256 bbbe784b8ffacf61d34d33a05b52c4fe65488046be88dcd3a6b8a9077449ca93.
- 2026-10-30T18:37:13Z (main): parked (waiting on user, decision): User approves (or redirects) the next diagnostic: per-step actor timings recorded on pass as well as failure and printed by an always() workflow step, plus the runner's resolver configuration and a timed sandboxed getaddrinfo, as one frozen revision on the pilot branch for a separately approved push. Then the agent prepares it and brings the SHA.
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T18:57:58Z (main): User correction 2026-10-30: the 9.20 s duration of test_the_actor_times_every_step includes proxy startup, actor launch and cleanup; it does not establish that an actor step caused the delay. DNS remains unconfirmed. Next diagnostic per user: PYTEST_ADDOPTS -rsP --durations=30, print world.actor_timings in the timing test, resolver-configuration output; standalone DNS probe deferred.
- 2026-10-30T18:59:06Z (main): Smaller diagnostic frozen at a8338d7ba569c577ffdeb8e07f7fe7109a8042fd on the pilot branch (parent d4a6bae): PYTEST_ADDOPTS -rsP --durations=30; test_the_actor_times_every_step prints proxy_start_to_close and world.actor_timings; workflow step 'Show the resolver configuration' (ls/readlink/cat /etc/resolv.conf, nsswitch hosts line; no lookup); standalone DNS probe deferred. Verified locally: -rsP shows both timing prints for passing tests; test_egress_session.py + test_front_door.py 52 passed; just check 0; 0 test lines removed; resolver commands run under bash -euo pipefail. Awaits approval for one diagnostic push beyond the exhausted cap.
- 2026-10-30T18:59:07Z (main): parked (waiting on user, approval): User approves one diagnostic push of a8338d7ba569c577ffdeb8e07f7fe7109a8042fd to the pilot branch (beyond the exhausted 5-push cap); then the agent rechecks head, visibility and SSH, pushes, and reads the step timings and resolver configuration from the hosted log.
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
