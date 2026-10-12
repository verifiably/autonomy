---
id: autonomy-6b1f9f
title: "Envelope Plan A: deferred review minors (sandbox gate env and argv, interpreter pin, probe edges, ledger canonical JSON)"
status: todo
priority: 3
size: s
complexity: low
process: direct
created: 2026-10-12T15:48:46Z
updated: 2026-10-12T15:48:46Z
depends: []
tags: []
source: autonomy-250f4d
agent: claude-code/claude-opus-5-5
---

Deferred minors from Plan A's whole-branch review and its fix rounds (fresh reviewer, rounds 1–3). Each is small; none blocks Plan B, but the sandbox ones should land before the first unattended run (autonomy-9e8a43).

- python-preference "system" can still download a managed 3.14 lacking pidfds; "only-system" would fail at setup instead of at launch (fails closed either way).
- static.py docstring overstates alias detection; a bind mount of a corpus subdirectory elsewhere is invisible to inode ancestry (needs /proc/self/mountinfo).
- build_argv binds paths as given; spec §7 canonicalizes scratch, and relative or symlinked specs leave a check-then-bind window.
- probe with an empty denied set proves nothing and passes.
- ledger reader accepts non-canonical JSON (NaN, duplicate keys).
- launch race if bwrap is killed externally between its info and pidfd_open (pid reuse); poll after pidfd_open and catch BrokenPipeError on release.
- a missing denied path keeps no inode ancestry; an alias of its nearest existing ancestor is not caught by inode.
- select.select raises ValueError for fds ≥ 1024 in _read_info; use select.poll.
- _abort's process.wait() is unbounded; a bwrap in uninterruptible sleep moves the hang into the abort.
- preflight's TimeoutExpired path has no test.
- the sh gate (bash on this host) adds PWD and SHLVL to the actor's environment; spec §7 says the environment is the --setenv set (fix: exec env -u SHLVL -u PWD, plus an exact-environment test).
- `exec "$@"` reads a leading-dash actor argv[0] as an exec option; use `exec -- "$@"`.
- an empty actor argv makes the gate exit 0, so launch reports a clean run of nothing; refuse empty argv.
- on Python 3.11/3.12 Path.resolve(strict=False) raises RuntimeError on a denied-path symlink loop, which escapes untyped from _target (3.14 is typed).
- _abort could leak the pidfd and skip killing bwrap if pidfd_send_signal raised anything but ProcessLookupError (cannot happen for our own child today); try/finally would make it airtight.
