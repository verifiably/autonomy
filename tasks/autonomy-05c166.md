---
id: autonomy-05c166
title: "live-egress smoke script: take an explicit thinking level validated against pi's registry instead of hardcoded '--thinking off'"
status: todo
priority: 3
size: xs
complexity: low
process: direct
created: 2026-11-01T16:40:18Z
updated: 2026-11-01T16:40:20Z
depends: []
tags: [egress]
source: autonomy-d0fce7
agent: agy
origin: mixed
---

Outcome: just live-egress and python/scripts/egress_live.py pass an explicit, registry-validated --thinking level to pi rather than hardcoding '--thinking off', so live smoke evidence states truthfully whether it exercised plain thinking-off or adaptive effort mode.

Why: python/scripts/egress_live.py:48,129 defaults model to claude-haiku-5-5 (justfile:111) and passes '--thinking off'. As established in autonomy-d0fce7 (and set aside as out of scope in its round 1 review), pi 1.1.0 maps off to null on claude-haiku-5-5, clamps '--thinking off' to low, and sends adaptive thinking plus mid-conversation output_config={'effort': 'low'} and PI_1_1_0_BETAS — contradicting autonomy-804a8d's assumption that egress_live.py sends one plain prompt with thinking off rather than effort mode.

Done: egress_live.py and just live-egress take an explicit thinking level, validate (pi_dir, model, thinking) via check_pi and check_thinking before starting the sandbox and proxy, record model and thinking in the printed summary, and have offline unit coverage in python/tests/test_egress_live.py; no paid live API call is authorized by filing this task.

## Notes

- 2026-11-01T16:40:18Z (add): created
  provenance: {"origin":"mixed"}
- 2026-11-01T16:40:20Z (main): concerns: autonomy-d0fce7 extension — apply explicit thinking validation to E21's live-egress helper (out of autonomy-d0fce7's analyst scope; clarifies autonomy-804a8d)
