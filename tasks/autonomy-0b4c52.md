---
id: autonomy-0b4c52
title: Rewrite t@t commit authorship in this repository
status: done
priority: 2
size: s
complexity: low
process: direct
owner: main
created: 2026-10-16T16:32:03Z
updated: 2026-10-16T19:08:45Z
started: 2026-10-16T19:06:12Z
completed: 2026-10-16T19:08:45Z
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
- 2026-10-16T19:07:44Z (main): attached: 2026-10-16-identity-commit-map.txt (20545 bytes): Authorship rewrite map: 250 changed commit IDs; resolves historical references while preserving append-only task notes.
- 2026-10-16T19:08:44Z (main): Verified all 257 original commit objects byte-for-byte after substituting only mapped parent IDs and t@t author/committer identities: 247 identities corrected, 250 hashes changed, every tree/message/timestamp preserved, no commit messages cite changed SHAs, zero t@t identities on all local refs. Attached SHA map resolves 15 historical references across task records and a note. Verified bundle, original Titan index and full audit retained at WORK_ROOT/autonomy/identity-rewrite-20261016T190712Z on Titan. Europa refs synced, zero t@t, all actual tracked file contents match HEAD; its pre-existing stale index is unchanged and backed up at /tmp/autonomy-identity-index-k5pajhos/index on Europa. just setup and tasks check passed; test-fast ran all 443 tests and passed (one coverage-context warning). Following ops-e5b39c completed pilot satisfies this repository dependency while the wider runbook remains open. Publish main with explicit lease ddab3e58ce7063e739d9ed91811f7bed7cc66529 and mandatory full pre-push gate; obs re-indexing remains tracked by wider rollout.
- 2026-10-16T19:08:45Z (main): done
  provenance: {"harness_session":"codex:01a14601-1483-73f2-8d62-ddb64b8f043b","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-16T19:08:45Z (main): Corrected 247 author/committer identities with filter-repo in an isolated mirror; verified every original commit preserves tree, dates, message and topology; attached 250-entry SHA map and retained bundle/index backups. Europa refs and tracked contents verified; pre-existing stale index preserved. All 443 tests and task checks passed. Close overrides only the still-open wider runbook dependency: its completed pilot procedure was followed. Publishing main next with original remote SHA as lease and full pre-push gate enabled.
  provenance: {"harness_session":"codex:01a14601-1483-73f2-8d62-ddb64b8f043b","harness_session_source":"CODEX_THREAD_ID"}
