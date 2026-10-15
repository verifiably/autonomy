---
id: autonomy-c5c566
title: "Establish whether pi over RPC runs inside the envelope's sandbox with its stdio held by the caller, and what it must have bound"
status: todo
priority: 2
size: s
complexity: mid
process: direct
created: 2026-10-15T10:39:25Z
updated: 2026-10-15T10:39:25Z
depends: []
parent: autonomy-d9adef
tags: []
source: docs/notes/2026-10-15-authority-and-development-actors-brief.md
agent: claude-code/claude-opus-5-5
---

Question: Can a caller outside the sandbox drive `pi --mode rpc` (pi 1.1.0 through hq's launcher) running under Plan A's bwrap sandbox, with the actor's stdin and stdout passed through rather than reopened on /dev/null, and which binds, network mode and environment does pi need there (node and the pi install, the agent directory, the model credential, the worktree as scratch)?

Where to start: python/src/autonomy/sandbox/bwrap.py (`_GATE` reopens stdin on /dev/null after reading the release line; `launch` passes the gate pipe as stdin); envelope spec §7 (sandbox spec, argv, what the actor is given); crew src/scopes.ts and src/runtime/pi-rpc.ts (crew spawns pi with piped stdio and speaks RPC over it); hq's pi launcher and pi/package.json; the brief at docs/notes/2026-10-15-authority-and-development-actors-brief.md.

Bound: A throwaway probe, not a change to the sandbox module: copy the launch with the gate's release moved to a dedicated fd and the caller's pipes passed to the actor, run one RPC prompt and one abort against a cheap model in a scratch git worktree with --share-net, and list every bind pi needed and whether the credential was readable inside. No envelope spec edit, no Plan B work, no crew change. If unprivileged user namespaces or bwrap are unavailable on the host, record that and stop.

Expected result: Record on this task and in the brief's §2: whether RPC over passed-through stdio works across bwrap --new-session --unshare-all; the bind list and environment pi needed; whether the model credential is inside the trajectory; a recommendation among the brief's stdio alternatives (pass-through, socket in scratch, pi-durable in process) for autonomy-641123.

Ideas it wakes: On completion, run `tasks note autonomy-d5c1cb --no-reviewed "<finding>"`, before this result's branch merges.
