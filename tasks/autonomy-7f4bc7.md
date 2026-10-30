---
id: autonomy-7f4bc7
title: Sandbox system symlinks assume Arch's /lib64 layout; every binary fails to exec on Debian/Ubuntu hosts
status: doing
priority: 1
size: s
complexity: mid
process: direct
owner: fix/autonomy-7f4bc7-sandbox-layout
created: 2026-10-30T16:36:31Z
updated: 2026-10-30T16:48:27Z
started: 2026-10-30T16:37:17Z
depends: []
tags: [sandbox]
source: autonomy-23aeff
agent: claude-code/claude-opus-5-5
origin: agent
---

Observed 2026-10-30 in hosted run 41090873620 (verifiably/autonomy, ubuntu-24.04, AppArmor userns restriction lifted): bwrap now creates its namespaces, but every sandboxed exec fails 'execvp /usr/bin/true: No such file or directory' (preflight, probe, launch, egress listener). Root cause: python/src/autonomy/sandbox/spec.py SYSTEM_SYMLINKS fixes /lib64 -> usr/lib (Arch's merged-usr layout). On Ubuntu 24.04 /lib64 -> usr/lib64 and /usr/lib/ld-linux-x86-64.so.2 does not exist (confirmed in a local ubuntu:24.04 container: the loader is /usr/lib64/ld-linux-x86-64.so.2 -> ../lib/x86_64-linux-gnu/...), so the ELF interpreter /lib64/ld-linux-x86-64.so.2 is missing inside the sandbox. The envelope design (docs/specs/2026-10-12-envelope-design.md, read-only system binds) names the /bin, /lib, /lib64 and /sbin symlinks but not their targets. Fix in the sandbox: derive each link from the host (or refuse with a typed preflight error on a layout it cannot mirror), keep the static bind check covering whatever is bound, and add a regression test for a non-Arch layout. Blocks autonomy-23aeff's hosted pilot: the suite cannot pass on GitHub's Ubuntu runner until this lands; the adoption itself makes no production change.

## Notes

- 2026-10-30T16:36:31Z (add): created
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID","origin":"agent"}
- 2026-10-30T16:36:44Z (main): concerns: autonomy-422173 defect — SYSTEM_SYMLINKS hard-codes Arch's /lib64 -> usr/lib, so sandboxed binaries cannot exec on Debian/Ubuntu layouts
- 2026-10-30T16:37:17Z (fix/autonomy-7f4bc7-sandbox-layout): started
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T16:48:26Z (fix/autonomy-7f4bc7-sandbox-layout): review: impl round 1 — verdict: revise; findings: Minor 7; reviewer: claude-code/claude-opus-5-5
- 2026-10-30T16:48:27Z (fix/autonomy-7f4bc7-sandbox-layout): Ruling: review Minor 1 (layout error in EgressSession.start escapes as SandboxUnproven, leaks info_read and ours) re-graded Important per the reviewer's fix-before-merge call — design step 9 makes any proxy-start failure egress-unproven, and an untyped escape misreports the run — cost if wrong: one small extra fix. Minors 2-7 stay minor (deferred).
