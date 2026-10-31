---
id: autonomy-0f7a78
title: "Analyst launch docs and fixture refresh for pi 1.1.0: README names the anthropic-beta tokens a live route needs and the host preconditions; PI_BETAS refreshed"
status: todo
priority: 2
size: s
complexity: low
process: direct
created: 2026-10-31T23:47:56Z
updated: 2026-10-31T23:47:56Z
depends: []
tags: [sandbox]
source: autonomy-2e2519
agent: claude-code/claude-fable-5-1
origin: agent
---

Outcome: an operator's first real 'autonomy analyst' launch does not close header-refused, and the README states the two host preconditions a reasonable operator hits first.

Why: pi 1.1.0 sends anthropic-beta tokens mid-conversation-output-config-2026-07-01, thinking-binding-controls-2026-08-01 and inline-tools-2026-09-15; the fixture route (tests/egress_fixtures.py PI_BETAS) and the README's model-route guidance predate them, so the E24 check had to add them on its own route (autonomy-2e2519 ledger ruling). Decision 13: a token alone grants no body capability, so listing them is safe.

Do: (1) README model-route section: name the tokens a live route for pi 1.1.0 must list in header_tokens, and point at the test's PI_1_1_0_BETAS; (2) README autonomy analyst section: host preconditions: no submount or btrfs subvolume boundary below /usr, /etc or an input (walk-submount), and a node prefix whose bin/ holds no rg or fd (toolchain-shadowed), with NODE_DIR as the way around a system node; (3) refresh PI_BETAS to pi 1.1.0's set and run the egress route/proxy tests; (4) optional, with the user's say-so since it costs a paid call: just live-egress against a real route updated with the tokens, to re-verify E21's live arm.

## Notes

- 2026-10-31T23:47:56Z (add): created
  provenance: {"harness_session":"claude-code:fc4eb4dd-05c5-441e-9e3b-34ef5c547637","harness_session_source":"CLAUDE_CODE_SESSION_ID","origin":"agent"}
