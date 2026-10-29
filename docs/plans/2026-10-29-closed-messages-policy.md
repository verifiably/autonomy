# Closed Messages Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Inline execution is the author's recommendation, subject to the user's plan review; use subagent-driven-development if the user chooses it instead.

**Goal:** Implement autonomy-58799c: refuse undefined route capabilities and validate every supported Anthropic Messages control shape before forwarding.

**Architecture:** Keep the existing `Operation` contract and strict JSON parser. The route defines a finite vocabulary; small explicit checks in `dialect.py` validate its supported control objects and recurse only through declared content positions. The server continues forwarding the original body bytes after validation.

**Tech Stack:** Python >=3.11, standard library, pytest through the existing just/tt front door. No new dependency.

**Spec:** [Envelope design](../specs/2026-10-12-envelope-design.md), decision 13, especially *Closed anthropic-messages body*, human-approved frozen revision `b1a325b6b10535de846441acc3c8f9f6375a5f45`; approval status recorded in `a5d3c2b`. Historical evidence and proposed-versus-current matrix: [egress brief](../notes/2026-10-18-egress-proof-gaps-brief.md), research autonomy-d0387e. The spec controls any difference from the historical probes.

**State:** Revised after plan review round 2 (Important 2, Minor 4); new revision awaiting human review. No implementation code changed. All six findings are addressed below; the previous self-review missed the deferred-placeholder and large-integer positives.

## Global Constraints

- "The dialect first defines its supported control shapes; the route can narrow them, never add a shape."
- "There is no coercion, default insertion, field removal, rewriting or silent fallback."
- "Numbers must be finite; integer fields admit integer JSON tokens, not floats or numeric strings."
- "Null is allowed only where explicitly stated."
- "Arrays may be empty, including the captured system message's `content: []`."
- "A feature header token alone grants no body capability."
- "The latter's value, like `tool_use.input`, is opaque JSON: no key inspection, recursive blacklist or JSON Schema validation, including of remote-looking `$ref` values."
- "Malformed JSON remains `request-malformed`; missing or refused model remains `model-refused`; other request-shape refusals use `body-refused` and the existing readable HTTP 403."
- "Preserve existing ordering of model checking before other body checks."
- Request bytes, credential custody, source opt-ins and recursive route permissions remain as specified. No kernel imports, schema dependency, route-schema changes, provider dialect, budget/accounting, response-completion or namespace work.
- No live API or desktop use. Every test subprocess newly added or changed must get an environment built key by key with temporary HOME and fake credentials; this plan needs no new subprocess.

## Review Focus

Each risk below has an explicit test in Task 2, rather than being left to reviewer inference.

1. A JSON boolean may satisfy Python's integer test, and float conversion of a finite 400-digit integer raises OverflowError. Refuse `true`, `1.0` and numeric strings in integer positions and `1e999` in numeric controls; accept 400-digit integer tokens at `temperature` and `top_p`, including HTTP 200 through the fake upstream (`test_numeric_controls_do_not_coerce`, `test_large_numeric_tokens_reach_upstream`).
2. Broad route lists can accidentally widen nested permissions; context/source pairings and nested effort permission must intersect the route at every entry (`test_nested_permissions_and_contexts`).
3. A recursive blacklist can reject legitimate tool data; opaque values, including scalar/null and remote-looking references, must pass unchanged (`test_opaque_client_data_is_not_control`).
4. Adding required fields can make an older mutation test exercise the wrong refusal; the duplicate-model mutation must remain otherwise valid and still forward under the deliberately lenient parser (`test_a_lenient_parser_would_forward_a_duplicate_model`).
5. Re-serialization or late validation can change valid bytes or contact an upstream for invalid input; preserve whitespace/escapes and record zero connections for refused shapes (`test_policy_checks_preserve_raw_bytes`, `test_nested_policy_refusals_never_connect`).

## Workspace and setup

The task worktree is `.worktrees/closed-messages`, branch `fix/closed-messages`.
Commands below run from that worktree; test paths are relative to `python/` because
`just test-one` changes there. `just setup` already completed. The author has not
run the planned-work baseline yet; it belongs to execution setup.

- [ ] After human plan approval, resume with `tasks start autonomy-58799c` in the task worktree and run `~/.agents/bin/trial-arm autonomy-58799c`, honoring its output.
- [ ] After the new frozen plan is approved and its review is closed, re-enter using-git-worktrees for this existing isolated worktree and confirm clean tracked files. Merge current local main with `git merge main -m "chore: merge main before policy baseline"`; never amend/rebase a reviewed revision. Resolve conflicts by preserving both changes before proceeding. In particular, retain ecd5858's response-completion tests and fixture additions. Do not merge main while the plan review is open.
- [ ] Run `just setup` on the merged base, then `just test` **before the first code change**; record the baseline commit, command, count, exit status and warnings on the task. This baseline must include the current main tests, not the branch's earlier base. A run selecting no tests is not a baseline. Do not turn a baseline failure into an unrelated fix.
- [ ] Read the approved spec, this plan and task evidence. Recheck all `parse_body`/`check_body` callers and the route vocabulary before editing. No public signature or `Operation` field changes are planned.

## File map

| File | Responsibility / change |
| --- | --- |
| `python/src/autonomy/egress/route.py` | Define `KNOWN_FIELDS` and `KNOWN_TOOL_TYPES`; reject undefined configuration in `_operation` |
| `python/src/autonomy/egress/dialect.py` | Enforce the approved control shapes in existing request-body validation |
| `python/tests/test_egress_route.py` | Route vocabulary, narrowing and unused-operation refusal tests |
| `python/tests/test_egress_dialect.py` | Strict parser plus complete supported-subset acceptance/refusal matrix |
| `python/tests/egress_fixtures.py` | Add `output_config` to `PI_FIELDS`; keep fake TLS server and request helpers |
| `python/tests/fixtures/pi-messages.json` (new) | Exact four offline synthetic captures promoted to a durable test fixture |
| `python/tests/test_egress_server.py` | Integration refusal-before-connect and unchanged-byte evidence; preserve parser mutation intent |
| `README.md` | Explain enforced finite subset, fallback route refusal and intentional compatibility exclusions |
| `docs/specs/2026-10-12-envelope-design.md` | Mark the approved amendment implemented only after acceptance and review pass |

`server.py`, `request.py`, `upstream.py`, exports, CLI and live scripts retain their
interfaces. A check-order regression found there would be fixed within Task 2;
there is no planned transport rewrite. Historical probes/captures and review
attachments under `tasks/files/` stay unchanged.

## Task 1: Close the route vocabulary

**Files:** `route.py`, `test_egress_route.py`, `egress_fixtures.py` from the map.

**Interfaces:**

- Consumes: existing `parse_route(data: bytes) -> Route`, `_operation(value: object, where: str) -> Operation`, `pi_route(...)`, `to_toml(doc: dict) -> str` and the test module's `parse(doc)` helper.
- Produces: unchanged `Operation`/`Route`; `KNOWN_FIELDS: frozenset[str]` and `KNOWN_TOOL_TYPES: frozenset[str]` beside the existing known block/source constants. `KNOWN_TOOL_TYPES` is exactly `{"custom"}`. `KNOWN_FIELDS` is exactly the fourteen field names in the spec's top-level table. No runtime dependency on the SDK or on a documentation file.

- [ ] **Step 1: Add route tests that fail on today's arbitrary fields and tool types.** Parameterize `test_undefined_fields_are_refused` over fields `fallbacks`, `mcp_servers`, `container`, `future_feature`, and `test_undefined_tool_types_are_refused` over tool types `web_fetch_20250910`, `future_tool`; append each to an otherwise valid route and assert `RouteRefused.code == "route-invalid"`. Add `test_undefined_capability_in_unused_operation_is_refused` with a second unused operation (different exact path), proving load-time refusal does not wait for request selection.

```python
@pytest.mark.parametrize("field", ["fallbacks", "mcp_servers", "container", "future_feature"])
def test_undefined_fields_are_refused(field, credential):
    doc = pi_route(credential=credential)
    doc["operations"][0]["fields"].append(field)
    with pytest.raises(RouteRefused) as caught:
        parse(doc)
    assert caught.value.code == "route-invalid"
```

Add `test_defined_route_capabilities_can_be_narrowed`: the README field set
and `tool_types=["custom"]` parse; omitted/empty tool types parse; `fields=["model"]`
parses even though it cannot admit a complete body. Keep all existing unknown,
duplicate, nonempty-list and mandatory-model tests.

- [ ] **Step 2: Run RED.** `just test-one tests/test_egress_route.py -k 'undefined or defined_route' -v`. Expected: new undefined-field/tool tests FAIL because current parsing accepts them; no import/config failure.
- [ ] **Step 3: Implement the vocabulary checks.** In `_operation`, refuse `fields - KNOWN_FIELDS` and `tool_types - KNOWN_TOOL_TYPES` using existing `_strings` and `_invalid`; validate the tool list once and use that parsed value to construct `Operation`. Keep current route-list semantics and all other checks. Add `output_config` to `PI_FIELDS` to match the already-documented pi route and support subsequent effort tests; do not widen blocks, sources or feature headers.
- [ ] **Step 4: Run GREEN and the precommit check.** `just test-one tests/test_egress_route.py -v`, then `just test-fast` and `just check`; expect zero failures and a nonzero test count from the focused run. Record counts and warnings; preserve failures for diagnosis rather than widening scope.
- [ ] **Step 5: Commit.** Stage only the three named files; commit `fix(egress): reject undefined route capabilities`.

## Task 2: Enforce control shapes and prove compatibility

**Files:** `dialect.py`, `test_egress_dialect.py`, `test_egress_server.py`, new
`python/tests/fixtures/pi-messages.json` and `README.md`. The spec's implemented
marker belongs to final integration, after whole-branch review, not this task commit.

**Interfaces:**

- Consumes Task 1's unchanged `Operation`, finite vocabularies, `PI_FIELDS` and existing `MODEL`, `message(**extra) -> dict`, `serve`/`served`, `raw_request`, `exchange`, `status_and_body` fixtures.
- Produces unchanged `parse_body(data: bytes) -> dict` and `check_body(body: dict, op: Operation) -> None`, raising existing `Refused` codes. `_blocks`/`_source` remain internal; adjust their private signatures for parent context as needed. No later task consumes a new helper interface.

- [ ] **Step 1: Add the table-driven body regressions.** Keep the existing parser tests; extend the same module with a parameter matrix of independently valid minimal objects, then mutate exactly one control position per case. Tests use `check_body(parse_body(json.dumps(payload).encode()), op)` for accepts; refusals assert `Refused.code`, rather than merely catching any exception. Every test has a stable pytest id naming its position and mutation.

Use these test groups; each includes positive controls so a refusal-only
implementation cannot pass. Build explicit finite test cases from the approved
spec tables; never derive expected keys from production validator constants.

| Test group | Cases and exact assertions |
| --- | --- |
| `test_control_object_key_sets` | One extra-key negative for root, user/assistant/system message, each of seven blocks, every source including image/PDF base64 variants, tool, cache, citations, effort, metadata, each thinking and choice variant, and binding; otherwise-minimal counterparts return None |
| `test_required_fields_and_nullable_leaves` | Remove every required key and alter every leaf's primitive type; optional absence accepts, explicit null accepts only where the spec names it. Empty arrays and effort/binding/citations/metadata objects accept. Explicit tool type null refuses; tool-result absent content accepts but null refuses |
| `test_nested_permissions_and_contexts` | An explicit `type: "custom"` client tool accepts with `tool_types=["custom"]` and gets `body-refused` when that permission is absent; keep the existing negative. Every message role; system effort with field permission accepts, without permission refuses including null, user/assistant effort refuses; top-level system only text, tool-result only text/image/document, document content only text/image. Test every defined block/source pairing (including media types), route-narrowed blocks/sources, and tool-result → document → content-source → image recursion with extra-key and unlisted URL/file descendants |
| `test_numeric_controls_do_not_coerce` | Integer `max_tokens`, `top_k`, enabled `budget_tokens` accept; True, 1.0 and "1" refuse there. `temperature`/`top_p` accept finite int/float, including an unquoted 400-digit integer token at each field after `parse_body`; assert `check_body` returns None without overflow. Reject boolean/object/string. A raw valid body with `temperature: 1e999` parses but gets `body-refused`; NaN/Infinity tokens still get `request-malformed` |
| `test_control_variants` | Every approved effort, display, mismatch and ttl value; thinking disabled/between_tools reject extra fields, adaptive rejects budget, enabled requires budget; choices auto/any/tool/none permit exactly their fields. Unknown values/discriminants refuse. Arbitrary tool-choice name remains accepted for provider validation |
| `test_opaque_client_data_is_not_control` | Tool input/schema objects containing model/tools/source keys and remote-looking `$ref`, plus scalar, array and null values, accept with required keys present; unknown sibling control keys still refuse. Strict JSON duplicate-key and lone-surrogate checks still apply inside the opaque values |
| `test_refusal_code_precedence` | Missing/unlisted/wrong-type model wins over other body defects (`model-refused`); valid model plus missing messages/max_tokens is `body-refused`; malformed JSON remains `request-malformed` |

Representative test syntax (extend cases as required by the matrix, without
adding a schema-walker test framework):

```python
@pytest.mark.parametrize("value", [True, 1.0, "1", None, {}])
def test_max_tokens_is_an_integer(value):
    with pytest.raises(Refused) as caught:
        check_body(body(max_tokens=value), OP)
    assert caught.value.code == "body-refused"


def test_system_effort_needs_route_permission():
    from dataclasses import replace
    payload = body(messages=[{"role": "system", "content": [],
                              "output_config": {"effort": "high"}}])
    check_body(payload, OP)
    with pytest.raises(Refused) as caught:
        check_body(payload, replace(OP, fields=OP.fields - {"output_config"}))
    assert caught.value.code == "body-refused"


@pytest.mark.parametrize("field", ["temperature", "top_p"])
def test_numeric_controls_do_not_coerce_large_integers(field):
    raw = json.dumps(body(**{field: int("9" * 400)})).encode()
    parsed = parse_body(raw)
    assert type(parsed[field]) is int and parsed[field] == int("9" * 400)
    assert check_body(parsed, OP) is None


def test_custom_client_tool_needs_route_permission():
    from dataclasses import replace
    payload = body(tools=[{"type": "custom", "name": "local", "input_schema": {}}])
    authorized = replace(OP, tool_types=frozenset({"custom"}))
    assert check_body(payload, authorized) is None
    with pytest.raises(Refused) as caught:
        check_body(payload, replace(authorized, tool_types=frozenset()))
    assert caught.value.code == "body-refused"
```

- [ ] **Step 2: Add offline pi and real proxy boundary cases.** Copy the exact attachment `tasks/files/autonomy-d0387e/pi-payloads.json` into the new test fixture (SHA-256 `959e31f7b1238077361c3962b4b1851e86d51a3933634e9ddc1971cad653f1f3`). Record its pinned pi 1.1.0 / SDK 0.129.0 provenance in the test; no new capture or network transport. `test_pinned_pi_payloads` loads it relative to the test file, and asserts plain/effort accept and inline/fallback get `body-refused` under the supported body route. Read body entries only; do not mistake beta-header presence for a grant.

Also add `test_pinned_pi_deferred_placeholder`: extract the exact
`__pi_deferred_placeholder__` tool from the inline capture's top-level tools array,
put it in an otherwise plain body, and assert acceptance. Refusing the complete
inline capture does not exercise this positive path. Do not rebuild or simplify
the captured tool, strip `defer_loading`, or reuse its inline message blocks.

```python
def test_pinned_pi_deferred_placeholder():
    from pathlib import Path
    captures = json.loads((Path(__file__).parent / "fixtures" / "pi-messages.json").read_text())
    inline = next(c for c in captures if c["id"] == "inline")
    placeholder = next(t for t in inline["body"]["tools"]
                       if t["name"] == "__pi_deferred_placeholder__")
    assert placeholder["defer_loading"] is True
    raw = json.dumps(body(tools=[placeholder])).encode()
    assert check_body(parse_body(raw), OP) is None
```

In `test_egress_server.py`, add:

```python
@pytest.mark.parametrize("extra", [
    {"messages": [{"role": "user", "content": "hi", "model": "outside-route"}]},
    {"thinking": {"type": "adaptive", "tools": []}},
    {"tools": [{"name": "local", "input_schema": {}, "allowed_callers": ["direct"]}]},
])
def test_nested_policy_refusals_never_connect(served, extra):
    status, answer = status_and_body(exchange(served.port, raw_request(body=message(**extra))))
    assert status == 403
    assert json.loads(answer)["error"]["code"] == "body-refused"
    assert served.upstream.connections == 0 and served.upstream.seen == []
    assert served.records()[0]["refused"] == "body-refused"


def test_policy_checks_preserve_raw_bytes(served):
    raw = (b'{ "model" : "claude-haiku-5-5", "max_tokens":16, '
           b'"messages":[{"role":"user","content":"caf\\u00e9"}] }\n')
    assert status_and_body(exchange(served.port, raw_request(body=raw)))[0] == 200
    assert served.upstream.seen[0].body == raw


@pytest.mark.parametrize("field", ["temperature", "top_p"])
def test_large_numeric_tokens_reach_upstream(served, field):
    raw = json.dumps(message(**{field: int("9" * 400)})).encode()
    assert status_and_body(exchange(served.port, raw_request(body=raw)))[0] == 200
    assert served.upstream.seen[0].body == raw
    record = served.records()[0]
    assert record["status"] == 200 and record["ended"] == "complete"
    assert record["forwarded"] is True and record["refused"] is None
```

The large-integer unit and HTTP cases require acceptance, not merely the absence
of a 502: provider ranges are intentionally not validated by this dialect, and
the fake upstream answers 200. This makes the overflow-to-502 regression visible.

Extend the raw-byte positive with a valid nested tool/schema payload to prove the
new walk never rewrites opaque data either. Keep `serve` cleanup and bounded
socket waits. The existing byte-preservation behavior may already pass; do not
introduce a transport change just to force this preservation test RED.

Update the duplicate-model mutation request in
`test_a_lenient_parser_would_forward_a_duplicate_model` with `"max_tokens":16`
so it remains otherwise-valid after required-field validation. Its deliberately
lenient parser must still permit the last model and yield one upstream request.
Keep the original strict-parser negative and its `request-malformed` result.

- [ ] **Step 3: Run RED before changing production validation.** `just test-one tests/test_egress_dialect.py tests/test_egress_server.py -v`. Expect new extra-key/type/required/null/permission cases to fail because current checks accept them. Record representative failures at the nested trust boundaries. Existing preservation and still-refused cases can already pass. If a test fails only because of a broken fixture, repair the fixture and rerun RED.
- [ ] **Step 4: Implement explicit control validation in `dialect.py`.** Keep strict parsing, model-first precedence and the RecursionError-to-body-refused guard. Validate root required fields and scalar values, messages, client tools and all discriminated controls against the approved tables. Check key closure before visiting defined child controls; recurse only through permitted content/source contexts. Use `type(value) is int` or equivalent boolean-safe integer checks and `math.isfinite` for floats; do not float-convert arbitrarily large Python integers. Preserve opaque values and unchanged bytes. Parent context can be passed privately to `_blocks`/`_source`; do not add a generic schema interpreter or import private route helpers just to avoid a small local check.
- [ ] **Step 5: Run GREEN.** `just test-one tests/test_egress_route.py tests/test_egress_dialect.py tests/test_egress_server.py -v`. Confirm nonzero test counts, zero failures and all named groups exercised. Re-run any affected proxy/launch cases through `just test-one` if testmon does not select them. Do not rerun the historical characterization probe as a fix test: its old-verdict assertions should no longer hold.
- [ ] **Step 6: Update current-behavior documentation.** README replaces the unenforced "Never list fallbacks" warning with route-load refusal, states the finite supported subset and compatibility exclusions, and links decision 13 for exact shapes. Keep the example route's source permissions and feature tokens; explain a listed beta does not admit undefined body shapes. Preserve its historical pi 1.1.0 date qualification. Keep the amendment marked approved but not implemented through Task 2 and its review. The implemented marker moves only in the final-integration step below.
- [ ] **Step 7: Precommit verification and commit.** Run `just test-fast`, `just check`, `git diff --check`; record test count, exit statuses and warnings. If test-fast selects none, focused runs above supply behavioral evidence; report that limit, do not call an empty run a suite. Stage only Task 2's named files; commit `fix(egress): close supported messages control shapes`.

## Self-review and final integration

The two deliverables are sequential, share no new public interface, and stay in
one worktree. No decomposition children are needed for inline execution; record
progress on autonomy-58799c. The revised coverage includes the explicit authorized-custom positive, the
exact deferred placeholder in a plain body, and 400-digit integer tokens at both
permitted numeric fields in unit and HTTP tests. These close the round-2 review
gaps rather than relying on the rejected inline capture or a prose-only overflow
warning. The five Review Focus risks each have a named test. No additional design decision is
left to the implementer; private helper layout and parameterized-case grouping
remain the builder's choice.

- [ ] Use executing-plans for inline execution after human plan approval. Follow its review workflow, with a fresh read-only whole-branch reviewer at a frozen code revision. The controller saves the full returned review as a `*-report.md` in the plan workspace, records the task's review-round note before acting, and keeps findings/rulings in its ledger.
- [ ] Resolve or rule on Critical/Important findings through corrective rounds (up to five), using a fresh reviewer per scoped re-review. Minor findings become `minor (deferred)` ledger entries and are reported whole. Any ruling records decision, Why, Cost and revision; do not invent a reason/cost absent from the record.
- [ ] After the final whole-branch review and all required corrective rounds accept the implementation, mark the approved amendment implemented in `docs/specs/2026-10-12-envelope-design.md`, retaining its frozen approval revision and evidence limitations. This status-only update follows review; it is not part of Task 2's earlier commit. Run `just check` and `git diff --check`, then commit `docs(egress): record closed policy implementation`.
- [ ] If a correction is made after task closure but before integration, reopen with `tasks edit autonomy-58799c --status todo`, then `tasks start autonomy-58799c`; release with done/park before reporting.
- [ ] Follow the project's full-suite policy: execution setup owes `just test`; after edits use focused and fast checks, with full suite only when hooks are absent or affected behavior lacks fast coverage. A green nonempty run is required evidence, with counts and limits recorded.
- [ ] Once reviewed and verified, record retained resources and `tasks done autonomy-58799c` on the branch, then merge locally into main under the personal-profile permission. Preserve concurrent main changes; never amend/rebase a frozen revision during an open review. No push or PR without separate authorization.
- [ ] Before worktree removal, run `tt-report`, inspect tracked and ignored state, preserve each needed review/evidence artifact on the task and verify hashes, finish the ledger, and check host launchers/units/config includes for pointers into the worktree. Remove only after each ignored item has a disposition. End with processes, review rulings/deferred minors, branch/worktree and integration state disclosed.
