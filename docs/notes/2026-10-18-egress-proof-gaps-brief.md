# Egress review follow-ups — brief

**Date:** 2026-10-18, revised the same day after review; nested-policy investigation
added 2026-10-28 (autonomy-d0387e). **Goal:** autonomy-3a06d3,
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

The original review below was checked against main at `316c68b`; egress landed in
merge `d00d744`. The 2026-10-28 investigation below supersedes its nested-policy
hypotheses with evidence from `7097495` and the pinned SDK.

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
    definitions and provider configuration at message level. The investigation
    below establishes that inline definitions use an already-refused block type;
    system-message effort is an admitted, unchecked configuration position.
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

## Nested-policy investigation (autonomy-d0387e, 2026-10-28)

**Result:** use explicit, finite key sets and value checks at known control
positions. Refuse `fallbacks` at route load. Preserve pi's system-message effort
shape and opaque client tool data. Do not add inline tools or a generic schema
walker. This is a recommendation and characterization of existing code, not an
implemented policy or an approved amendment.

### Evidence and reproduction

- Code baseline: main `7097495`; `check_body`, `_blocks`, `_source` in
  `python/src/autonomy/egress/dialect.py` and `_operation` in `egress/route.py`.
  The isolated baseline ran `just test`: **791 passed**. No production code changed.
- Offline schema: pi **1.1.0**, bundled `@anthropic-ai/sdk` **0.129.0**,
  `resources/beta/messages/messages.d.ts`. Relevant symbols are
  `BetaMessageParam`, `BetaSystemMessageOutputConfig`, `BetaOutputConfig`,
  `BetaFallbacksParam`, `BetaFallbackParam`, `BetaRequestToolAdditionBlock`,
  `BetaToolChangeToolDefinitionParam`, the seven supported block types and five
  source types, `BetaTool`, `BetaToolChoice`, `BetaThinkingConfigParam`,
  `BetaThinkingBlockBinding`, `BetaCacheControlEphemeral` and `BetaMetadata`.
  Source hashes, including the stable Messages declarations and pi's serializer,
  are attached as `source-hashes.json`.
- Four **offline transport captures**, with synthetic messages, tools, model
  compatibility switches and a fake credential, exercised pi's actual serializer
  and SDK. `capture-pi.mjs` substitutes fetch, returns a synthetic 400, asserts one
  intercepted request per case, and never calls a network transport. Its global
  fetch also throws. It was run with an environment constructed from `PATH` and an
  empty scratch `HOME`; no real credentials, API calls or desktop use. These are
  not provider acceptance tests or evidence that the selected model supports each
  compatibility switch. `pi-payloads.json` preserves body bytes as parsed JSON and
  the emitted beta header. No header containing the fake credential is recorded.
- The previous live run's outcome is recorded on autonomy-e4c0b5 and the
  fallback/system-message observation on autonomy-58799c. Those records are not a
  raw request capture; this investigation does not promote them into one.
- `test_policy_probe.py`, `route-example.toml` (the README example), and the
  capture files are attached to this task. Run from the main checkout:
  `just test-one ../tasks/files/autonomy-d0387e/test_policy_probe.py -q -s`.
  **67 cases passed**. Each row asserts the **current** verdict and prints a
  separate **proposed** verdict; a passing probe does not mean the hole is fixed.
  The script reads only sibling fixtures and imports the installed autonomy
  package. To regenerate captures, run `capture-pi.mjs` with node and the path to
  the pinned pi-ai `dist/api/anthropic-messages.js` as its argument, in an empty
  environment with only PATH and a disposable HOME. Verify source hashes first.

### What passes and what does not

| Position / case ids in the probe | Observed code verdict | Evidence and implication |
| --- | --- | --- |
| `message-tools`, `message-source`, `message-model`, `message-future_feature`; unknown or absent role | accept | No closure of message keys or roles. The tool/source/model keys here are synthetic probes, not SDK-defined capability positions. |
| `block-tools`, `block-model`, `block-future_feature` on a text block | accept | Extra block keys are unchecked. A direct block `source` is an exception: `_source` checks its type even on text. |
| `system-effort`, `pi-effort` | accept | SDK and pi both define `{role:"system",content:[],output_config:{effort:"high"}}`. An absent `content` currently refuses; the captured empty list passes. |
| `user-output-config`, `system-output-extra`, `top-output-extra`, unknown effort | accept | The position, permitted keys and values of output configuration are unchecked. No provider acceptance of the injected tool key was established. |
| `thinking-extra`, unknown thinking type, `binding-extra`, `choice-extra`, unknown choice type, `metadata-extra`, `scalar-object` | accept | Allowed top-level field names do not constrain their values or nested control objects. |
| `tool-extra`, `tool-server-caller`, `tool-use-caller`, `cache-extra`, `source-extra`, `text-citations` | accept | Tool objects, caller metadata, cache controls, source keys and citation objects add further unchecked positions. A server caller in SDK metadata is not proof of server execution. |
| `inline-client-tool`, `inline-server-tool`, `pi-inline` | `body-refused` | SDK inline definitions are `tool_addition.tool.definition`; the block type is absent from the route's list. Adding it to a route gives `route-invalid` because it is outside `KNOWN_BLOCK_TYPES`. The beta header alone does not open this path. |
| `fallback-array`, `fallback-default`, `pi-fallback` | `body-refused` | The README route omits `fallbacks`. Its beta token list also omits the fallback beta, an independent request-layer barrier not exercised by the body probe. |
| `fallback-array-listed`, `fallback-default-listed` | accept | A route listing `fallbacks` admits an out-of-route model or the SDK's server-selected `"default"`. A full request also needs any provider-required beta allowed by the route; this probe proves body acceptance only. |
| `unknown-field-listed`, `server-tool-listed` | accept | Route parsing accepts arbitrary field names and tool types. Enumerating body keys alone cannot close the dialect if an operator can list a field with undefined nested semantics. |
| `outside-model`, `top-mcp`, `top-server-tool`, URL image and nested result URL | refuse | Existing model, field, tool-type and source checks still work at the positions they cover. |
| `document-*`, `nested-document-url-denied` | accept authorized sources; refuse unlisted URL | A deliberately expanded route already supports document sources, including recursive content. Extra source/citation keys still pass. |
| `client-input-opaque`, `client-schema-opaque` | accept | Deliberately retained: model/tool/source-looking keys inside client data are not provider control positions. |

The SDK gives a narrower conclusion than the original suspicion: no bypass via
message-level inline tools was demonstrated. It does show real configuration
positions inside allowed objects, and the synthetic cases prove that unknown
positions reach the next layer without local refusal. Whether the provider rejects,
ignores or interprets those synthetic keys is **unverified**. Do not call this an
observed network escape.

### Smallest recommended policy

One hand-written check per known control shape is sufficient; dispatch on the
declared type and reject extra keys before visiting its defined children. Keep
JSON parsing and unchanged request bytes as they are. Refuse unknown discriminants
even if a route lists them. The following is the proposed supported subset, not
the entirety of the SDK or a claim that every SDK field is safe.

1. **Route-load boundary.** Restrict `fields` to the README set (`model`,
   `messages`, `system`, `max_tokens`, `stream`, `tools`, `tool_choice`, `thinking`,
   `temperature`, `metadata`, `stop_sequences`, `top_p`, `top_k`, `output_config`).
   Refuse `fallbacks`, unknown fields, and tool types without an explicit shape.
   For the minimum slice, support client tools only: absent `type`, or `custom`
   only when the route explicitly lists it. Keep the seven existing block types
   and five source types; their configured allow-lists still narrow availability.
   Do not add route keys, arbitrary nested paths or a schema dependency.
2. **Messages.** Require `role` in `user|assistant|system` and `content` as a
   string or list of checked blocks. Allow only `role`, `content`, plus
   `output_config` on `system`. Reuse the effort-only configuration below there;
   require `output_config` in the operation's `fields` for this nested occurrence
   too, so leaving it out is meaningful at both positions. Preserve the captured
   empty content list. Refuse `clear_at` in the minimum slice: the SDK defines it,
   but the inspected pi serializer does not emit it. No new message tool/source
   position is admitted.
3. **Blocks and sources.** Apply this table at every existing recursive entry
   (`system`, message content, tool-result content, document content source).
   All listed keys are an upper bound, not all required. Require the SDK's required
   fields and primitive types; optional fields follow its declared nullability.
   Do not treat a control object's unrecognized keys as opaque data.

   | Block | Allowed keys in the minimum slice |
   | --- | --- |
   | text | `type`, `text`, `cache_control` |
   | image | `type`, `source`, `cache_control` |
   | document | `type`, `source`, `cache_control`, `citations`, `context`, `title` |
   | tool_use | `type`, `id`, `name`, `input`, `cache_control` |
   | tool_result | `type`, `tool_use_id`, `content`, `is_error`, `cache_control` |
   | thinking | `type`, `thinking`, `signature` |
   | redacted_thinking | `type`, `data` |

   Source key sets: base64 `{type,media_type,data}`; text
   `{type,media_type,data}`; content `{type,content}`; URL `{type,url}`;
   file `{type,file_id}`. Continue to enforce `source_types` and recursive block
   checks; constrain each block/source pairing and scalar leaves using the pinned
   declarations. URL/file sources remain deliberate operator opt-ins, not newly
   enabled defaults. Document citations accept only `{enabled: boolean}`.
   Cache controls accept only `{type:"ephemeral",ttl?:"5m"|"1h"}` with pinned
   nullability at each parent. Text citations, image transformations, toolset and
   caller metadata are refused pending a defined supported shape.
4. **Client tools.** Allow `name`, `description`, `input_schema`, optional
   route-authorized `type:"custom"`, `cache_control`, `eager_input_streaming`,
   `strict`, and `defer_loading`. Check strings/booleans and cache shape. Preserve
   pi's deferred placeholder. Refuse `allowed_callers`, `input_examples` and
   unrecognized keys in this slice. Keep `input_schema` and `tool_use.input`
   opaque JSON, including keys named `model`, `tools`, `source`, and remote-looking
   schema references. No recursive blacklist through those data regions.
5. **Top-level values.** `output_config` allows only `effort` with SDK values
   `low|medium|high|xhigh|max` (and SDK-declared null). `thinking` is a closed
   discriminated object: disabled/between_tools allow only `type`; enabled adds
   required integer `budget_tokens`, optional `display` and `block_binding`;
   adaptive allows `type`, `display`, `block_binding`. Display is
   `summarized|omitted|updates`; binding allows only `prefix_mismatch_behavior`
   (`error|drop_block`, with declared nullability). Tool choice is
   `auto|any|tool|none`, only the defined `name` and boolean
   `disable_parallel_tool_use` fields for the appropriate variant. Metadata allows
   only string-or-null `user_id`. Numeric/boolean/list top-level fields must have
   their declared primitive shapes; do not let an object hide in `temperature` or
   a list element hide in `stop_sequences`. Resource limits, accounting and
   full provider semantic validation remain separate work.

**Fallback decision:** refuse at route load, rather than validate fallback models.
Checking only `fallbacks[].model` misses `"default"` and per-attempt overrides of
`thinking`, `output_config`, `max_tokens` and `speed`. Supporting it would require
an explicit closed entry schema, rejection of server-selected defaults and an
accounting decision. It is unnecessary for the admitted plain/effort pi cases.
Users with fallback compatibility configured will continue to receive a refusal;
the envelope must not strip the field or silently choose another model.

### Contract, acceptance and remaining limits

- **Reviewed amendment required before implementation.** Decision 13 currently
  permits operator-listed server tool types, `mcp_servers` and `container`, and
  lists only top-level model/field positions. The route restriction above narrows
  that capability; the nested `output_config` gate and finite message/block shapes
  also need to be recorded. autonomy-58799c should scope a written amendment and
  implementation, not silently interpret this research as approval. If those
  broader features must remain available now, their explicit schemas and tests
  become additional scope rather than exceptions to key closure.
- Other intentional narrowing to review: `clear_at`, output format and task
  budget, text citations, image transformations, caller/toolset metadata and
  tool examples. SDK presence does not imply support by this dialect. Structured
  output schemas are refused at their parent in the minimum slice, so they do not
  introduce another opaque region. Inline tool additions/removals remain refused;
  supporting them would require a reviewed dialect extension with the same tool
  checks on every definition. A header token cannot substitute for that work.
- The acceptance matrix is the probe's named cases and proposed verdicts. Retain
  `pi-plain`, `pi-effort`, the two opaque-data cases and authorized document
  sources. Flip the extra-key, role, value and route cases as printed. Extend the
  implementation tests with one extra-key negative at **each** admitted control
  object, nullable/required-field/type negatives, every source/block pairing,
  nested `output_config` with the top-level permission omitted, recursion through
  every defined content path, and proof of unchanged forwarded bytes. The 67
  characterization cases establish the gap; they are not exhaustive fix tests.
- No production validator, route schema or approved spec changed here. No
  provider behavior was probed. Future provider versions or header semantics,
  semantic prompt-mediated effects, general server-tool/MCP/container support,
  response validation, budget enforcement and other provider dialects remain
  outside this investigation. Hostile text and client JSON can contain URLs;
  this policy concerns provider control positions, not the meaning of that data.

This result wakes autonomy-58799c with concrete evidence and proposed acceptance
cases. Response completion and namespace proof retain their separate tasks.
