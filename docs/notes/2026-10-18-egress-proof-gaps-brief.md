# Egress review follow-ups — brief

**Date:** 2026-10-18, revised the same day after review. **Goal:** autonomy-3a06d3,
under autonomy-d9adef. **Ideas and tasks:** autonomy-58799c and autonomy-d0387e
(positions below the top level), autonomy-c9508e and autonomy-9570b0 (response
completion), autonomy-c282c5 (namespace proof).

## Problem

Close three proof gaps found in autonomy-e4c0b5's implementation review and live
run: tool, source, model and provider-feature positions below the body's top level
that the dialect does not check; a response cut that looks complete over HTTP; and a
network proof that depends on host routing and covers the probe rather than the
actor. This is follow-through on the existing envelope, within autonomy-d9adef.

## Current behaviour and evidence

Checked against main at `316c68b`; egress landed in merge `d00d744`. No code has
changed since.

- autonomy-58799c: `python/src/autonomy/egress/dialect.py::check_body` closes the
  top-level fields, checks only top-level `model` against `models`, and checks
  `tool_types` only on elements of top-level `tools`.
  - Message objects are checked for content blocks only. Their other keys and their
    roles are not closed.
  - `_blocks` checks a block's `type`, its `source`, and a `tool_result`'s content.
    A block's other keys are not closed.
  - The values of allowed top-level fields other than `tools`, `system` and
    `messages` (`output_config`, `thinking`, `tool_choice`, `metadata`) are not
    checked.
  - Listing `fallbacks` in a route's `fields` admits it without checking its model
    positions. The README warns against this. Without that listing, a body carrying
    `fallbacks` is already refused (`body-refused`), so refusing it at route load
    hardens operator configuration rather than closing a reachable gap.
  - The README's example route admits the `inline-tools-2026-09-15` and
    `mid-conversation-output-config-2026-07-01` betas. Their names suggest tool
    definitions and provider configuration at message level, which `tool_types`
    and `fields` would not see. Their schema is not verified here. If either places
    a server tool there, the open message or block keys would admit it, which
    decision 13 forbids.
  - The captured live finding reports pi 1.1.0 fallback and mid-conversation system
    message shapes. pi 1.1.0's pinned install bundles `@anthropic-ai/sdk` 0.129.0,
    whose type definitions are an offline source for the request schema:
    `resources/beta/messages/messages.d.ts` names `fallbacks` and `output_config`,
    and `resources/messages/messages.d.ts` names `output_config`.
- autonomy-c9508e: `egress/upstream.py::response_head` removes upstream framing
  and sends a close-delimited response. The badchunk test checks status and the
  error record, not HTTP client completion detection. Two paths send a FIN on the
  actor socket:
  - `egress/server.py::_release` calls `cut` (`SHUT_RDWR`) before `close`, on
    successful and failed responses alike;
  - on a route stop, `close()` shuts each actor socket for reading, joins the
    workers, then shuts survivors with `SHUT_RDWR` from its own thread.

  A client reading a close-delimited body sees the FIN as a clean end, before any
  later RST. An abortive close therefore has to replace both paths' FIN and win a
  cross-thread race against the stop path. Linux also discards a socket's unread
  received data when an RST arrives.
- autonomy-c282c5: `sandbox/bwrap.py::probe` tests connect outcomes, while its
  real shared-network negative skips without an IPv4 default route. The fixed
  builder still uses `--unshare-all`; this is a runtime-proof gap, not an observed
  escape. The probe is a separate `bwrap` run from the actor's `launch`, so a check
  inside the probe proves the probe's namespace, and the actor's rests on the shared
  argv builder.
  - `launch` already holds the namespace init's pid (from `--info-fd`) and a pidfd
    on it before the release, where `before_release` runs. On this host the parent
    could `stat` `/proc/<child-pid>/ns/net` there and saw a device and inode
    different from its own. bwrap's `--info-fd` report also carries
    `net-namespace`.

The final review and deferred findings are preserved in
`tasks/files/autonomy-e4c0b5/sdd-ledger.md`. The existing authority brief and open
research contain no investigation of the two open egress questions: positions below
the top level, and response completion.

## Constraints

Envelope design decision 13 fixes a closed dialect, unchanged request bytes,
streaming with bounded buffering, per-run close, and one final request record. The
proxy already streams the response "in framing of its own". Retain those properties
and keep client tool input/schema as opaque data. Do not extend the route schema
merely to accommodate an unchecked provider feature. Keep readable pre-response
403/502 errors and successful response completion. Do not use a paid API or live
desktop for this research.

## Alternatives

- **Positions below the top level:** reject `fallbacks` at route load, or support
  and validate every fallback model. Lean toward refusal: it enforces the README's
  existing restriction with the least policy expansion. For message and block keys,
  close each to an allow-list taken from captured pi traffic and the bundled SDK
  types, so the policy fails closed whatever the provider's full schema is. A
  message-level position that carries tools or sources needs the same `tool_types`,
  `block_types` and `source_types` checks as its top-level counterpart, or refusal.
- **Response completion:** use proxy-owned chunked framing with a terminator only
  on completion, or abort an incomplete response with `SO_LINGER {1,0}`. Lean toward
  framing: its result depends only on what the proxy writes, and it needs no
  contract change. An abortive close must remove the FIN from `_release` and from
  `close()`'s survivor cut, and win the stop path's race. Application-specific
  terminal events alone do not settle the generic HTTP question. Neither approach
  can prove semantic completeness of an upstream body whose own framing supplies no
  such evidence.
- **Namespace proof:** compare the orchestrator's network namespace identity
  (device and inode) with the actor namespace's own, inside `launch` after the
  pidfd is held and before the release, and confirm afterwards that the pidfd is
  still live so a reused pid cannot answer. This proves the namespace the actor
  runs in, needs no routing, and needs no change to the probe's trusted script.
  Retain the probe's connect checks. autonomy-c282c5 now has direct acceptance
  criteria.

## Unanswered questions

- Which positions below the body's top level can carry tools, sources, models or
  provider features outside current checks: message keys and roles, block keys, the
  values of allowed top-level fields, and `fallbacks`? Which minimal fail-closed
  policy covers them, and which positions are explicitly out of scope? A bounded
  dialect trace, the bundled SDK types and synthetic tests can answer this, without
  a live call.
- Does proxy-owned chunked framing make every detectable cut an HTTP client error,
  and can an abortive close match it once both FIN paths change? A real loopback
  experiment with an HTTP client and a raw reader can answer this; route stop
  mid-body is its first case. Distinguish detectable cuts from unframed upstream
  EOF.

## Proposed decomposition

Goal autonomy-3a06d3 groups this work under autonomy-d9adef. The two research
results must update this brief and wake their named ideas before merge; neither
needs a separate design task before its evidence is available.

- autonomy-d0387e: establish the minimal closed policy for positions below the top
  level; autonomy-58799c waits on it. Priority 2, size s, mid complexity, direct
  process.
- autonomy-9570b0: establish reliable HTTP cut detection;
  autonomy-c9508e waits on it. Priority 2, size s, mid complexity, direct process.
- autonomy-c282c5: launch-time namespace identity proof, priority 3, size s, low
  complexity.
