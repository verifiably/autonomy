# Plan review round 2

Reviewer identity supplied in the review: claude-code/claude-opus-5-5.
Frozen reviewed revision: autonomy 10547f2b50b2cd60e1e294ef46535c545a04843f,
docs/plans/2026-10-29-closed-messages-policy.md.
Received through the user's message; reviewer reported no writes or processes.

## Full supplied review

My verdict on plan 10547f2 (`.worktrees/closed-messages/docs/plans/2026-10-29-closed-messages-policy.md`) is **revise**. It covers the approved decision-13 amendment closely, but two cases the spec requires have no test. Both fixes are small. I didn't change anything. autonomy-58799c is still parked waiting on your review. Once you rule, the plan's author revises it into a new frozen revision before execution starts.

I checked the plan against the approved spec at b1a325b, the current `route.py`, `dialect.py`, the egress tests and fixtures, and the pinned pi captures. The working file matches the frozen commit.

**Important**

1. **No test checks that pi's deferred placeholder tool is still accepted.** The spec requires it to be accepted (first row of its acceptance matrix, and "pi's deferred tool placeholder still passes"). In the pinned captures, the `__pi_deferred_placeholder__` tool (with `defer_loading: true`) only appears inside the `inline` capture. The plan expects that whole capture to be refused because of its `tool_addition` block. The plan's test groups never mention the placeholder, so a validator that wrongly refuses `defer_loading` would pass every planned test. The plan's self-review also says every compatibility case is covered, which isn't true for this one.
   - Fix: in `test_pinned_pi_payloads` or the key-set group, put that exact placeholder tool into an otherwise plain body and assert it's accepted.

2. **The overflow risk in number checks has no test.** The plan warns against converting huge integers to float but doesn't test for it, even though the Review Focus says every risk has an explicit test. A naive `math.isfinite(value)` on a JSON integer token of about 400 digits raises `OverflowError`. I confirmed this, and that `parse_body` accepts such a token since it's under the 4300-digit limit. `server.py:395` catches it and answers 502 with the request recorded as `upstream-error`. So a valid request, which the spec says should pass as a finite number, would get a misleading proxy failure.
   - Fix: add a case to `test_numeric_controls_do_not_coerce` with a very large integer token at `temperature` and `top_p`. It should be accepted, or at least never give a 502.

**Minor**

3. **The spec is marked implemented before review.** The file map says the spec should be marked implemented "only after acceptance and review pass". But Task 2 Step 6 marks it as soon as the checks pass, and that lands in Task 2's commit, before the whole-branch review. The marking should move to after the final review.
4. **No passing case for an explicit `"custom"` tool type at the body level.** The existing dialect test only shows `type: "custom"` refused when the route's `tool_types` is empty. Nothing shows it accepted when `tool_types=["custom"]` is listed, so a check that only ever refuses would pass. One accepted case in `test_nested_permissions_and_contexts` would close this.
5. **main has moved since the branch was created.** Commit ecd5858 added about 111 lines to `test_egress_server.py` and 5 to `egress_fixtures.py`, the same files Task 2 edits. Those new tests use `message()`, which already includes `max_tokens`, so they should still pass under the new checks. Still, the setup baseline would run on a stale base. Suggestion: merge main into the branch at execution setup, before running `just test`. That should happen after this review closes, so the frozen revision stays untouched.
6. **A test name doesn't match.** Task 1 Step 1 calls the test `test_undefined_route_capabilities_are_refused`, but the code sample defines `test_undefined_fields_are_refused`. The RED run's `-k` filter matches either name, so it's harmless, but one name should be chosen.

The rest of the plan holds up:
- The fourteen allowed fields match the spec table, and `custom` is the only tool type.
- Model refusal still comes before other body checks.
- Adding `max_tokens` to the duplicate-model mutation test is the right fix. It's the only existing test where real validation runs on a body that's meant to be forwarded.
- `1e999` parses as infinity and should get `body-refused`, as the plan says.
- The pinned captures match their recorded hash, and the `plain` and `effort` bodies fit the approved shapes.

Task 2 is large: one RED/GREEN cycle covering seven test groups, the server tests, the README and the spec. Splitting it would make review easier, but that's the author's call, not a defect.

For the task note: the session that wrote the plan's round-1 note records this one as `review: plan round 2 — verdict: revise; findings: Important 2, Minor 4; reviewer: claude-code/claude-opus-5-5`. I didn't write it.

Nothing was pushed or edited, and I started no background processes. The worktree `.worktrees/closed-messages` and branch `fix/closed-messages` are still unmerged and waiting on plan approval.
