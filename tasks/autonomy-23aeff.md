---
id: autonomy-23aeff
title: Adopt shared broad-test policy and remote verification
status: done
priority: 2
size: m
complexity: mid
process: planned
owner: main
created: 2026-10-29T13:45:42Z
updated: 2026-10-30T23:54:57Z
started: 2026-10-30T14:13:58Z
completed: 2026-10-30T23:01:46Z
closed: 2026-10-30T23:01:46Z
depends: [ops-68729d]
tags: []
source: "tt-policy:autonomy"
model: claude-opus-5-5
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
- 2026-10-30T18:00:14Z (main): Latency disposition at registered main b6fdc728a1ac80f947751d5bda0c7507a457b154: no autonomy test-latency incident or halt; the only open test-latency task across projects is mm-f1dccf (multiple-myeloma, unrelated). Nothing retired; no performance-verification claim.
- 2026-10-30T18:00:51Z (main): attached: activation-packet-c.md (3427 bytes): Packet C: push local main (97 commits incl. another session's ops-check v16 vendoring 0ab3671); policy-off run 41101402802 1395/1395
- 2026-10-30T18:00:53Z (main): parked (waiting on user, approval): User approves packet C (attached): git push origin main. Then the agent verifies main's hosted run and finishes Task 6 (report to ops-8bfa85 and ops-56aab7, retained items, close).
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T18:08:21Z (main): resumed
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T18:08:24Z (main): User approved packet C: pushed main 3c5f272ab1b5aa820a0af9191a0a2bf451384a41 (55417bc..3c5f272, incl. 0ab3671); local hook ran hygiene and recorded test-fast skipped by policy; main run 41104200861.
- 2026-10-30T18:15:11Z (main): Main hosted run 41104200861 (head 3c5f272) FAILED: 1 failed, 1394 passed of 1395; proof 45/45; 21 modules. The failure is test_e21_the_model_route_is_the_actors_only_way_out: the proxy closed by lease (30 s elapsed) instead of close; it passed on the same code in runs 41095831866 and 41101402802, and takes 1.7 s locally. Filed autonomy-1ba43a. Log sha256 66bc428ed89938e9020972c951b7ff1c966a88d667e0baa1e92e2b84cd1d3d23. Policy stays as landed (disabled at b6fdc72); rollback is the user's call.
- 2026-10-30T18:15:22Z (main): parked (waiting on user, decision): User decides: keep local policy off and approve a diagnostic hosted run for autonomy-1ba43a (per-test durations; the last pilot push or a workflow_dispatch on main), or roll back to automatic_broad = true. Then the agent fixes autonomy-1ba43a, verifies main green, and finishes Task 6 (ops-8bfa85 and ops-56aab7 reports, retained items, close).
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T22:58:23Z (main): resumed
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T22:58:24Z (main): Main hosted run 41141028249 (head 3b281bd, includes the autonomy-1ba43a fix) success: full suite 1398/1398, 0 skipped, 21 modules, proof 45/45. Log archive sha256 421977fe56665665fa78eb7fcbd8273a49f09e892ab77fd0982ba0dab6cbdfe9. Main is green with policy off.
- 2026-10-30T22:59:00Z (main): attached: hosted-run-41095831866.log (92083 bytes): Hosted run 41095831866: accepted coverage, 1394/1394 (packet B)
- 2026-10-30T22:59:48Z (main): attached: hosted-run-41089297381.log (129356 bytes): Pilot push 1: namespace proof failed under Ubuntu AppArmor userns restriction
- 2026-10-30T22:59:49Z (main): attached: hosted-run-41090873620.log (131344 bytes): Pilot push 2: sysctl lifted; sandbox /lib64 layout defect (autonomy-7f4bc7)
- 2026-10-30T22:59:50Z (main): attached: hosted-run-41101402802.log (73705 bytes): Policy-off head 26c8a0e: 1395/1395
- 2026-10-30T22:59:51Z (main): attached: hosted-run-41104200861.log (80291 bytes): Main 3c5f272: e21 closed by lease (autonomy-1ba43a)
- 2026-10-30T22:59:52Z (main): attached: hosted-run-41107688532.log (82013 bytes): Diagnostic d4a6bae: durations; e21 passed
- 2026-10-30T22:59:53Z (main): attached: hosted-run-41112785423-logs.zip (39445 bytes): Diagnostic a8338d7 log archive: sweep 12.39 s first in job; resolver configuration
- 2026-10-30T22:59:53Z (main): attached: hosted-run-41120536343-logs.zip (39398 bytes): Renewal fix be0dea3 log archive: 1399/1399
- 2026-10-30T22:59:54Z (main): attached: hosted-run-41141028249-logs.zip (36473 bytes): Main 3b281bd log archive: 1398/1398, green
- 2026-10-30T22:59:55Z (main): attached: local-suite-9523dc4.log (3099 bytes): Local forced suite at 9523dc4: 1394/1394, compared in packet B
- 2026-10-30T23:00:10Z (main): attached: plan-ledger-progress.md (7732 bytes): Executing-plans ledger for the test policy plan: task completions, rulings, deferred minors
- 2026-10-30T23:00:38Z (main): attached: local-suite-f71c605.log (3099 bytes): Local forced suite at f71c605: 1382/1382, cited in packet A
- 2026-10-30T23:00:39Z (main): attached: policy-off-verify-rows.jsonl (899 bytes): TT_LOG rows from Task 5 Step 4: test skipped (policy-disabled, exit null) and forced run (exit 0, 1395 tests)
- 2026-10-30T23:00:59Z (main): Scratch disposition before removal: attached (sha256 verified against the scratch copies): packets A/B/C, hosted-run logs 41089297381, 41090873620, 41095831866, 41101402802, 41104200861, 41107688532, log archives 41112785423, 41120536343, 41141028249, local suites f71c605 and 9523dc4, policy-off TT_LOG rows, plan ledger. Discarded as regenerable or already recorded in notes and attachments: the rustup 1.99.1 toolchain, cargo home, tasks-src and tasks-target (pinned build, about 860 MB), the rehearsal env and its hygiene log, cargo/rustup logs, push and run-watch output, plain-text extracts and module lists derived from the attached logs, the truncated gh view of 41112785423 (archive attached), .head files and origin-main..main.txt (SHAs in notes, range from git).
- 2026-10-30T23:01:00Z (main): retained: {"host":"titan","kind":"scratch","path":"$WORK_ROOT/autonomy/autonomy-23aeff","state":"released","verification":"verified","purpose":"Removed 2026-10-30 after its evidence was attached to autonomy-23aeff (hashes verified) and the rest was discarded as regenerable or recorded in notes","next_owner":"none","cleanup_trigger":"none"}
- 2026-10-30T23:01:26Z (main): retained: {"host":"titan","kind":"worktree","path":".worktrees/autonomy-23aeff","state":"released","verification":"verified","purpose":"Removed 2026-10-30 after integration into main (head 315dc1d merged; main pushed at 3b281bd): tree clean, tt-report run, no host pointers, no submodules; ignored files were caches, the venv and testmon data (regenerable) and the plan ledger (attached as plan-ledger-progress.md); local branch deleted, remote branch design/autonomy-23aeff-test-policy left on origin","next_owner":"none","cleanup_trigger":"none"}
- 2026-10-30T23:01:45Z (main): resumed
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T23:01:46Z (main): done
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T23:01:46Z (main): Adopted: policy disabled at 2026-10-30T17:59:04Z revision b6fdc728a1ac80f947751d5bda0c7507a457b154; main green at 3b281bd (run 41141028249, 1398/1398); evidence attached (packets A-C, hosted logs, ledger).
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T23:42:55Z (main): Remote branch design/autonomy-23aeff-test-policy (head be0dea3, contained in origin/main) deleted from origin at the user's request 2026-10-30; origin now has only main.
- 2026-10-30T23:45:25Z (main): Disclosure 2026-10-30: origin/main advanced 3b281bd..a35145d (task-record commits only) during the remote branch deletion; the mechanism is not established and no main push was intended. That push's run 41145953343 failed at Hygiene on attachment eligibility; filed autonomy-e51da5.
- 2026-10-30T23:54:55Z (main): retained: {"host": "titan", "kind": "evidence", "path": "$WORK_ROOT/autonomy/autonomy-23aeff/portable-log-repair-e51da5/local-suite-f71c605.log", "state": "kept", "verification": "verified", "purpose": "Exact raw suite evidence underlying the portable attachment on autonomy-23aeff", "next_owner": "task:autonomy-e51da5", "cleanup_trigger": "After a published tasks CLI with attachments support is pinned and normal hosted hygiene accepts the raw attachment, reassess preservation", "sha256": "8a081b5ad21d9b4208553cc15ef3c7050daf06fac30919d964a046a7e33bb228"}
- 2026-10-30T23:54:56Z (main): retained: {"host": "titan", "kind": "evidence", "path": "$WORK_ROOT/autonomy/autonomy-23aeff/portable-log-repair-e51da5/local-suite-9523dc4.log", "state": "kept", "verification": "verified", "purpose": "Exact raw suite evidence underlying the portable attachment on autonomy-23aeff", "next_owner": "task:autonomy-e51da5", "cleanup_trigger": "After a published tasks CLI with attachments support is pinned and normal hosted hygiene accepts the raw attachment, reassess preservation", "sha256": "0911fc7267306f75a5c7f45dae7db951b65644ce725b9f142f6c9b90eb395482"}
- 2026-10-30T23:54:57Z (main): Portable derivative mapping for local-suite-f71c605-portable.log and local-suite-9523dc4-portable.log: <PYTEST_ROOT> = /mnt/ssd3/work/autonomy/.worktrees/autonomy-23aeff/python. Exact originals retained under $WORK_ROOT/autonomy/autonomy-23aeff/portable-log-repair-e51da5/ with per-file SHA-256 records above; current owner autonomy-e51da5. Only this rootdir value changes; test results remain historical evidence, not a fresh run.
