---
id: autonomy-1ba43a
title: "Egress e21 test outlives its 30 s proxy lease on GitHub's ubuntu runner (closes by lease, not close)"
status: todo
priority: 1
size: s
complexity: mid
process: direct
created: 2026-10-30T18:15:10Z
updated: 2026-10-30T18:15:10Z
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
