---
id: autonomy-413763
title: Guard socket.socket(fileno=dup) in stdio and channel against a process-wide default timeout
status: doing
priority: 2
size: xs
complexity: low
process: direct
owner: crew
created: 2026-10-15T15:37:56Z
updated: 2026-10-17T11:31:08Z
started: 2026-10-17T11:22:34Z
depends: []
tags: []
source: autonomy-641123
agent: claude-code/claude-opus-5-5
---

Plan B1 final review. CPython's socket constructor sets O_NONBLOCK on the open file description when socket.getdefaulttimeout() is not None, and the description is shared with the caller's (and the actor's) fd. stdio._socket_kind and LineChannel.__init__ both wrap a dup this way. Nothing sets a default timeout today, but B2 adds socket clients (control socket, endpoint). Refuse (or assert) when socket.getdefaulttimeout() is not None, with a test that sets one. Land before B2 adds socket code.

## Notes

- 2026-10-15T15:39:32Z (plan-b1): also fold in: LineChannel and stdio._socket_kind os.dup before try leaks the dup if socket(fileno=) raises
- 2026-10-17T11:22:34Z (crew): started
- 2026-10-17T11:22:59Z (crew): crew: attempt 01M54SJV6BZ79QNN3MMA04269C started — kind code-xs, worker openrouter/anthropic/claude-sonnet-5.5, worktree .worktrees/crew-ma04269c
- 2026-10-17T11:24:07Z (crew): crew: attempt 01M54SJV6BZ79QNN3MMA04269C — verdict passed (worker openrouter/anthropic/claude-sonnet-5.5, reviewer openrouter/openai/gpt-6.1-sol); report /home/keith/.local/state/crew/attempts/01M54SJV6BZ79QNN3MMA04269C/attempt-report.md
- 2026-10-17T11:24:08Z (crew): parked (waiting on user, review): review crew attempt 01M54SJV6BZ79QNN3MMA04269C (verdict passed): branch crew/autonomy-413763-ma04269c in .worktrees/crew-ma04269c; merge and close, or discard
- 2026-10-17T11:24:55Z (crew): resumed
- 2026-10-17T11:25:26Z (crew): crew: attempt 01M54SQ3PVMN9QX1MCVX4PVDJ5 started — kind code-xs, worker openrouter/z-ai/glm-5.3-flash, worktree .worktrees/crew-vx4pvdj5
- 2026-10-17T11:30:27Z (crew): crew: attempt 01M54SQ3PVMN9QX1MCVX4PVDJ5 — verdict passed (worker openrouter/z-ai/glm-5.3-flash, reviewer openrouter/openai/gpt-6.1-sol); report /home/keith/.local/state/crew/attempts/01M54SQ3PVMN9QX1MCVX4PVDJ5/attempt-report.md
- 2026-10-17T11:30:28Z (crew): parked (waiting on user, review): review crew attempt 01M54SQ3PVMN9QX1MCVX4PVDJ5 (verdict passed): branch crew/autonomy-413763-vx4pvdj5 in .worktrees/crew-vx4pvdj5; merge and close, or discard
- 2026-10-17T11:31:08Z (crew): resumed
