---
id: autonomy-23aeff
title: Adopt shared broad-test policy and remote verification
status: doing
priority: 2
size: m
complexity: mid
process: planned
owner: main
created: 2026-10-29T13:45:42Z
updated: 2026-10-30T17:59:19Z
started: 2026-10-30T14:13:58Z
depends: [ops-68729d]
tags: []
source: "tt-policy:autonomy"
agent: codex
origin: agent
spec: docs/specs/2026-10-30-test-execution-policy-design.md
plan: docs/plans/2026-10-30-test-execution-policy.md
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
- 2026-10-30T14:19:25Z (design/autonomy-23aeff-test-policy): Design frozen at ec27ca5c3a90f66c2178ca7b5a48f35fe1e7e1b3:docs/specs/2026-10-30-test-execution-policy-design.md; read-only builder review dispatched before user design review. GitHub API verified PUBLIC and zero workflows; standard public hosted compute needs no private-minute allowance. Current tt is v8 (task filing snapshot v7 is outdated). Proposed Ubuntu24 system Python includes required os.setns; namespace exception remains conditional and explicitly gated with publication. No implementation, policy file, push, hosted run, or host security change. just check passed with two pre-existing unlinked-step warnings; isolated tasks check exited 0 with 23 explicit foreign-graph/unlinked warnings. No suite run in documentation-only phase.
- 2026-10-30T14:19:54Z (design/autonomy-23aeff-test-policy): review: spec round 1 — verdict: accept; findings: none; reviewer: codex/gpt-6.1-sol
- 2026-10-30T14:19:57Z (design/autonomy-23aeff-test-policy): attached: design-builder-report.md (876 bytes): Full read-only builder review by codex/gpt-6.1-sol of frozen ec27ca5; accepted with zero Critical, Important or Minor findings.
- 2026-10-30T14:20:31Z (design/autonomy-23aeff-test-policy): Builder review is attached and listed by tasks show; SHA-256 17ff83849d2fbe390f4eb696f12d484961fa900edf2416bb7f943105ad8d3c66 matched the workspace copy before its removal. Review accepted with no findings; no rulings or deferred minors. No standalone scratch/evidence copy remains. Design content stays frozen at ec27ca5c3a90f66c2178ca7b5a48f35fe1e7e1b3.
- 2026-10-30T14:20:33Z (design/autonomy-23aeff-test-policy): retained: {"host":"titan","kind":"worktree","path":".worktrees/autonomy-23aeff","state":"kept","verification":"verified","purpose":"Frozen design ec27ca5 and attached accepted builder review await user design review; branch design/autonomy-23aeff-test-policy is unmerged","next_owner":"task:autonomy-23aeff","cleanup_trigger":"After user design review, approved planning and authorized integration, inspect ignored files and host pointers and harvest timings before considering removal"}
- 2026-10-30T14:20:34Z (design/autonomy-23aeff-test-policy): parked (waiting on user, review): User reviews frozen autonomy revision ec27ca5c3a90f66c2178ca7b5a48f35fe1e7e1b3:docs/specs/2026-10-30-test-execution-policy-design.md in .worktrees/autonomy-23aeff. After approval, agent resumes this worktree and writes the implementation plan for separate user review; revisions get a new frozen commit. Policy remains enabled; hosted publication and activation have separate approval gates.
  provenance: {"harness_session":"codex:01a18c8a-2c3b-7a23-ad9a-ee1621b14ebb","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-30T15:03:59Z (design/autonomy-23aeff-test-policy): resumed
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T15:04:00Z (design/autonomy-23aeff-test-policy): review: spec round 2 — verdict: accept; findings: none; reviewer: human
- 2026-10-30T15:24:53Z (design/autonomy-23aeff-test-policy): review: plan round 1 — verdict: revise; findings: Important 3, Minor 11; reviewer: claude-code/claude-opus-5-5
- 2026-10-30T15:28:36Z (design/autonomy-23aeff-test-policy): review: plan round 2 — verdict: accept; findings: Minor 4; reviewer: claude-code/claude-opus-5-5
- 2026-10-30T15:28:46Z (design/autonomy-23aeff-test-policy): parked (waiting on user, review): User reviews frozen plan a2c20a083a248b6690e5add1eccecec6f6900c4b:docs/plans/2026-10-30-test-execution-policy.md in .worktrees/autonomy-23aeff and picks inline or subagent-driven execution; the agent then resumes this worktree, runs the full baseline (just test) and starts Task 1 (autonomy-216f8d). Policy stays enabled; pilot push, coverage acceptance and main push each have their own packet approval.
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T15:48:14Z (design/autonomy-23aeff-test-policy): resumed
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T15:48:15Z (design/autonomy-23aeff-test-policy): review: plan round 3 — verdict: accept; findings: none; reviewer: codex/gpt-6.1-sol
- 2026-10-30T15:48:16Z (design/autonomy-23aeff-test-policy): review: plan round 4 — verdict: accept; findings: none; reviewer: human
- 2026-10-30T15:48:17Z (design/autonomy-23aeff-test-policy): Plan a2c20a0 accepted; execution: native (inline) with fresh reviewers at Task 3 Step 0 and Task 5 Step 5. Approval clarification (user): packet A's five-push limit is a cap; each pilot retry still needs approval for its exact revision.
- 2026-10-30T15:57:31Z (design/autonomy-23aeff-test-policy): Scratch directory created: host titan, /mnt/ssd3/work/autonomy/autonomy-23aeff; purpose: activation evidence for Tasks 3-5 (local suite log, rehearsal build, packets, hosted logs); owner: task:autonomy-23aeff; contents still mutable.
- 2026-10-30T16:09:18Z (design/autonomy-23aeff-test-policy): review: impl round 1 — verdict: accept; findings: Minor 4; reviewer: claude-code/claude-opus-5-5
- 2026-10-30T16:10:11Z (design/autonomy-23aeff-test-policy): attached: activation-packet-a.md (5313 bytes): Pilot push packet A (code f71c605): branch push, limits, local counts, AppArmor exception
- 2026-10-30T16:10:12Z (design/autonomy-23aeff-test-policy): parked (waiting on user, approval): User approves packet A (attached): the pilot push of design/autonomy-23aeff-test-policy (code f71c605) and, separately, the conditional AppArmor runtime sysctl. Then the agent verifies the head differs from f71c605 only in tasks/, checks ssh -T greets khughitt, pushes, and runs Task 4 Step 2.
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T16:22:32Z (design/autonomy-23aeff-test-policy): resumed
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T16:22:33Z (design/autonomy-23aeff-test-policy): Packet A approved by user 2026-10-30: one initial pilot push (code f71c605, head 2f261d7, tasks-only since), 15-min timeout, 5-push cap with per-retry revision approval; AppArmor runtime sysctl approved conditional on the first run showing that restriction caused the namespace failure, corrective revision still needs approval. Pushed 2f261d76d7850d31bb96e2d995961a382ca368dc to origin (push 1/5).
- 2026-10-30T16:25:49Z (design/autonomy-23aeff-test-policy): Hosted run 41089297381 (head 2f261d7) failed at the namespace and TLS proof: 12 failed, 32 passed of 44; Python 3.12.3 at /usr/bin/python3; kernel.apparmor_restrict_unprivileged_userns=1. Every failure is bwrap 'loopback: Failed RTM_NEWADDR: Operation not permitted' (capabilities denied in the new user namespace) or downstream of it (sandbox gone, /proc/<pid>/ns/net missing). The approved condition for the AppArmor runtime sysctl is met; Hygiene and Full suite were skipped. Log sha256 36c6aac4df0da602d817ec1d1dd07b651cab0ea1b83eb434ca2c1b197e574c4b.
- 2026-10-30T16:26:33Z (design/autonomy-23aeff-test-policy): parked (waiting on user, approval): User approves pushing corrective revision 30efc34d42b79cccf715aa4c1c5d85effedcf5fc (runtime AppArmor sysctl step, approved conditionally; condition met in run 41089297381) as pilot push 2/5; head may add tasks/-only commits. Then the agent rechecks tasks-only diff, visibility and ssh identity, pushes, and repeats Task 4 Step 2.
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T16:33:16Z (design/autonomy-23aeff-test-policy): resumed
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T16:33:18Z (design/autonomy-23aeff-test-policy): User approved retry; pushed 29e81e2723a01de84a44e13b167e729fad582c86 (code 30efc34, tasks-only since) as pilot push 2/5; run 41090873620.
- 2026-10-30T16:36:45Z (design/autonomy-23aeff-test-policy): Hosted run 41090873620 (head 29e81e2, sysctl lifted to 0): namespaces now form, but the proof failed 12/44 with 'execvp /usr/bin/true: No such file or directory' and its consequences. Root cause (confirmed in a local ubuntu:24.04 container): sandbox SYSTEM_SYMLINKS maps /lib64 -> usr/lib (Arch); Ubuntu's loader lives under usr/lib64. Product defect, outside this adoption's scope: filed autonomy-7f4bc7 (concerns autonomy-422173). Pilot blocked on it; 2 of 5 pushes used. Log sha256 df301f8680780d66f6ac5a6c7717d63d73843eeb7ffe68cdfc4a83ff45d01c5c.
- 2026-10-30T16:54:45Z (design/autonomy-23aeff-test-policy): Sandbox layout fix autonomy-7f4bc7 reviewed (2 rounds, accept) and merged to main f0c0d37; main merged into the pilot branch as a171725. Pilot push 3/5 of a171725 awaits user approval.
- 2026-10-30T16:54:47Z (design/autonomy-23aeff-test-policy): parked (waiting on user, approval): User approves pilot push 3/5 of a171725 (sandbox layout fix autonomy-7f4bc7 merged in); then the agent pushes and continues Task 4 Step 2.
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T17:06:34Z (design/autonomy-23aeff-test-policy): resumed
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T17:06:36Z (design/autonomy-23aeff-test-policy): User approved pilot push 3/5 of a17172577904537cfa8c339b7a707ab5fa51b80b (later changes only under tasks/); pushed head 9523dc4ae73140efdfb2e25fabdd4f1a27a7c863; run 41095831866.
- 2026-10-30T17:12:38Z (design/autonomy-23aeff-test-policy): Hosted run 41095831866 (head 9523dc4, code a171725) success in 3m02s: full suite 1394/1394 passed, 0 skipped, 21 modules identical to local, 0 excluded; proof 45/45; hygiene 23 known warnings. Local forced suite at same head 1394/1394. Log sha256 1b208a41e691fdaaf80b75f0f6e41bca9b0239924cc54a4bf17e634887dc0fea.
- 2026-10-30T17:12:39Z (design/autonomy-23aeff-test-policy): attached: activation-packet-b.md (3342 bytes): Packet B: coverage acceptance (run 41095831866, 1394/1394 local = hosted) and the policy-off branch push
- 2026-10-30T17:12:41Z (design/autonomy-23aeff-test-policy): parked (waiting on user, approval): User decides packet B (attached): accept hosted coverage of run 41095831866 and approve pilot push 4/5 of the policy-off commit; then the agent runs Task 4 Step 5 and Task 5.
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T17:37:38Z (design/autonomy-23aeff-test-policy): User accepted packet B 2026-10-30 ('Accepted.'): hosted coverage of run 41095831866 accepted as equivalent; read as also approving pilot push 4/5 of the reviewed policy-off commit.
- 2026-10-30T17:37:48Z (main): resumed
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T17:37:49Z (main): policy: enabled at 2026-10-30T17:37:39Z revision 333556916b25706c852e2c893f21ceca68f0aeba
- 2026-10-30T17:44:43Z (design/autonomy-23aeff-test-policy): review: impl round 2 — verdict: revise; findings: Important 1, Minor 3; reviewer: claude-code/claude-opus-5-5
- 2026-10-30T17:47:12Z (design/autonomy-23aeff-test-policy): review: impl round 3 — verdict: accept; findings: none; reviewer: claude-code/claude-opus-5-5
- 2026-10-30T17:47:12Z (design/autonomy-23aeff-test-policy): Pilot push 4/5 under packet B: 26c8a0e26e63aa9424463cee0fbf82cd6e831379 (policy-off fc775b8 + AGENTS cadence fix 26c8a0e, both reviewed); local hook ran hygiene and recorded test-fast skipped by policy; run 41101402802.
- 2026-10-30T17:59:16Z (main): policy: disabled at 2026-10-30T17:59:04Z revision b6fdc728a1ac80f947751d5bda0c7507a457b154
- 2026-10-30T17:59:19Z (main): resumed
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
