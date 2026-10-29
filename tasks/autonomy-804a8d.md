---
id: autonomy-804a8d
title: Verify the closed Messages policy with the existing live pi smoke test
status: todo
priority: 3
size: xs
complexity: low
process: direct
created: 2026-10-29T10:24:10Z
updated: 2026-10-29T10:24:10Z
depends: [autonomy-58799c]
parent: autonomy-3a06d3
tags: [egress]
source: autonomy-58799c
agent: codex
origin: agent
---

Why: the closed Messages policy is implemented and independently reviewed, with offline pi 1.1.0 / SDK 0.129.0 captures and fake-upstream tests. The earlier live pi proof in autonomy-e4c0b5 predates the stricter body checks. Confirm that the admitted plain request still works through the complete live path; this is additional compatibility evidence, not a discovered enforcement defect. Done: after explicit approval of the paid API call, route, model and spend limit at execution time, run the existing just live-egress recipe on the current code. Record the code/SDK/pi versions, request and stream verdicts, normal final assistant message, coded refusals if any, clean route close and redacted evidence with credentials excluded. Report this one exercised path without claiming live coverage of every supported optional feature. Where: python/scripts/egress_live.py, justfile live-egress, README model route and decision 13. The existing helper sends one plain prompt with thinking off; do not silently claim it tests effort mode. Do not widen the policy or modify production code merely to make the live call pass; a genuine mismatch needs a separately recorded defect or reviewed contract decision. No API call, credential access, deployment or desktop use is authorized by filing this task.

## Notes

- 2026-10-29T10:24:10Z (add): created
  provenance: {"harness_session":"codex:01a186e7-b040-7ec0-b7e3-b46b220e04a6","harness_session_source":"CODEX_THREAD_ID","origin":"agent"}
