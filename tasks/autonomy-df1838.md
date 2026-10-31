---
id: autonomy-df1838
title: Run row E24 in the hosted workflow by installing the pinned pi from hq's lock
status: idea
priority: 2
created: 2026-10-31T23:48:03Z
updated: 2026-10-31T23:48:03Z
depends: []
tags: []
source: autonomy-2e2519
agent: claude-code/claude-fable-5-1
origin: agent
---

Row E24's evidence is a local run attached to its task because the hosted workflow has neither pi nor node. The pinned install is hq's pi/package.json + package-lock.json (npm ci), and node is available on GitHub runners; the job would also need rg and fd from apt and the AppArmor userns sysctl the workflow already lifts. Cross-repository: the lock lives in hq, so the job must fetch it or hq must publish it. Decide whether the paid-free check belongs in CI at all, or whether the attached local run per epoch is enough.

## Notes

- 2026-10-31T23:48:03Z (add): created
  provenance: {"harness_session":"claude-code:fc4eb4dd-05c5-441e-9e3b-34ef5c547637","harness_session_source":"CLAUDE_CODE_SESSION_ID","origin":"agent"}
