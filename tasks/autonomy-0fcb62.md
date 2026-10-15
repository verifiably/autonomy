---
id: autonomy-0fcb62
title: "Create autonomy's state, cache and runtime parent directories 0700 and check an existing $XDG_RUNTIME_DIR/va's owner and mode"
status: todo
priority: 3
size: s
complexity: mid
process: direct
created: 2026-10-15T15:37:57Z
updated: 2026-10-15T15:37:57Z
depends: []
tags: []
source: autonomy-641123
agent: claude-code/claude-opus-5-5
---

Plan B1 final review. allocate's mkdir(parents=True) leaves <state>/verifiably-autonomy and <cache>/verifiably-autonomy (and their parents) at the umask, typically 0755, so run ids are listable by other local users; the run, scratch and socket directories themselves are 0700. A pre-existing $XDG_RUNTIME_DIR/va owned by another user (or wider than 0700) is accepted as is. Create the parents 0700 and refuse a va/ not owned by the caller or not 0700. Before B2 puts the endpoint socket there.
