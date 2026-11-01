---
id: autonomy-375479
title: "Model-free confined command launch: run a pinned argv under analyst's namespace (inputs, denied set, walk, probe, no-follow release) with no model and no network route"
status: todo
priority: 2
size: m
complexity: high
process: planned
created: 2026-11-01T18:15:17Z
updated: 2026-11-01T18:15:17Z
depends: []
tags: [sandbox]
source: mm-62e2da
agent: claude-code/claude-opus-5-5
origin: agent
---

Outcome: a confined launch that runs one pinned argument vector with no model in the process tree and no network route, inside the same namespace construction `autonomy analyst` builds today: declared read-only inputs (`--input`), the denied set (`--deny`) with the static check, alias walk and probe before start, a no-follow release of declared outputs, and the launch record (epoch, walk/probe results, input and output digests, exit status). The command's stdout and stderr go to the run directory, never to a model.

Why: a consumer (multiple-myeloma's phase-2 protocol, Amendment 4 A4.2/A4.10, accepted 2026-11-01 at commit 42304d4 on branch mm-e8cf21-phase2-protocol) needs its live numerical computation confined from a private key while transmitting nothing to a model provider. Running the fixed command through a pi agent under `autonomy analyst` does not meet that: the agent's tools can read the staged inputs and return their values in tool results before any after-the-fact session check can reject the attempt. A launcher that refused every other tool call before execution and returned only a fixed status would also conform, but the agent adds nothing over a model-free runner.

Open design questions for autonomy: whether this is a mode of `autonomy analyst` (a `--command` in place of pi, no route bound) now, or waits for `autonomy run` with decision 14's declarations (autonomy-5a0929, blocked on Plan B2 autonomy-f6efe8); how decision 14's E23/E24 evidence extends to it (a no-network proof replacing the endpoint check); and what the launch record names for the command (argv digest, interpreter and bound environment paths).

Acceptance the consumer needs: the denied-set proof, walk and probe over the consumer's real denied paths; read-only declared inputs; no network namespace route (a connection attempt fails); a no-follow release report listing only declared outputs; the exit status and argv recorded.

## Notes

- 2026-11-01T18:15:17Z (add): created
  provenance: {"harness_session":"claude-code:d2f6936f-5a00-44ba-bd5b-50a8c3d96fff","harness_session_source":"CLAUDE_CODE_SESSION_ID","origin":"agent"}
