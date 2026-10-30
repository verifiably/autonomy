---
id: autonomy-0df61e
title: Activate policy-off
status: done
priority: 2
size: xs
complexity: low
process: direct
owner: main
created: 2026-10-30T15:11:41Z
updated: 2026-10-30T22:58:26Z
started: 2026-10-30T17:38:06Z
completed: 2026-10-30T22:58:26Z
closed: 2026-10-30T22:58:26Z
depends: []
parent: autonomy-23aeff
tags: []
model: claude-opus-5-5
agent: claude-code/claude-opus-5-5
plan: docs/plans/2026-10-30-test-execution-policy.md
step: "Task 5: Activate policy-off"
---

## Notes

- 2026-10-30T15:11:41Z (add): created
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T17:38:06Z (main): started
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T18:00:52Z (main): parked (waiting on user, approval): User approves packet C (push local main, incl. another session's ops-check v16 commit 0ab3671); then the agent rechecks the tasks-only diff, pushes main, and verifies main's hosted run (1395/1395).
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T18:08:22Z (main): resumed
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T18:15:21Z (main): parked (waiting on user, decision): User decides on main's failed run 41104200861 (e21 lease timeout, autonomy-1ba43a): keep policy off and approve a diagnostic hosted run, or roll back. Then the agent acts on that decision.
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T22:58:25Z (main): resumed
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T22:58:26Z (main): done
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-30T22:58:26Z (main): Policy-off landed: .tt.toml in main merge b6fdc72 (disabled note recorded); hosted run 41101402802 1395/1395 on the policy-off head; main pushed 3c5f272 then 3b281bd after the e21 fix; main run 41141028249 1398/1398
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
