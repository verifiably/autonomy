---
id: autonomy-413763
title: Guard socket.socket(fileno=dup) in stdio and channel against a process-wide default timeout
status: todo
priority: 2
size: xs
complexity: low
process: direct
created: 2026-10-15T15:37:56Z
updated: 2026-10-15T15:39:32Z
depends: []
tags: []
source: autonomy-641123
agent: claude-code/claude-opus-5-5
---

Plan B1 final review. CPython's socket constructor sets O_NONBLOCK on the open file description when socket.getdefaulttimeout() is not None, and the description is shared with the caller's (and the actor's) fd. stdio._socket_kind and LineChannel.__init__ both wrap a dup this way. Nothing sets a default timeout today, but B2 adds socket clients (control socket, endpoint). Refuse (or assert) when socket.getdefaulttimeout() is not None, with a test that sets one. Land before B2 adds socket code.

## Notes

- 2026-10-15T15:39:32Z (plan-b1): also fold in: LineChannel and stdio._socket_kind os.dup before try leaks the dup if socket(fileno=) raises
