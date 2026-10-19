# Egress review follow-ups — brief

## Problem

Close three proof gaps found in autonomy-e4c0b5's implementation review and live
run: model selection outside the checked top-level field, a response cut that
looks complete over HTTP, and a network probe that depends on host routing.
This is follow-through on the existing envelope, within autonomy-d9adef.

## Current behaviour and evidence

Checked against main at `316c68b`; egress landed in merge `d00d744`.

- autonomy-58799c: `python/src/autonomy/egress/dialect.py::check_body` checks
  only top-level `model`. Listing `fallbacks` in a route's `fields` admits it
  without checking its model positions. The README warns against this. Message
  objects are checked for content blocks, but their keys and roles are not closed.
  The captured live finding reports pi 1.1.0 fallback and mid-conversation system
  message shapes; their complete supported schema is not established here.
- autonomy-c9508e: `egress/upstream.py::response_head` removes upstream framing
  and sends a close-delimited response. `egress/server.py::_release` shuts down
  and closes actor sockets on both successful and failed responses. The badchunk
  test checks status and the error record, not HTTP client completion detection.
- autonomy-c282c5: `sandbox/bwrap.py::probe` tests connect outcomes, while its
  real shared-network negative skips without an IPv4 default route. The fixed
  builder still uses `--unshare-all`; this is a runtime-proof gap, not an observed
  escape. The final review proposes comparing namespace identities.

The final review and deferred findings are preserved in
`tasks/files/autonomy-e4c0b5/sdd-ledger.md`. The existing authority brief and open
research contain no investigation of these two unresolved egress questions.

## Constraints

Envelope design decision 13 fixes a closed dialect, unchanged request bytes,
streaming with bounded buffering, per-run close, and one final request record.
Retain those properties and keep client tool input/schema as opaque data. Do not
extend the route schema merely to accommodate an unchecked provider feature.
Keep readable pre-response 403/502 errors and successful response completion.
Do not use a paid API or live desktop for this research. No shared need is
declared in the task configuration.

## Alternatives

- **Model positions:** reject unsupported `fallbacks` at route load, or explicitly
  support and validate every fallback model. Lean toward refusal: it enforces the
  README's existing restriction with the least policy expansion. First establish
  whether unchecked message fields create the same class of bypass.
- **Response completion:** abort an incomplete response with `SO_LINGER {1,0}`,
  or use proxy-owned chunked framing with a terminator only on completion. Lean
  toward abortive close if loopback tests prove it survives the current shutdown
  paths; otherwise prefer framing. Application-specific terminal events alone do
  not settle the generic HTTP question. Neither approach can prove semantic
  completeness of an upstream body whose own framing supplies no such evidence.
- **Namespace proof:** compare trusted parent and probe namespace identities,
  retaining connect checks. Prefer this to routing-dependent negative tests;
  autonomy-c282c5 now has direct acceptance criteria.

## Unanswered questions

- Which supported fallback/message positions can select models or provider
  features outside current checks, and which minimal refusal policy covers them?
  A bounded dialect trace and synthetic tests can answer this.
- Can the existing shutdown order produce a reliable client error after a cut
  response head, including stop and upstream framing failures? A real loopback
  experiment with an HTTP client and a raw reader can answer this. Distinguish
  detectable cuts from unframed upstream EOF.

## Proposed decomposition

Goal autonomy-3a06d3 groups this work under autonomy-d9adef. The two research
results must update this brief and wake their named ideas before merge; neither
needs a separate design task before its evidence is available.

- autonomy-d0387e: establish the minimal closed fallback/message policy;
  autonomy-58799c waits on it. Priority 2, size s, mid complexity, direct process.
- autonomy-9570b0: establish reliable HTTP cut detection;
  autonomy-c9508e waits on it. Priority 2, size s, mid complexity, direct process.
- autonomy-c282c5: direct namespace identity proof, priority 3, size s, low complexity.
