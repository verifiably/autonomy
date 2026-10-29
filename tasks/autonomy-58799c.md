---
id: autonomy-58799c
title: "Dialect: close fallbacks and the message- and block-level positions the route does not check"
status: doing
priority: 2
size: m
complexity: mid
process: planned
owner: fix/closed-messages
created: 2026-10-17T18:24:01Z
updated: 2026-10-29T09:20:40Z
started: 2026-10-29T09:19:33Z
depends: [autonomy-d0387e, autonomy-a1d778]
parent: autonomy-3a06d3
tags: []
agent: claude-code/claude-opus-5-5
spec: docs/specs/2026-10-12-envelope-design.md
---

Why: implement the human-approved 2026-10-29 decision-13 amendment in docs/specs/2026-10-12-envelope-design.md (approved frozen revision b1a325b6b10535de846441acc3c8f9f6375a5f45; status recorded in a5d3c2b). Research autonomy-d0387e established unchecked nested control keys, including message and block positions, and characterized 67 cases plus four offline pi 1.1.0 / SDK 0.129.0 captures. [ref:brief] holds the evidence and limitations. Neither offline body acceptance nor SDK presence proves a provider escape. The design dependency autonomy-a1d778 is complete and integrated.

Done: enforce the approved finite fields and tool-type vocabulary at route load, refusing fallbacks including default; close every admitted message, block, source, client-tool, cache, citations, effort, thinking, tool-choice and metadata control object. Apply required-field, primitive, nullability, source/context and recursive route checks exactly as the approved amendment specifies. Preserve opaque client input/schema, pi plain/effort traffic, unchanged forwarded bytes, existing refusal codes and strict-JSON behavior. Update affected tests, shared fixtures and README. Prove extra-key rejection for each admitted object/variant, source/context pairings, nested effort permission, opaque data and byte preservation with no upstream connection for invalid requests. No new dependency, provider dialect, schema walker, route-schema expansion, live API, accounting, response-completion or namespace work.

Where: python/src/autonomy/egress/route.py and dialect.py; python/tests/test_egress_route.py, test_egress_dialect.py, test_egress_server.py and egress_fixtures.py; README model route. Read the approved spec and [ref:brief]. Research evidence stays immutable on autonomy-d0387e: those probes assert old verdicts and are not fix tests. Produce and obtain human review of an implementation plan before product code changes; use an isolated worktree, hydrate it and defer the full-suite baseline to execution setup.

Captured original finding (historical, preserved verbatim):

The anthropic-messages dialect closes top-level fields but checks only `model` against the route's `models`. pi 1.1.0 sends `fallbacks: [{model: ...}]` when a model's compat lists allowedFallbackModels; a route that listed `fallbacks` in `fields` would let the upstream answer with models outside `models`. Today the README warns never to list it. Options: treat `fallbacks[].model` as a model position checked against `models`, or refuse `fallbacks` in route parsing. Also check whether keys on message objects (pi's mid-conversation `{role: system, output_config}` messages) are closed. Found during autonomy-e4c0b5's live run (2026-10-17).

## References

- brief (input, required, kind=brief): docs/notes/2026-10-18-egress-proof-gaps-brief.md — nested-policy research, proposed subset and reviewed-contract gate

## Notes

- 2026-10-19T00:11:45Z (main): scope: briefed; 316c68b confirms fallback models and message-object keys/roles are unchecked; retained the captured live finding and framed fail-closed refusal versus explicit fallback validation; brief: docs/notes/2026-10-18-egress-proof-gaps-brief.md; waits on autonomy-d0387e
- 2026-10-19T00:37:35Z (main): scope: brief revised after review; the gap widens past model selection to tool and source positions in open message and block keys (the example route's inline-tools and mid-conversation-output-config betas), and to values of allowed top-level fields; fallbacks is reachable only through operator misconfiguration; still waits on autonomy-d0387e
- 2026-10-29T02:18:41Z (research/egress-policy): autonomy-d0387e established the nested-policy result in docs/notes/2026-10-18-egress-proof-gaps-brief.md (research e8fdb3a, clarification b76482d); its task holds 67 current/proposed acceptance cases and four offline pi SDK captures. Inline tool_addition is already refused, while extra message/block/control keys pass; no provider escape demonstrated. Recommend explicit finite control schemas, preserving opaque input/schema and system effort; refuse fallbacks at route load including default. Scope a reviewed decision-13 amendment before implementing: restricting operator-listed fields/server tools and optional SDK features narrows the existing contract. Research independently accepted; one minor clarified, none deferred.
- 2026-10-29T09:02:33Z (main): scope: briefed; revalidated unclaimed idea unchanged since 2026-10-29T02:18:41Z. At 141f31a, validator, route, README and decision 13 are unchanged from research baseline 7097495; autonomy-d0387e completed with 67 characterization cases and four offline pi 1.1.0 / SDK 0.129.0 captures (e8fdb3a, clarification b76482d). Extra message/block/control keys pass; inline tool_addition is already refused; provider escape remains unverified. Recommend finite control schemas and route-load fallback refusal over model-only fallback checks, preserving opaque input/schema and pi system effort. Narrowing operator-listed fields/server tools and optional features needs reviewed contract change: created autonomy-a1d778 (P2, m, high, planned) under existing goal autonomy-3a06d3 and recorded the dependency. Original body and unknown origin preserved; origin: filing event unavailable (no creation occurrence/session stamp in show); older-request stage not applicable (no origin_session); no provenance inference from another task. brief: docs/notes/2026-10-18-egress-proof-gaps-brief.md reused unchanged because its existing recommendation, compatibility decisions and acceptance matrix remain current; required references added to idea and design follow-up. No new research, goal, draft spec or implementation.
  provenance: {"harness_session":"codex:01a186e3-3aaf-7182-859e-f668c80750f9","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:13:59Z (design/closed-messages-policy): Taking the next dependency under the user request: autonomy-a1d778 now holds proposed decision-13 amendment b1a325b6b10535de846441acc3c8f9f6375a5f45 at .worktrees/closed-messages-policy/docs/specs/2026-10-12-envelope-design.md. Independent builder check accepted with no findings; human design review remains required. This idea remains unimplemented and depends on that reviewed contract; do not treat the proposal as approved scope.
  provenance: {"harness_session":"codex:01a186e7-b040-7ec0-b7e3-b46b220e04a6","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:16:17Z (design/closed-messages-policy): Human approved decision-13 amendment at autonomy b1a325b6b10535de846441acc3c8f9f6375a5f45:docs/specs/2026-10-12-envelope-design.md. Explicit control schemas, route-load fallback refusal and compatibility exclusions are now approved design; production code unchanged. Scope implementation against this contract and obtain a separate implementation-plan review.
- 2026-10-29T09:19:32Z (main): scope: scoped; human-approved b1a325b finite-subset contract resolves prior design dependency; implementation narrowed to route/dialect enforcement, tests/fixtures and README, with a separate implementation-plan gate. Status todo, priority 2 unchanged, size m, complexity mid, process planned. Current production code still matches the research baseline; approved intent is broader than that implemented behavior. Origin remains unknown: original filing has no creation/session stamp; no origin_session; approval in the present session settles this scope without inventing historical intent. Existing brief and evidence reused unchanged; no repeated research or new goal.
  provenance: {"harness_session":"codex:01a186e7-b040-7ec0-b7e3-b46b220e04a6","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:19:33Z (main): started
  provenance: {"harness_session":"codex:01a186e7-b040-7ec0-b7e3-b46b220e04a6","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:20:13Z (fix/closed-messages): resumed
  provenance: {"harness_session":"codex:01a186e7-b040-7ec0-b7e3-b46b220e04a6","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-29T09:20:40Z (fix/closed-messages): Implementation scoped against human-approved decision 13; planning in .worktrees/closed-messages on fix/closed-messages. just setup completed; planned-work full-suite baseline remains due at execution setup before any production edit. Plan will keep route vocabulary closure and complete body-policy enforcement as two dependent deliverables, reusing existing proxy fixtures and offline captures. Recommend inline execution with a fresh whole-branch reviewer because both deliverables share the same small route/dialect interface.
