---
id: autonomy-c0ac69
title: Point Pyright at python/.venv so editor diagnostics show real type errors
status: todo
priority: 4
size: xs
complexity: low
process: direct
created: 2026-10-15T15:44:10Z
updated: 2026-10-15T15:44:10Z
depends: []
tags: []
source: autonomy-641123
agent: claude-code/claude-opus-5-5
---

During Plan B1 the editor's Pyright reported every autonomy.* import and tests/channels helper as unresolved, which buries the real findings it also made (stdio.py's int-keyed enum dicts, a lost Literal). Add a [tool.pyright] venvPath/venv (and extraPaths for python/tests) to the project config so only genuine diagnostics remain.
