---
id: autonomy-30c717
title: Restore raw suite attachments when hosted tasks supports eligibility queries
status: todo
priority: 3
size: xs
complexity: low
process: direct
created: 2026-10-31T00:05:21Z
updated: 2026-10-31T00:05:35Z
depends: []
tags: []
source: autonomy-e51da5
agent: codex
origin: agent
---

Own the retained raw suite logs and portable derivatives under $WORK_ROOT/autonomy/autonomy-23aeff/portable-log-repair-e51da5. Keep the only required raw copies while CI pins a tasks CLI without attachments support. After a published compatible CLI is pinned and the executing checker accepts raw ledger-backed attachments normally, verify recorded hashes, reattach the exact raw logs to autonomy-23aeff, run normal hygiene and obtain approval for any push; reassess each off-tree copy before disposition. Portable derivative mapping remains on autonomy-23aeff. The published-tool mismatch is reported in ops-c2263c.

## Notes

- 2026-10-31T00:05:21Z (add): created
  provenance: {"harness_session":"codex:01a18f3b-625c-7fe1-a950-48b95107ec84","harness_session_source":"CODEX_THREAD_ID","origin":"agent"}
- 2026-10-31T00:05:35Z (main): retained: {"host": "titan", "kind": "evidence", "path": "$WORK_ROOT/autonomy/autonomy-23aeff/portable-log-repair-e51da5/local-suite-f71c605.log", "state": "kept", "verification": "verified", "purpose": "Exact raw suite evidence underlying the portable attachment on autonomy-23aeff", "next_owner": "task:autonomy-30c717", "cleanup_trigger": "After a published compatible tasks CLI is pinned and the executing checker accepts raw attachments normally, verify preservation and reassess each copy; no deletion is authorized by task closure", "sha256": "8a081b5ad21d9b4208553cc15ef3c7050daf06fac30919d964a046a7e33bb228"}
