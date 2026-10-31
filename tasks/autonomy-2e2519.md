---
id: autonomy-2e2519
title: "Analyst launch: a fresh pi analyst with caller-declared inputs, outputs and denied paths under the sandbox, with a scripted-upstream tool-denial check"
status: doing
priority: 2
size: l
complexity: high
process: planned
owner: analyst-launch
created: 2026-10-31T21:04:57Z
updated: 2026-10-31T21:31:05Z
started: 2026-10-31T21:07:12Z
depends: []
tags: [sandbox]
source: hq-a99924
agent: claude-code/claude-opus-5-5
origin: mixed
spec: docs/specs/2026-10-12-envelope-design.md
---

Outcome: a supported launch that starts a fresh pi analyst under the envelope's sandbox with only caller-declared read-only inputs and one output directory, enforced denial of caller-declared private paths (key, source data, world) across every pi tool, and a passing zero-cost check that proves it. mm's Phase 2 pilot (mm-62e2da, plan docs/plans/2026-10-18-phase-2-descriptive-report.md Task 8) keeps its analyst-isolation gate closed until this check passes.

Why: hq-a99924 (2026-10-31) qualified the existing routes read-only and found none supported. `autonomy run` closes every run `unwired` before launch and has no flags for input binds, outputs or extra denied paths; the only code that runs pi under the sandbox is scripts/egress_live.py, a one-prompt test of E21. Envelope design section 7 binds only toolchain paths and derives its denied set from the world configuration, so caller-declared binds and denied paths are a design change, autonomy's to decide.

The pinned contract, the threat notes and the full check recipe are in hq docs/notes/2026-10-15-headless-workers-brief.md at hq commit fd1468b, section "Analyst launch qualification (hq-a99924, 2026-10-31)". Read it there (git -C <hq> show fd1468b:docs/notes/2026-10-15-headless-workers-brief.md); it is not restated here.

Approach (each piece as the brief specifies):
1. Design amendment to the envelope spec: caller-declared read-only input binds, an output directory under scratch, and extra denied paths beside the computed set. Human review gate.
2. The launcher: pi 1.1.0 run directly from hq's pin under sandbox.bwrap and the egress model route, as egress_live.py composes them, plus --no-context-files and a fixed --tools list; resolve every bind source; run prove immediately before launch.
3. Pre-launch bundle walk over each admitted tree: no submount (by mount id, not st_dev), no regular file with st_nlink > 1 (bundle, node and pi only), no file or directory inode equal to one under a denied root.
4. No-follow output release: openat2 with RESOLVE_BENEATH and RESOLVE_NO_SYMLINKS, O_PATH or O_NONBLOCK then fstat, regular files with st_nlink == 1 only.
5. The scripted-upstream tool-denial check: a local TLS upstream with a test CA answering scripted tool_use turns; random-suffixed fixtures holding fresh sentinels; allowed controls first (grep from / with glob !{proc,etc,usr}); denied read, bash, grep, find, ls and write for key, source and world; escape checks; judged on the host without following links. A grep error or a failed allowed control is inconclusive, never a pass.

Verification: the walk's negative tests plant a hard link, a same-filesystem bind submount and a tmpfs submount and see each refused; the release tests plant a symlink, a FIFO and a hard link; the scripted-upstream check passes per the brief's step 7 with no paid model call. A tool-level run against real key, source or world paths is a separate, authorized step and not part of this task.

Out of scope: naming mm's real denied set and bundle (mm), and running mm's Task 8 gate. A pi, node, bubblewrap, rg or fd version change is a new epoch for the check.

Not compared: a confined Codex executor; the gap is a launcher, which that route would also need.

## Notes

- 2026-10-31T21:04:57Z (add): created
  provenance: {"harness_session":"claude-code:11d3486a-d5fd-410b-a675-76d16a9f4384","harness_session_source":"CLAUDE_CODE_SESSION_ID","origin":"mixed"}
- 2026-10-31T21:07:12Z (main): started
  provenance: {"harness_session":"claude-code:fc4eb4dd-05c5-441e-9e3b-34ef5c547637","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-31T21:08:36Z (analyst-launch): resumed
  provenance: {"harness_session":"claude-code:fc4eb4dd-05c5-441e-9e3b-34ef5c547637","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-31T21:13:37Z (analyst-launch): process: planned; workspace .worktrees/analyst-launch (branch analyst-launch, just setup done; baseline deferred to execution Setup as the policy-off rule says). Origin read: hq-0806e7 (user: analyst isolation with enforced key/source/world denial), hq-a99924's verdict and the pinned brief section at hq fd1468b. Nothing is left for the user to describe, so the design amendment is written without questions, every call marked as mine; its review is the gate. Design shape: decision 14 in the envelope spec (declared inputs, extra denied paths, output directory, alias walk, no-follow release, the autonomy analyst launch), rows E23/E24, §13 item 6.
  provenance: {"harness_session":"claude-code:fc4eb4dd-05c5-441e-9e3b-34ef5c547637","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-31T21:30:26Z (analyst-launch): review: spec round 1 — verdict: revise; findings: important 2, minor 1; reviewer: claude-code/claude-fable-5-1
- 2026-10-31T21:31:04Z (analyst-launch): retained: {"host":"titan","kind":"worktree","path":".worktrees/analyst-launch","state":"kept","verification":"verified","purpose":"branch analyst-launch holding the decision 14 spec amendment (frozen 5c5c423) and this task record; the implementation plan and code land here after spec approval","next_owner":"task:autonomy-2e2519","cleanup_trigger":"branch analyst-launch merged into main after the implementation is reviewed and done"}
- 2026-10-31T21:31:05Z (analyst-launch): retention checkpoint: observed 2026-10-31T21:31:05Z on titan; basis autonomy in-tree . cfe9090c8dae4f863073e596343f9259021e67f4:tasks/autonomy-2e2519.md; retained by branch analyst-launch; this host: kept verified 1, kept unknown 0, released 0; changed 1. Rechecked all kept/verified items on this host; no task scratch under WORK_ROOT was created; session scratchpad copies (brief extract, amendment fragments) are regenerable; worktree ignored files are the uv environment. Other hosts hold nothing for this task. Next: user review of the spec amendment, then writing-plans.
  provenance: {"harness_session":"claude-code:fc4eb4dd-05c5-441e-9e3b-34ef5c547637","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
