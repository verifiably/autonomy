---
id: autonomy-c5b5cb
title: Find what makes the first sandboxed filesystem sweep slow on GitHub's runner
status: todo
priority: 3
size: s
complexity: mid
process: direct
created: 2026-10-30T23:42:57Z
updated: 2026-10-30T23:42:57Z
depends: []
tags: [egress]
source: autonomy-1ba43a
agent: claude-code/claude-opus-5-5
origin: agent
---

On GitHub's ubuntu-24.04 runner the actor's full sweep (os.walk of / skipping /proc, /sys, /dev and /usr, reading up to 4 MiB per file, then /proc/*/environ and cmdline) took 12.39 s and 12.94 s as the job's first sweep (runs 41112785423, 41120536343) and 0.11-0.17 s afterwards; locally it takes about 0.05 s. e21 now tolerates it through lease renewal (autonomy-1ba43a), but it adds about 11 s to every hosted run (e21 11.32 s in run 41141028249), and why it is slow, or what consumed 30 s in run 41104200861, is unknown. Profile the sweep per top-level directory (files, bytes, seconds) on one approved hosted run; then decide whether anything should change. The user deferred this profiling on 2026-10-30 because the fix tolerates cold or warm reads; it needs a hosted run, which needs approval.

## Notes

- 2026-10-30T23:42:57Z (add): created
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID","origin":"agent"}
