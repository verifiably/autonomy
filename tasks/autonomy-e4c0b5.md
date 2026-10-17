---
id: autonomy-e4c0b5
title: "Envelope egress plan: model route, namespace listener, sandboxed model proxy and its close transition (decision 13; rows E21-E22 launch arms, live pi recipe)"
status: doing
priority: 2
size: l
complexity: high
process: planned
owner: main
created: 2026-10-17T11:25:57Z
updated: 2026-10-17T11:55:58Z
started: 2026-10-17T11:26:48Z
depends: []
parent: autonomy-d9adef
tags: []
source: docs/specs/2026-10-12-envelope-design.md
agent: claude-code/claude-opus-5-5
spec: docs/specs/2026-10-12-envelope-design.md
---

Spec §13 item 5, from the approved amendment autonomy-efa755 (decision 13, approved 2026-10-17). Independent of the beliefs and science slices; lands before Plan B2 (autonomy-f6efe8) is needed.

Scope: the `egress` module (route parsing with the `anthropic-messages` dialect and its closed lists, step 2's `route-unknown`/`route-invalid`/`credential-unavailable`); `--model-route` on `autonomy run`; the denied set's `<config>` and credential entries; the probe's IPv4 and IPv6 `ENETUNREACH` check; removal of Plan A's `network` field and `host` value; the single-threaded namespace helper (NS_GET_USERNS, then the netns, listener on 127.0.0.1:4780 passed back over SCM_RIGHTS, the orchestrator keeping no copy); the model proxy in its own bwrap (fixed builder, no --die-with-parent, static check at step 7) with strict HTTP/1.1, the body and header checks, its own upstream framing, streaming, `egress.jsonl` and `proxy.log`, the lease, and the close transition (non-blocking upstream writes under the lock, waits outside it); step 9's proxy start and listener hand-off before the release (`egress-unproven`); close step 0 concurrent with the seal; the orphan path; the `admit`/`settle` join points as no-ops. Rows E21 and E22 on their launch arms, and a live recipe running pi through B1's launch path with its proxy to the real API (never in the suite). Full-run arms join B2.

Where: envelope spec decision 13, §3 steps 2, 7, 9 and Close, §6, §7, §8, §9 rows, §12 E20-E22, §13 item 5, §14; python/src/autonomy/sandbox/ (spec.py network, bwrap.py launch and _GATE), run.py, cli.py; autonomy-efa755's attached helper.py and host.py (the namespace listener as checked). Overlap risk: autonomy-6b1f9f also edits the sandbox launch.

## Notes

- 2026-10-17T11:26:48Z (main): started
  provenance: {"harness_session":"claude-code:8d3345f1-e50f-41b0-b5f0-0aedb418be65","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-17T11:55:58Z (main): plan drafted: docs/plans/2026-10-17-envelope-plan-egress.md on branch plan-egress (8387070), 10 tasks; B2 wiring items noted on autonomy-f6efe8. Agent plan review and a dry run of the plan's code in a /tmp copy dispatched before the user's review.
