---
id: autonomy-24c056
title: Close the last narrow windows in autonomy run's failure paths
status: todo
priority: 4
size: xs
complexity: low
process: direct
created: 2026-10-15T15:44:09Z
updated: 2026-10-15T15:44:09Z
depends: []
tags: []
source: autonomy-641123
agent: claude-code/claude-opus-5-5
---

From Plan B1's final fix re-review, each needing a narrow race:
- cli.py: diag.close() in main's finally, and the diagnostic in _unexpected before its own try, sit outside the last-resort guard; an os.close error or a second SIGINT there still reaches the default excepthook.
- run.py allocate: a KeyboardInterrupt between path.mkdir and made.append(path) leaks that directory while the run reports exit 2; a failed rollback rmdir likewise leaves one (and reports failed:, not allocation-failed).
- A newline in an XDG path splits the 'run … in <run_dir>' and _unexpected diagnostics across two lines; escape it.
