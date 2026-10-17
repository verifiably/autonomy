---
id: autonomy-c9508e
title: "Proxy: end a cut response abortively so any client sees an error"
status: idea
priority: 2
created: 2026-10-17T19:00:17Z
updated: 2026-10-17T19:00:17Z
depends: []
tags: [egress]
agent: claude-code/claude-opus-5-5
---

Every proxied response is close-delimited, so a stream cut by an upstream error or run stop ends in a clean EOF that HTTP cannot tell from a complete response. pi detects it (no message_stop), but a harness reading a non-streaming body would take truncated JSON as complete. Idea: when a line ends other than `complete` after the head went out, close the actor socket with SO_LINGER {1,0} (RST). From autonomy-e4c0b5's final review (Minor 1).
