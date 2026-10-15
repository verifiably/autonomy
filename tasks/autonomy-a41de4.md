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
updated: 2026-10-15T11:36:13Z
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
