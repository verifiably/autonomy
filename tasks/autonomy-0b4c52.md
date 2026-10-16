---
id: autonomy-0b4c52
title: Rewrite t@t commit authorship in this repository
status: doing
priority: 2
size: s
complexity: low
process: direct
owner: main
created: 2026-10-16T16:32:03Z
updated: 2026-10-16T19:06:52Z
started: 2026-10-16T19:06:12Z
depends: [ops-e5b39c]
tags: []
source: git-identity-leak-2026-10-07
agent: claude-code/claude-opus-5-5
---

Rewrite this repository's t <t@t> commits (from the 2026-10-07 global-config leak; see ops-5749d9) to Keith Hughitt <keith.hughitt@gmail.com>, following the runbook ops-e5b39c. Inventory on titan 2026-10-16: 247 t@t commits on all refs, 0 unpushed on main, 1 worktree(s); remote: verifiably/autonomy.

## Notes

- 2026-10-16T19:06:12Z (main): started
  provenance: {"harness_session":"codex:01a14601-1483-73f2-8d62-ddb64b8f043b","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-16T19:06:52Z (main): User confirmed Europa idle for this rewrite. Direct history maintenance following ops-e5b39c completed pilot: only main on both hosts, no tags/stashes/extra worktrees, 247 t@t commits; remote has only main, no open PRs, main unprotected. Prepare verified bundle and scratch mirror outside Dropbox; filter all refs once; prove commit objects differ only by mapped parents and identity (trees/messages/timestamps preserved); swap refs with old-value guards; attach changed-entry map for historical references; run mandatory full pre-push gate and push with explicit lease. No source-code changes or code worktree needed. Europa reports a stale index for the task record; preserve its index and check actual tracked file bytes before changing refs.
