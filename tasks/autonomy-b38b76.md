---
id: autonomy-b38b76
title: "Sandbox host links: deferred review minors from the layout fix"
status: todo
priority: 3
size: s
complexity: low
process: direct
created: 2026-10-30T16:50:50Z
updated: 2026-10-30T16:52:38Z
depends: []
tags: [sandbox]
source: autonomy-7f4bc7
agent: claude-code/claude-opus-5-5
origin: agent
---

Deferred minors from autonomy-7f4bc7's impl review round 1 (claude-code/claude-opus-5-5). (2) Links are re-read from the host at every argv build (preflight, probe build_argv, launch build_argv, proxy_argv), so the probed sandbox is not guaranteed to be the launched one, and nothing records the links a run used: resolve once at prove or spec construction, carry them in SandboxSpec and ProxyBinds, and write them into the probe event or baseline. (3) An os.readlink OSError in system_symlinks (link swapped after is_symlink) escapes untyped from preflight: map it to SandboxUnproven layout-unsupported. (4) system_symlinks resolves targets against '/' rather than the link's own directory; correct only while every SYSTEM_LINKS entry is top-level. (5) No test pins that preflight()/prove() use system_symlinks (a fixed-table regression there passes on Arch); no case for an absolute /usr target (accepted) or a target of exactly usr (refused). (6) Envelope design's read-only system binds clause (docs/specs/2026-10-12-envelope-design.md, near line 1392) should say the link targets mirror the host, absent links are left out, and anything not under /usr is layout-unsupported. (7) Duplicate 'from autonomy.sandbox.static import' lines in python/src/autonomy/egress/session.py.

## Notes

- 2026-10-30T16:50:50Z (add): created
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID","origin":"agent"}
- 2026-10-30T16:52:38Z (main): Also from autonomy-7f4bc7 round 2: test import order in test_egress_session.py; the layout-refusal test could assert egress.jsonl and proxy.log are not created; the layout check runs at step 9 (start), not step 7 (check_proxy).
