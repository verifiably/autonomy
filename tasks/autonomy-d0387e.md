---
id: autonomy-d0387e
title: "Establish the minimal closed policy for tool, source, model and feature positions below the body's top level"
status: doing
priority: 2
size: s
complexity: mid
process: direct
owner: research/egress-policy
created: 2026-10-19T00:11:43Z
updated: 2026-10-29T02:12:39Z
started: 2026-10-29T02:02:43Z
depends: []
parent: autonomy-3a06d3
tags: []
source: docs/notes/2026-10-18-egress-proof-gaps-brief.md
agent: codex
---

Question: Which positions below the top level of an anthropic-messages body can carry tools, sources, models or provider features outside the dialect's checked lists (message keys and roles, block keys, the values of allowed top-level fields such as output_config, thinking and tool_choice, and fallbacks), and which minimal fail-closed policy covers them? Should fallbacks be refused at route load or validated?

Where to start: python/src/autonomy/egress/dialect.py::check_body and _blocks, egress/route.py operation parsing, python/tests/test_egress_dialect.py and test_egress_route.py; README model-route example (its inline-tools and mid-conversation-output-config betas) and fallbacks warning; envelope design decision 13; docs/notes/2026-10-18-egress-proof-gaps-brief.md. autonomy-58799c preserves the pi 1.1.0 live finding. pi 1.1.0's pinned install bundles @anthropic-ai/sdk 0.129.0: resources/beta/messages/messages.d.ts names fallbacks and output_config, an offline schema source.

Bound: trace the existing validation paths, read the bundled SDK request types, and use minimal synthetic request/route cases to establish which sub-top-level positions pass unchecked, including the reported system/output_config message shape and any message-level tool or source position. Close message and block keys to an allow-list from captured pi traffic and the SDK types, so the policy holds whatever the provider's full schema is; a position that carries tools or sources gets the top-level checks or refusal. Compare refusing fallbacks with checking every fallback model. Name explicitly any position left out of scope, and any policy that needs a reviewed contract change. No proxy implementation, generalized schema walker, dependency change, live API call or unrelated provider audit.

Expected result: record the demonstrated accepted/refused shapes, coverage boundary and smallest recommended policy on this task and in the brief. Distinguish observed code behavior and SDK types from unverified provider behavior. Provide concrete acceptance cases so the waiting idea can be scoped without repeating the investigation.

Ideas it wakes: On completion, run tasks note autonomy-58799c --no-reviewed "<finding>" before this result's branch merges.

## Notes

- 2026-10-29T02:02:43Z (main): started
  provenance: {"harness_session":"codex:01a18551-e297-7d03-ac46-c87da73b2eed","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T02:02:59Z (research/egress-policy): resumed
  provenance: {"harness_session":"codex:01a18551-e297-7d03-ac46-c87da73b2eed","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T02:04:39Z (research/egress-policy): Direct bounded research in .worktrees/egress-policy (research/egress-policy); hydrated with just setup. Baseline just test: 791 passed in 86.64s. SDK 0.129.0 is present in pinned pi 1.1.0. Its inline definitions use tool_addition blocks, already refused by the current block vocabulary; distinguish unchecked synthetic keys from demonstrated provider capability.
- 2026-10-29T02:05:31Z (research/egress-policy): Created persistent scratch on titan at $WORK_ROOT/autonomy/autonomy-d0387e for synthetic cases, offline pi payload capture, and SDK provenance. Owner autonomy-d0387e; contents mutable, not yet checkpointed.
- 2026-10-29T02:12:30Z (research/egress-policy): attached: test_policy_probe.py (8848 bytes): 67 current-verdict characterization cases with proposed policy verdicts; run through just test-one
- 2026-10-29T02:12:31Z (research/egress-policy): attached: route-example.toml (1043 bytes): README example route used by the characterization probe; placeholder credential path, never opened
- 2026-10-29T02:12:33Z (research/egress-policy): attached: pi-payloads.json (6007 bytes): Four offline pi 1.1.0 SDK transport captures from synthetic inputs; no provider call
- 2026-10-29T02:12:34Z (research/egress-policy): attached: capture-pi.mjs (2588 bytes): Reproduce offline pi transport captures with substituted fetch and assert-based self-checks
- 2026-10-29T02:12:36Z (research/egress-policy): attached: source-hashes.json (594 bytes): SHA-256 provenance for pinned SDK 0.129.0 and pi-ai serializer inputs
- 2026-10-29T02:12:37Z (research/egress-policy): attached: probe-results.txt (3797 bytes): Characterization verdicts: 67 passed, current and proposed outcomes separated
- 2026-10-29T02:12:39Z (research/egress-policy): Result: 67 characterization cases pass; offline pi plain/effort payloads accepted, inline/fallback payloads refused. Inline definitions are tool_addition blocks (already closed), not a demonstrated escape via message keys. Unknown message/block/control keys pass; provider interpretation remains unverified. Recommend finite key/value shapes, preserving opaque client input/schema and system effort; refuse fallbacks at route load, including server-selected default. Proposed restriction of arbitrary fields/server tool types and other SDK options needs a reviewed decision-13 amendment in autonomy-58799c. Updated source brief contains matrix, precise subset and acceptance requirements. just test-fast: 791 passed, coverage warned that sysmon dynamic contexts may be incomplete.
