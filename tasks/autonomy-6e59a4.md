---
id: autonomy-6e59a4
title: Plan B1 test and typing hygiene
status: todo
priority: 4
size: s
complexity: low
process: direct
created: 2026-10-15T15:37:57Z
updated: 2026-10-15T15:37:57Z
depends: []
tags: []
source: autonomy-641123
agent: claude-code/claude-opus-5-5
---

Deferred minors from Plan B1's task reviews and final review, none blocking.
- stdio.py: _FAMILIES/_TYPES are keyed by enum but looked up by int (annotate dict[int, str]); the generator unpack at check_stdio loses the StdioKind literal (return the three classify calls directly).
- channel.py and stdio.py both carry the /dev/null rdev and the kind classification; share one.
- cli.py: on Python 3.14 argparse colours help by stdout's tty status, so escape codes can reach the stderr pipe; pass color=False where supported.
- test_stdio.py: os.get_inheritable(fd) is False is vacuous.
- test_channel.py: test_a_blocking_write_hangs can pass vacuously on a loaded host (~4 s; fails on 64 KiB-page hosts); tests assert private attributes (_private == -1); the socket test never checks the caller's fd stays open after close().
- test_sandbox_launch.py / test_sandbox_probe.py: four plan-mandated tests assert dash/sh/head facts, not autonomy code; test_a_child_that_inherits_stdin_consumes_the_callers_bytes passes read_end explicitly; the stdio fixture opens three /dev/null fds where one serves.
- test_cli.py: unused dataclasses.field import.
- docs/specs/2026-10-12-envelope-design.md status line: the 'Item 4 stays open until B2 lands; it is split: …' splice reads awkwardly.
