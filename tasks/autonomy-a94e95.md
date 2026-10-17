---
id: autonomy-a94e95
title: "Establish whether an actor-side shared clone in scratch lets pi commit inside the envelope's sandbox with no shared git metadata writable, and how the host takes the branch without running actor-written git config or hooks"
status: todo
priority: 2
size: s
complexity: mid
process: direct
created: 2026-10-17T09:40:02Z
updated: 2026-10-17T09:40:02Z
depends: []
parent: autonomy-d9adef
tags: []
source: docs/notes/2026-10-15-authority-and-development-actors-brief.md
agent: claude-code/claude-opus-5-5
---

Question: Can a development actor (pi 1.1.0 over RPC, as in autonomy-c5c566) commit to a task branch in a `git clone --shared` made in scratch, with the main checkout's object store bound read-only and no other main-checkout git metadata bound? And by which route can the host then take that branch into the main repository without running any git config, hook or attribute the actor could write?

Where to start: autonomy-c5c566's attached probe.py and setup.sh (tasks/files/autonomy-c5c566/) and its result note, which found that a linked worktree needs objects, refs/heads and logs read-write to commit, which exposes every branch, and that Plan A's static check refuses binding main/.git while the main checkout is denied (bind-overlaps-denied); the brief docs/notes/2026-10-15-authority-and-development-actors-brief.md §2 and §5 question 2; envelope spec §2 decision 12 ("Harness state stays in scratch") and §7; python/src/autonomy/sandbox/ (SandboxSpec, build_argv, the static check).

Bound: A throwaway probe on a disposable repository, reusing c5c566's probe; no change to the sandbox module, the envelope spec, or crew. Network as in c5c566 (--share-net) and a cheap model. (1) The host makes the shared clone in scratch on the task branch; bind only the main object store, read-only, at the path its alternates name; send one RPC prompt that edits, commits twice, and tries `git push` to the main repository and `git update-ref refs/heads/main`; record what each does. (2) Compare host import routes, each run against a clone whose config the actor has set to run a marker command (core.fsmonitor, core.hooksPath, a post-checkout or reference-transaction hook, a filter in .gitattributes): plain `git fetch <scratch clone>`; fetch with the clone's .git/config and .git/hooks bound read-only from host-written copies; a host-built bare repository with its own config that reads the clone's objects directory and the one branch ref; a bundle the actor writes. Record which routes ran the marker. Check whether the static check accepts the object-store bind with the main checkout denied, and record its refusal if it does not.

Expected result: Record on this task and in the brief's §2: whether the shared clone commits with only the object store bound read-only; what the push and update-ref attempts did; each import route and whether it ran actor-controlled code; the route recommended for the development mode's closing step; and whether the static check needs a change to allow the bind.

Ideas it wakes: On completion, run `tasks note autonomy-d5c1cb --no-reviewed "<finding>"`, before this result's branch merges.
