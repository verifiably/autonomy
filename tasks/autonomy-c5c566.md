---
id: autonomy-c5c566
title: "Establish whether pi over RPC can work in a linked worktree inside the envelope's sandbox with its stdio held by the caller, and what it must have bound"
status: todo
priority: 2
size: s
complexity: mid
process: direct
created: 2026-10-15T10:39:25Z
updated: 2026-10-15T10:51:30Z
depends: []
parent: autonomy-d9adef
tags: []
source: docs/notes/2026-10-15-authority-and-development-actors-brief.md
agent: claude-code/claude-opus-5-5
---

Question: Can a caller outside the sandbox drive `pi --mode rpc` (pi 1.1.0 through hq's launcher) running under Plan A's bwrap sandbox, with the actor's stdin and stdout passed through rather than reopened on /dev/null? Can pi do development work there, in a linked git worktree bound as scratch, whose `.git` file points at metadata in the main checkout outside the bind? Which binds, network mode and environment does it need?

Where to start: python/src/autonomy/sandbox/bwrap.py (`_GATE` reopens stdin on /dev/null after reading the release line; `launch` passes the gate pipe as stdin); envelope spec §7 (sandbox spec, argv, what the actor is given); crew src/scopes.ts and src/runtime/pi-rpc.ts (crew spawns pi with piped stdio and speaks RPC over it); hq's pi launcher and pi/package.json; the brief at docs/notes/2026-10-15-authority-and-development-actors-brief.md.

Bound: A throwaway probe, not a change to the sandbox module. Copy the launch with the gate's release moved to a dedicated fd and the caller's pipes passed to the actor. Use --share-net and a cheap model. Make a disposable linked worktree the scratch. Send one RPC prompt that has pi run `git status` and `git log -1` and make one disposable edit, then send one abort. Run it twice: once without the main checkout's git metadata bound (record what git reports), and once with the worktree's admin directory and the shared object store bound, the shared parts read-only if git tolerates it. No envelope spec edit, no Plan B work, no crew change. If unprivileged user namespaces or bwrap are unavailable on the host, record that and stop.

Expected result: Record on this task and in the brief's §2:
- whether RPC over passed-through stdio works across bwrap --new-session --unshare-all;
- whether git works in the linked worktree, and the smallest metadata binds that let it, with what each bind would let the actor change (refs, config, hooks);
- the bind list and environment pi needed;
- credential readability, recorded separately from credential appearance: whether the model credential is readable from inside the sandbox, and, separately, whether it appears in pi's session files, RPC events, stdout or stderr;
- a recommendation among the brief's stdio alternatives (pass-through, socket in scratch, pi-durable in process) for autonomy-a41de4.

Ideas it wakes: On completion, run `tasks note autonomy-d5c1cb --no-reviewed "<finding>"`, before this result's branch merges. autonomy-a41de4 depends on this task and needs no note.
