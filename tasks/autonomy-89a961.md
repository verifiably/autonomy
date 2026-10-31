---
id: autonomy-89a961
title: "Analyst launch: the 13 minors deferred by the final review (release labels and hygiene, walk transients, toolchain nesting, judge param, test skips)"
status: todo
priority: 3
size: s
complexity: low
process: direct
created: 2026-10-31T23:47:58Z
updated: 2026-10-31T23:47:58Z
depends: []
tags: [sandbox]
source: autonomy-2e2519
agent: claude-code/claude-fable-5-1
origin: agent
---

Outcome: the deferred minors from autonomy-2e2519's three review rounds are fixed or explicitly declined, each with a test where behaviour changes.

The list, with reasoning, is in autonomy-2e2519's attachment analyst-launch-ledger.md (every 'minor (deferred)' line). In short: walk.py: an entry deleted between scandir and stat escapes as a raw OSError (skip in walk_tree, denied-unreadable in collect_denied_inodes); launch.py: nesting refused only when an input is involved (refuse any pair of admitted trees); launch.py: a ProxySurvived from the finally's session.kill() is swallowed silently (log it); release.py: ENOTDIR/post-open mismatch labelled symlink (a swapped reason), a top-level outputs/ that opens but cannot be listed reported unopenable not outputs-unusable, an empty directory left in the release when its destination open or listing fails, uncaught os.fstat/os.close/destination-open OSErrors reachable only from the host environment, child pair leak on a non-OSError from _names before frames.append; tests: judge's unused release_dir parameter, the chmod-000 case lacks the uid-0 skip, the supervision test's del sessions[:] only on success.

Keep the release's reason list closed unless a new reason is justified; decision 14 and docs/plans/2026-10-31-analyst-launch.md are the references.

## Notes

- 2026-10-31T23:47:58Z (add): created
  provenance: {"harness_session":"claude-code:fc4eb4dd-05c5-441e-9e3b-34ef5c547637","harness_session_source":"CLAUDE_CODE_SESSION_ID","origin":"agent"}
