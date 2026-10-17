---
id: autonomy-c282c5
title: "Probe: prove the sandbox's network namespace differs from the orchestrator's"
status: idea
priority: 2
created: 2026-10-17T19:00:18Z
updated: 2026-10-17T19:00:18Z
depends: []
tags: [sandbox]
agent: claude-code/claude-opus-5-5
---

The probe's network check expects ENETUNREACH to 192.0.2.1 and 2001:db8::1, which a host with no default route (or IPv4-only) also gives, so there it cannot tell a shared network from an unshared one; the suite skips the negative there. The static guarantee (build_argv never emits --share-net) holds, but the probe could also compare its /proc/self/ns/net inode with one the orchestrator passes in. From autonomy-e4c0b5's final review (Minor 3).
