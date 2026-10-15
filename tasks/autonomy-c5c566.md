---
id: autonomy-c5c566
title: "Establish whether pi over RPC can work in a linked worktree inside the envelope's sandbox with its stdio held by the caller, and what it must have bound"
status: doing
priority: 2
size: s
complexity: mid
process: direct
owner: probe/pi-sandbox
created: 2026-10-15T10:39:25Z
updated: 2026-10-15T11:23:23Z
started: 2026-10-15T11:00:20Z
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

## Notes

- 2026-10-15T11:00:20Z (main): started
  provenance: {"harness_session":"claude-code:bc6b520d-859e-4019-8e86-348c5b5c5b51","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-15T11:00:35Z (probe/pi-sandbox): resumed
  provenance: {"harness_session":"claude-code:bc6b520d-859e-4019-8e86-348c5b5c5b51","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-15T11:23:21Z (probe/pi-sandbox): attached: probe.py (8345 bytes): The probe as run: Plan A's spec, build_argv and prove, gate on its own fd, pi RPC over passed-through stdio; runs bare, gitmeta, gitcommit
- 2026-10-15T11:23:22Z (probe/pi-sandbox): attached: setup.sh (678 bytes): Builds a probe root: main checkout, linked worktree under scratch, agent dir with auth.json from ANTHROPIC_API_KEY
- 2026-10-15T11:23:22Z (probe/pi-sandbox): result: pi 1.1.0 RPC over passed-through stdio works inside Plan A's bwrap sandbox (get_state 0.6 s; six-step prompt settled 15-39 s; abort settled 0.01-0.03 s, aborted true; stdin close -> exit 0; three runs about US$0.005, claude-haiku-5-5). Binds: node and pi installs ro; agent dir rw (pi locks auth.json by mkdir auth.json.lock -> EROFS on every prompt when ro; it also writes models-store.json); scratch with worktree, sessions and HOME. Actor cwd must be set to the worktree separately from --chdir scratch. Linked worktree: git unusable without metadata; main .git ro + admin dir rw gives status/log/rev-parse, add fails; + objects, refs/heads, logs rw gives commit but exposes every branch including main (one ref cannot be bound alone); Plan A's static check refuses main/.git while main is denied. Credential: readable inside (153-byte auth.json read by a shell in the same sandbox); absent from session files, RPC records, stdout, stderr, models-store.json (47 files per run). Recommendation for autonomy-a41de4: pass-through, with the gate on its own fd, no autonomy output on the actor's stdout, a separate actor cwd, and extra rw binds under the static check. Details: brief §2 (cc15489).
