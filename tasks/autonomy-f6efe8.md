---
id: autonomy-f6efe8
title: "Envelope Plan B2: science_reads, baseline, endpoint, run supervisor close path and run close/stop (rows E7–E12, E20 full-run arm)"
status: todo
priority: 2
size: l
complexity: high
process: planned
created: 2026-10-15T13:05:59Z
updated: 2026-10-15T13:06:00Z
depends: [beliefs-7a56ef, sci-a1d45f, autonomy-641123]
tags: []
agent: claude-code/claude-opus-5-5
---

Spec §13 item 4, second half: plan and build after the beliefs and science slices land (beliefs-7a56ef, sci-a1d45f). Builds on Plan B1 (autonomy-641123): science_reads (heads --resolve, log.v1), baseline.json/events.jsonl/seal.json, the endpoint launcher and control-socket client with heartbeat and seal, run steps 3–8 and the close path, autonomy run close and run stop, the wall-clock bound if B1 did not settle it; rows E7–E12 and E20's full-run arm. Consumes Plan A's tiers, ledger reader, closing check and sandbox.

## Notes

- 2026-10-15T13:05:59Z (main): concerns: none — split from autonomy-641123 before its plan was written (2026-10-15); the wall-clock bound note on 641123 applies here if B1 leaves it
