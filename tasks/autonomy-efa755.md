---
id: autonomy-efa755
title: "Amend the envelope spec with model-only egress and credential custody: a per-run trusted proxy is the actor's only network path and holds the provider credential"
status: doing
priority: 2
size: m
complexity: high
process: direct
owner: main
created: 2026-10-17T09:50:27Z
updated: 2026-10-17T10:10:06Z
started: 2026-10-17T09:59:00Z
depends: []
parent: autonomy-d9adef
tags: []
source: docs/notes/2026-10-15-authority-and-development-actors-brief.md
agent: claude-code/claude-opus-5-5
---

Why: an actor in autonomy run, science or development, needs the model API and nothing else on the network, and its provider credential must stay out of its reach. The envelope's network modes are `none` and `host` (spec §7; sandbox/spec.py), and neither confines a pi actor. autonomy-c5c566 found the credential readable inside the sandbox while pi holds it (brief §2). The spec deferred egress and credential custody to autonomy-9e8a43 (spec §1 "Out of scope", §2 decision 12 "Harness state stays in scratch"), which is blocked on science prerequisites unrelated to confinement. Decided by the user, 2026-10-17 (brief §5 question 4): one shared amendment that both the science run (autonomy-9e8a43) and the development mode (autonomy-d5c1cb) consume.

Bounds, from the user's decision:
- The actor reaches a trusted proxy, which permits only the configured model API operations. Arbitrary destinations and general forwarding are unavailable.
- The provider credential stays outside the actor's filesystem, environment and process. The proxy supplies it upstream.
- Proxy access belongs to one run and ends on stop, expiry or revocation. Missing enforcement fails closed: a run whose proxy cannot be established or proven does not start the actor.
- "Model endpoint only" is the required capability; its transport (a socket bound into scratch, a network namespace with one route, or another) is the design's choice and need not be a new SandboxSpec.network value.
- The amendment defines where a future allowance check joins the proxy (the point that decides whether another model call may start), without implementing budgeting. Allowance enforcement and accounting stay with autonomy-9e8a43.

Done: an amendment to docs/specs/2026-10-12-envelope-design.md, approved by the user, that: specifies the proxy, its lifetime per run (open, stop, lease expiry, revocation) and its fail-closed behaviour; states how pi is pointed at it (a provider base URL with a placeholder key, as pi's containerization guide describes; compare crew-799319, a policy-granted custom provider in the attempt's models.json) so no credential is in scratch, the environment or bwrap's argv; keeps explicit that this configuration only directs pi to the proxy, while the envelope and the proxy enforce the restriction even if the actor rewrites that configuration (user, 2026-10-17); replaces the credential template in decision 12 accordingly; marks the allowance join point; moves egress and credential custody out of the §1 deferral to autonomy-9e8a43; and names E-rows that demonstrate successful model streaming through the proxy, denied direct network access, denied destination overrides (another host, a Host header or absolute URL, CONNECT), and an unavailable credential (absent from the actor's filesystem, environment, /proc and the proxy socket's reachable responses). Implementation is filed from the approval (a Plan, or with Plan B2 autonomy-f6efe8), not done here.

Where: the brief docs/notes/2026-10-15-authority-and-development-actors-brief.md §2 (probe credential findings), §3, §5 question 4; envelope spec §1, §2 decision 12, §3 steps 1-9 and Close, §7, §8 (lease and kill), §12; python/src/autonomy/sandbox/ (spec.py network, bwrap.py launch); autonomy-c5c566's attached probe for a pi-in-sandbox harness.

## Notes

- 2026-10-17T09:59:00Z (main): Scope accepted by the user, 2026-10-17, including the credential-template replacement, the deferral move and crew-799319 as the way to configure pi; the design keeps configuration (directs pi) separate from enforcement (envelope and proxy, holding against an actor that rewrites its config). Amendment approval follows review of the drafted spec.
- 2026-10-17T09:59:00Z (main): started
  provenance: {"harness_session":"claude-code:8d3345f1-e50f-41b0-b5f0-0aedb418be65","harness_session_source":"CLAUDE_CODE_SESSION_ID"}
- 2026-10-17T10:09:56Z (main): Draft on spec/egress (30ccb3e, .worktrees/spec-egress): decision 13. Transport: TCP listener on 127.0.0.1:4780 inside the actor's own netns, made by a host-side helper that joins the netns's owning user ns (NS_GET_USERNS; joining the init's own nested user ns gives EPERM) and passes the fd to the proxy; no process inside the sandbox; checked locally (attached helper.py, host.py). Proxy sandboxed (--share-net, credential ro bind), exact method/path/query/model match, header allow-lists, no redirects, lease/EOF/SIGTERM/close, egress.jsonl; admit/settle join points for autonomy-9e8a43; host network mode removed; rows E21-E22; delivery item 5. pi facts used: TCP only, POST /v1/messages?beta=true, placeholder key OK, sk-ant-oat shape switches to Bearer.
- 2026-10-17T10:10:05Z (main): attached: helper.py (566 bytes): Namespace helper as checked 2026-10-17: joins the netns's owning user ns (NS_GET_USERNS), binds 127.0.0.1 there, returns the fd over SCM_RIGHTS
- 2026-10-17T10:10:05Z (main): attached: host.py (1861 bytes): Round trip: a bwrap --unshare-all actor GETs 127.0.0.1:8471 served by the host; direct connect ENETUNREACH; the host netns cannot reach the port
