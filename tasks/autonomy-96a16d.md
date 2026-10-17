---
id: autonomy-96a16d
title: "Egress route parsing: refuse port 0, case-variant header_tokens keys, and a non-host upstream"
status: todo
priority: 3
size: xs
complexity: low
process: direct
created: 2026-10-17T19:00:16Z
updated: 2026-10-17T19:00:16Z
depends: []
tags: [egress]
agent: claude-code/claude-opus-5-5
---

Deferred minors from autonomy-e4c0b5's Task 2 review (ledger attached there). In route.py: `port or 443` turns an explicit `:0` into 443 (use `443 if port is None` and refuse 0); header_tokens keys are lowercased, so `Anthropic-Beta` and `anthropic-beta` silently overwrite each other (refuse the duplicate); the upstream hostname is not checked as a DNS name or IP (CRLF is already impossible). Each with a test in test_egress_route.py.
