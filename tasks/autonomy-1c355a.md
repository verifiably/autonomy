---
id: autonomy-1c355a
title: "Egress tests: hang guards, fd and thread leaks, and accurate docstrings"
status: todo
priority: 3
size: s
complexity: low
process: direct
created: 2026-10-17T19:00:17Z
updated: 2026-10-17T19:00:17Z
depends: []
tags: [egress]
agent: claude-code/claude-opus-5-5
---

Deferred minors from autonomy-e4c0b5's reviews (ledger attached there). Hang guards: proxy process tests call blocking receive_message with no timeout and the suite has no pytest-timeout, so a regression hangs the pre-commit hook. Leaks: FakeUpstream listener/accept thread when stop() isn't called; make_served's records fd; unclosed pipes/socketpairs in test_egress_proxy; the failed-serve server test re-serves the fixture's server (orphaned listener, ~2.5 s teardown). Gaps: assert no live worker thread in the actor-hang-up test (Review Focus 3); credential-ownership test fails as root. Docs: Recorder's backfill status is usually, not always, null; upstream.py's close boundary is 'no request byte' (OpenSSL may write protocol records from recv); egress_live docstring's exit-0 condition is looser than verdict().
