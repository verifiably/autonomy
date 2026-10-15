---
id: autonomy-a41de4
title: Amend the envelope spec with how the actor's stdio is handled under autonomy run
status: doing
priority: 2
size: s
complexity: mid
process: direct
owner: spec/stdio
created: 2026-10-15T10:51:01Z
updated: 2026-10-15T12:58:29Z
started: 2026-10-15T11:36:01Z
depends: [autonomy-c5c566]
parent: autonomy-d9adef
tags: []
source: docs/notes/2026-10-15-authority-and-development-actors-brief.md
agent: claude-code/claude-opus-5-5
---

Why: the approved envelope spec never says what the actor's stdin, stdout and stderr are. Plan A's gate reads its release line on stdin and then reopens stdin on /dev/null (python/src/autonomy/sandbox/bwrap.py, _GATE), so a caller cannot drive an actor over stdio. crew's pi-cli-rpc runtime does exactly that (crew src/scopes.ts, src/runtime/pi-rpc.ts; crew core design §8.2 leaves the question to Plan B). Plan B's launch interface (autonomy-641123) must not be planned before this is settled, and it does not wait on the authorization contract (autonomy-1aac03) or the development mode (autonomy-d5c1cb).

Done: an amendment to docs/specs/2026-10-12-envelope-design.md (§7 and §3 at least) approved by the user. It picks one of the brief's stdio alternatives on autonomy-c5c566's evidence (current lean: pass-through, with the gate released on its own fd and autonomy run's own reports confined to stderr and the run directory), says what the caller may and may not do through the channel, and names the E-row that tests it. The sandbox change itself is implemented in Plan B or with it, not here.

Where: the brief at docs/notes/2026-10-15-authority-and-development-actors-brief.md §4 (Stdio); envelope spec §3, §7, §12; sandbox/bwrap.py launch and _GATE.

## Notes

- 2026-10-15T11:36:01Z (main): started
  provenance: {"harness_session":"claude-code:5012b356-782b-4ff4-b554-9cd759e28012","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-15T11:36:13Z (spec/stdio): resumed
  provenance: {"harness_session":"claude-code:5012b356-782b-4ff4-b554-9cd759e28012","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-15T11:41:49Z (spec/stdio): Draft amendment on spec/stdio: decision 12 pass-through; fds 0-2 must be pipe/socket//dev/null (stdio-refused); stdout actor-only; stderr run line then diagnostic; gate on own fd; SCM_RIGHTS a caller obligation; rw binds and separate cwd not added (actor argv keeps harness state in scratch; d5c1cb decides binds beyond scratch); row E20 in Plan B. Verified: bwrap --info-fd does not reach the actor; pre-release stdin bytes reach it; Node 'pipe' stdio is a socketpair.
- 2026-10-15T11:50:33Z (spec/stdio): review: spec round 1 — verdict: revise; findings: Critical 2, Important 3, Minor 8; reviewer: claude-code
- 2026-10-15T11:55:43Z (spec/stdio): review: spec round 2 — verdict: revise; findings: Important 2, Minor 7; reviewer: claude-code
- 2026-10-15T11:56:45Z (spec/stdio): On approval, file: crew task (stop an autonomy-run actor by SIGTERM to autonomy run, allow seal timeout+5 s+10 s grace+closing check before the scope stop; after autonomy-641123); note on sci-a1d45f (endpoint seals on SIGTERM, decision 5; stdout/stderr to endpoint.log).
- 2026-10-15T11:58:48Z (spec/stdio): review: spec round 3 — verdict: revise; findings: Important 2, Minor 6; reviewer: claude-code
- 2026-10-15T12:01:27Z (spec/stdio): review: spec round 4 — verdict: revise; findings: Important 1, Minor 7; reviewer: claude-code
- 2026-10-15T12:03:14Z (spec/stdio): review: spec round 5 — verdict: accept; findings: Minor 3; reviewer: claude-code
- 2026-10-15T12:03:28Z (spec/stdio): parked (waiting on user, review): User reviews the envelope amendment (decision 12 and its §3/§5/§6/§7/§8/§10/§12 E20/§13/§14 edits) on branch spec/stdio in .worktrees/spec-stdio. On approval the agent: marks the header approved, files the crew stop-path task and the sci-a1d45f note (see earlier note), merges spec/stdio, tasks done.
  provenance: {"harness_session":"claude-code:5012b356-782b-4ff4-b554-9cd759e28012","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-15T12:25:39Z (spec/stdio): resumed
  provenance: {"harness_session":"claude-code:5012b356-782b-4ff4-b554-9cd759e28012","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-15T12:25:39Z (spec/stdio): review: spec round 6 — verdict: revise; findings: P2 3; reviewer: human
- 2026-10-15T12:27:15Z (spec/stdio): Round 6 (human) fixes in 0bfe96d: report and pre-step-9 stderr writes bounded (poll ≤1 s, one write ≤ PIPE_BUF, drop + report-unwritten), report fd kinds restricted; gate moved to python3 -I (dash rejects fd >9; verified python gate on fd 17 under bwrap, dash fails); terminal recipe uses pipefail (verified bash and zsh keep exit 4). Verified POLLOUT leaves room for a PIPE_BUF write on pipes 4K-64K and socketpairs.
- 2026-10-15T12:27:16Z (spec/stdio): parked (waiting on user, review): User re-reviews the envelope amendment on spec/stdio (.worktrees/spec-stdio), round-6 fixes in 0bfe96d. On approval the agent marks the header approved, files the crew stop-path task and the sci-a1d45f note, merges spec/stdio, tasks done.
  provenance: {"harness_session":"claude-code:5012b356-782b-4ff4-b554-9cd759e28012","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-15T12:58:29Z (spec/stdio): resumed
  provenance: {"harness_session":"claude-code:5012b356-782b-4ff4-b554-9cd759e28012","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
