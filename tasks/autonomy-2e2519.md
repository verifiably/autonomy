---
id: autonomy-2e2519
title: "Analyst launch: a fresh pi analyst with caller-declared inputs, outputs and denied paths under the sandbox, with a scripted-upstream tool-denial check"
status: todo
priority: 2
size: l
complexity: high
process: planned
created: 2026-10-31T21:04:57Z
updated: 2026-10-31T21:04:57Z
depends: []
tags: [sandbox]
source: hq-a99924
agent: claude-code/claude-opus-5-5
origin: mixed
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
