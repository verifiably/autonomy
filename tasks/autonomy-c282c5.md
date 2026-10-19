---
id: autonomy-c282c5
title: "Launch: prove the actor's network namespace differs from the orchestrator's"
status: todo
priority: 3
size: s
complexity: low
process: direct
created: 2026-10-17T19:00:18Z
updated: 2026-10-19T00:38:06Z
depends: []
parent: autonomy-3a06d3
tags: [sandbox]
agent: claude-code/claude-opus-5-5
---

Why: the runtime proof must distinguish the actor's network namespace from the orchestrator's even on an offline host. At 316c68b, build_argv always unshares the network, but the probe checks only connect outcomes, test_a_sandbox_sharing_the_host_network_fails_the_probe skips without an IPv4 default route, and the probe is a separate bwrap run from the actor's launch. This is additional proof, not a demonstrated escape in the fixed launcher.

Done: inside sandbox/bwrap.py::launch, after the pidfd on the namespace's init is held and before the release (where before_release runs), compare the orchestrator's /proc/self/ns/net identity (st_dev and st_ino) with /proc/<child-pid>/ns/net, then confirm the pidfd is still live so a reused pid cannot answer. Refuse a shared namespace and missing or unreadable identity evidence with a typed SandboxUnproven error through the existing abort path, so the actor never runs. The check is unconditional, not a before_release callback a caller could omit. Keep the probe's IPv4/IPv6 reachability and denied-path checks, including EAFNOSUPPORT on kernels without IPv6. Add deterministic same/different/unreadable tests and a real-bwrap --share-net negative (test hook on launch's argv) that fails regardless of the host's default route. Update the envelope spec. Verify through just test-one on the launch and probe tests, then just test-fast.

Where: python/src/autonomy/sandbox/bwrap.py (launch, _abort, probe); python/tests/test_sandbox_launch.py and test_sandbox_probe.py (the default-route skip); docs/specs/2026-10-12-envelope-design.md decision 8, §3 step 7, the probe and launch sections, and E21's shared-network negative. A 2026-10-18 check on this host: the parent could stat /proc/<child-pid>/ns/net of a bwrap --unshare-all child and saw a different device:inode; bwrap's --info-fd report also carries net-namespace. Check overlap with autonomy-6b1f9f's older probe-edge items; do not absorb its other sandbox changes. Evidence: autonomy-e4c0b5's attached sdd-ledger.md final Minor 3; docs/notes/2026-10-18-egress-proof-gaps-brief.md.

Captured idea (preserved):
The probe's network check expects ENETUNREACH to 192.0.2.1 and 2001:db8::1, which a host with no default route (or IPv4-only) also gives, so there it cannot tell a shared network from an unshared one; the suite skips the negative there. The static guarantee (build_argv never emits --share-net) holds, but the probe could also compare its /proc/self/ns/net inode with one the orchestrator passes in. From autonomy-e4c0b5's final review (Minor 3).

## Notes

- 2026-10-19T00:10:35Z (main): scope: scoped; 316c68b confirms the runtime probe checks only connect outcomes and the shared-net negative skips without an IPv4 default route; defined namespace-identity proof, strict evidence failures and route-independent checks; priority 3, size s, complexity low, process direct; no sandbox escape demonstrated
- 2026-10-19T00:38:05Z (main): scope: rescoped after brief review; the identity check moves from the probe to launch before release, so it proves the actor's own namespace; compare device and inode, confirm the pidfd is live after the stat; parent stat of /proc/<child-pid>/ns/net confirmed on this host
