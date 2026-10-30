---
id: autonomy-23aeff
title: Adopt shared broad-test policy and remote verification
status: doing
priority: 2
size: m
complexity: mid
process: planned
owner: design/autonomy-23aeff-test-policy
created: 2026-10-29T13:45:42Z
updated: 2026-10-30T14:15:09Z
started: 2026-10-30T14:13:58Z
depends: [ops-68729d]
tags: []
source: "tt-policy:autonomy"
agent: codex
origin: agent
---

Adopt the approved shared test execution policy for this personal project after the ops pilot. Owner: the next autonomy implementer; Keith approves external activation. State: pending preparation, not offloaded. Shared authority: ops-8bfa85 (read its approved spec and plan with tasks doc); pilot prerequisite ops-68729d.

Observed 2026-10-29: code checkout is its own Git top level; records kind in-tree; profile personal. Current policy file: absent (enabled). Wrapper: {"tools/tt": "# tt version 7"}. Commands: test-fast, test-one, test, check, setup, hook-pre-commit, hook-pre-push. Read [ref:front-door] for actual commands and setup. Workflows: None found..

Current command/ref declarations:
```
fast_cmd := "cd python && uv run pytest --testmon"
test_cmd := "cd python && uv run pytest"
ci_suite_refs := ""
ci_remote := "origin"
one_cmd := "cd python && uv run pytest"
```

Prepare a reviewed project-specific design/plan and isolated worktree. Adopt the published wrapper only after ops and obs readers are live. Keep test-one/focused implementation checks and mandatory hygiene on; split broad lint/type/test work into explicit targets. Preserve current selectors and argument forwarding. Add the forced test-full route. Verify branch/ref coverage against workflow triggers and use explicit TT_FORCE=1 for the full remote suite, including nested recipes. One suite per push, latest-ref cancellation, no duplicate internal-PR run. Keep local policy enabled until an approved hosted invocation finishes with a nonzero test count and accepted coverage.

Inventory capability omissions and private sibling checkouts from actual workflow/setup; none are presumed equivalent to local verification.

Prepare the activation packet with current private-repository allowance and enforced no-paid-overage setting, setup, exact refs, executed tests, excluded modules and skipped-test/module counts. Publishing workflows, live global instruction/hook delivery and account changes require explicit approval. Existing work/external/shared Git roots are not independent opt-ins. Reuse host/profile proof only for identical setup paths. Detached records remain separate from code policy lookup.

After approved activation, commit .tt.toml with real broad target names, verify focused execution/recorded skip/forced failure/covered remote push, and retire each disabled timing obligation explicitly without claiming performance verification. Record the actual activation revision/time here. On hook-split integration and rollback write exactly: policy: enabled at <RFC3339-UTC> revision <full-sha>. This record's source tt-policy:autonomy is the latency floor lookup key. Keep remaining diagnosis and unrelated obligations. Report status to ops-39bff6; never label pending work as offloaded. The first actual activation files the 30-day regret review under ops; no scheduler and no invented date.

## References

- front-door (input, required, kind=configuration): justfile

## Notes

- 2026-10-29T13:45:42Z (add): created
  provenance: {"harness_session":"codex:01a1874f-c2d8-7320-ae81-7114e37e343f","harness_session_source":"CODEX_THREAD_ID","origin":"agent"}
- 2026-10-30T14:13:58Z (main): started
  provenance: {"harness_session":"codex:01a18c8a-2c3b-7a23-ad9a-ee1621b14ebb","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-30T14:15:08Z (design/autonomy-23aeff-test-policy): resumed
  provenance: {"harness_session":"codex:01a18c8a-2c3b-7a23-ad9a-ee1621b14ebb","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-30T14:15:09Z (design/autonomy-23aeff-test-policy): Intent traced to the filing session codex:01a1874f-c2d8-7320-ae81-7114e37e343f human turns at 2026-10-29T11:25:29Z and 11:36:20Z: reduce local broad verification contention, retain focused implementation tests, use wrapper-owned policy and push CI; binary policy is the approved shared design. Shared spec 1ce9abe and plan ddcfdab approved; ops pilot complete, ops tt v8 and obs schema17/parser2 readers landed. Project process remains planned; this phase prepares the project design only. Isolated .worktrees/autonomy-23aeff on design/autonomy-23aeff-test-policy hydrated with just setup; broad baseline deferred to implementation Setup. No runtime, workflow publication or policy change.
