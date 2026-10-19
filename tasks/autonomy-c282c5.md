---
id: autonomy-c282c5
title: "Probe: prove the sandbox's network namespace differs from the orchestrator's"
status: todo
priority: 3
size: s
complexity: low
process: direct
created: 2026-10-17T19:00:18Z
updated: 2026-10-19T00:10:34Z
depends: []
tags: [sandbox]
agent: claude-code/claude-opus-5-5
---

Why: the runtime denial probe must distinguish the actor's network namespace from the orchestrator's even on an offline host. At 316c68b, build_argv always unshares the network, but the probe checks only connect outcomes. test_a_sandbox_sharing_the_host_network_fails_the_probe skips without an IPv4 default route. This is additional proof, not a demonstrated escape in the fixed launcher.

Done: capture the orchestrator's /proc/self/ns/net identity before spawning the trusted probe and compare it with the probe's identity inside bwrap. Refuse a shared namespace and missing or malformed identity evidence with a typed SandboxUnproven error. Keep the existing IPv4/IPv6 reachability and denied-path checks, including EAFNOSUPPORT on kernels without IPv6. Add deterministic same/different/malformed evidence tests, update mocked probe output, and make the real-bwrap --share-net negative independent of the host's default route. Update the envelope spec's probe description. Verify through just test-one tests/test_sandbox_probe.py, then just test-fast.

Where: python/src/autonomy/sandbox/bwrap.py (_PROBE, probe); python/tests/test_sandbox_probe.py (mocked stdout and the default-route skip); python/tests/test_sandbox_static.py; docs/specs/2026-10-12-envelope-design.md §3 step 7 and §7 probe. Check overlap with autonomy-6b1f9f's older probe-edge items; do not absorb its other sandbox changes. Evidence: autonomy-e4c0b5's attached sdd-ledger.md final Minor 3; current checkout 316c68b.

Captured idea (preserved):
The probe's network check expects ENETUNREACH to 192.0.2.1 and 2001:db8::1, which a host with no default route (or IPv4-only) also gives, so there it cannot tell a shared network from an unshared one; the suite skips the negative there. The static guarantee (build_argv never emits --share-net) holds, but the probe could also compare its /proc/self/ns/net inode with one the orchestrator passes in. From autonomy-e4c0b5's final review (Minor 3).
