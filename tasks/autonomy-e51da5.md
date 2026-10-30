---
id: autonomy-e51da5
title: "Main's hosted hygiene fails: two attachments carry host paths and the pinned tasks CLI cannot judge attachment eligibility"
status: doing
priority: 1
size: xs
complexity: low
process: direct
owner: main
created: 2026-10-30T23:45:24Z
updated: 2026-10-30T23:55:38Z
started: 2026-10-30T23:53:56Z
depends: []
tags: [gates]
source: autonomy-23aeff
agent: claude-code/claude-opus-5-5
origin: agent
---

Hosted run 41145953343 (main a35145d, task-record commits only; code identical to 3b281bd, which passed) failed at Hygiene: 'ops-check: attachment eligibility ... tasks exited 2; install a tasks build with attachments'. ops-check v16 (vendored in 0ab3671) calls 'tasks attachments' only when an attachment holds host-layout values; the workflow's pinned public tasks 43b6eee (khughitt/tasks main) has no attachments command; the host's tasks build does, so local hygiene passes. The two offending attachments are tasks/files/autonomy-23aeff/local-suite-f71c605.log and local-suite-9523dc4.log (pytest rootdir line carries the host path), attached during autonomy-23aeff's close-out. Fix options: (a) follow the retained-item reference's layout-refusal fallback: keep the raw bytes as evidence under $WORK_ROOT/autonomy/autonomy-23aeff/, detach both, attach portable derivatives with the host path replaced by a placeholder (mapping in a task note); or (b) pin a published tasks revision that has the attachments command, once one exists. Pushing main needs the user's approval.

## Notes

- 2026-10-30T23:45:24Z (add): created
  provenance: {"harness_session":"claude-code:ebd9e3fd-0ff3-49af-84ef-dffb5a446c3c","harness_session_source":"CLAUDE_CODE_SESSION_ID","origin":"agent"}
- 2026-10-30T23:53:56Z (main): started
  provenance: {"harness_session":"codex:01a18f3b-625c-7fe1-a950-48b95107ec84","harness_session_source":"CODEX_THREAD_ID"}
- 2026-10-30T23:54:29Z (main): Direct task-record repair in main (worktree exception). Scope: preserve both raw suite logs, replace their active attachments with explicitly labelled portable derivatives, verify exact replacement and hygiene without attachment eligibility support. No code, workflow or tool pin changes; no pytest obligation for records-only work. Reproduced that ops-check attempts attachment eligibility on the current logs.
- 2026-10-30T23:54:53Z (main): Created persistent scratch on titan: /mnt/ssd3/work/autonomy/autonomy-23aeff/portable-log-repair-e51da5; purpose: preserve original suite logs and prepare portable derivatives; owner autonomy-e51da5; contents mutable, not yet checkpointed.
- 2026-10-30T23:54:54Z (main): retained: {"host": "titan", "kind": "evidence", "path": "$WORK_ROOT/autonomy/autonomy-23aeff/portable-log-repair-e51da5/local-suite-f71c605.log", "state": "kept", "verification": "verified", "purpose": "Exact raw suite evidence underlying the portable attachment on autonomy-23aeff", "next_owner": "task:autonomy-e51da5", "cleanup_trigger": "After a published tasks CLI with attachments support is pinned and normal hosted hygiene accepts the raw attachment, reassess preservation", "sha256": "8a081b5ad21d9b4208553cc15ef3c7050daf06fac30919d964a046a7e33bb228"}
- 2026-10-30T23:54:56Z (main): retained: {"host": "titan", "kind": "evidence", "path": "$WORK_ROOT/autonomy/autonomy-23aeff/portable-log-repair-e51da5/local-suite-9523dc4.log", "state": "kept", "verification": "verified", "purpose": "Exact raw suite evidence underlying the portable attachment on autonomy-23aeff", "next_owner": "task:autonomy-e51da5", "cleanup_trigger": "After a published tasks CLI with attachments support is pinned and normal hosted hygiene accepts the raw attachment, reassess preservation", "sha256": "0911fc7267306f75a5c7f45dae7db951b65644ce725b9f142f6c9b90eb395482"}
- 2026-10-30T23:54:58Z (main): Tooling mismatch reported as ops-c2263c. Exact raw bytes verified before detaching; original-to-placeholder mapping recorded on autonomy-23aeff. Reproduction guard fails before repair because ops-check calls attachment eligibility.
- 2026-10-30T23:55:38Z (main): retained: {"host": "titan", "kind": "scratch", "path": "$WORK_ROOT/autonomy/autonomy-23aeff/portable-log-repair-e51da5", "state": "kept", "verification": "verified", "purpose": "Exact raw logs and portable derivatives for hosted hygiene repair; active attachments verified by reversible byte comparison", "next_owner": "task:autonomy-e51da5", "cleanup_trigger": "After approved push and hosted hygiene verdict, establish ongoing ownership of raw evidence before closing this task; retain raws until normal checks accept originals", "manifest": "$WORK_ROOT/autonomy/autonomy-23aeff/portable-log-repair-e51da5/sha256-manifest.txt", "sha256": "b76d9f381a26f681158afcdbe3d2e5165a5c46565232c174b44779b66ad1d209"}
