---
id: autonomy-c9508e
title: "Proxy: make a cut response detectable to any HTTP client"
status: idea
priority: 2
reviewed: true
reviewed_at: 2026-10-19T00:11:47Z
created: 2026-10-17T19:00:17Z
updated: 2026-10-19T00:37:49Z
depends: [autonomy-9570b0]
parent: autonomy-3a06d3
tags: [egress]
agent: claude-code/claude-opus-5-5
---

Every proxied response is close-delimited, so a stream cut by an upstream error or run stop ends in a clean EOF that HTTP cannot tell from a complete response. pi detects it (no message_stop), but a harness reading a non-streaming body would take truncated JSON as complete. Idea: when a line ends other than `complete` after the head went out, close the actor socket with SO_LINGER {1,0} (RST). From autonomy-e4c0b5's final review (Minor 1).

## Notes

- 2026-10-19T00:11:47Z (main): scope: briefed; 316c68b confirms close-delimited actor responses and shutdown-before-close on both completion paths; reset behavior and its shutdown interaction remain unproven; brief: docs/notes/2026-10-18-egress-proof-gaps-brief.md; waits on autonomy-9570b0
- 2026-10-19T00:37:49Z (main): scope: brief revised after review; an abortive close must replace the FIN from both _release and close()'s survivor cut and win the stop path's cross-thread race, so the brief now leans to proxy-owned chunked framing; mechanism follows autonomy-9570b0
