---
id: autonomy-704202
title: "Egress proxy control loop: close stray fds, refuse a second listener, survive a bad message, expire leases strictly"
status: todo
priority: 3
size: s
complexity: mid
process: direct
created: 2026-10-17T19:00:16Z
updated: 2026-10-17T19:00:16Z
depends: []
tags: [egress]
agent: claude-code/claude-opus-5-5
---

Deferred minors from autonomy-e4c0b5's Task 8 review (ledger attached there). In proxy.py: fds carried by renew/close/route messages leak (only unknown ops close them); a second `listener` message is accepted and orphans the first listener and its accept thread; invalid JSON, a non-object message, bad base64 or a missing `lease` crash main with no `closed` line; a `renew` arriving at the deadline can extend a just-expired lease (re-check after select). Received-fd CLOEXEC is B2's (noted on autonomy-f6efe8).
