---
id: autonomy-f6efe8
title: "Envelope Plan B2: science_reads, baseline, endpoint, run supervisor close path and run close/stop (rows E7–E12, E20 full-run arm)"
status: todo
priority: 2
size: l
complexity: high
process: planned
created: 2026-10-15T13:05:59Z
updated: 2026-10-23T01:41:52Z
depends: [beliefs-7a56ef, sci-a1d45f, autonomy-641123, autonomy-413763, autonomy-cb258b]
tags: []
agent: claude-code/claude-opus-5-5
---

Spec §13 item 4, second half: plan and build after the beliefs and science slices land (beliefs-7a56ef, sci-a1d45f). Builds on Plan B1 (autonomy-641123): science_reads (heads --resolve, log.v1), baseline.json/events.jsonl/seal.json, the endpoint launcher and control-socket client with heartbeat and seal, run steps 3–8 and the close path, autonomy run close and run stop, the wall-clock bound if B1 did not settle it; rows E7–E12 and E20's full-run arm. Consumes Plan A's tiers, ledger reader, closing check and sandbox.

## Notes

- 2026-10-15T13:05:59Z (main): concerns: none — split from autonomy-641123 before its plan was written (2026-10-15); the wall-clock bound note on 641123 applies here if B1 leaves it
- 2026-10-15T13:06:06Z (main): correction: the line above is not an outcome-measure concern (no closed work fell short); this task is a planned split of autonomy-641123
- 2026-10-15T15:37:58Z (plan-b1): inputs from Plan B1 (autonomy-641123) final review: (1) execute now takes a required progress= argument (the B1 plan's Task 4/5 code blocks show the pre-fix signature; read run.py, not the plan); (2) a steps exception after allocation currently exits 4 through cli.main's last-resort handler with no disposition.json and nothing in events.jsonl — B2 should close such a run unwired with a spec'd finding code; (3) LineChannel's pipe EPIPE handling relies on CPython ignoring SIGPIPE, so the orchestrator must not restore SIGPIPE; (4) an AF_UNIX report fd after shutdown(SHUT_WR) passes step 2 (lines then dropped report-unwritten; spec silent); (5) allocate failing mid-way now rolls back and refuses allocation-failed — check against the orphaned-run scan
- 2026-10-15T15:39:32Z (plan-b1): input from Plan B1 fix re-review: run.Progress and cli._unexpected assume a set dirs means no disposition.json; if append_event (ENOSPC) or the final fsync_dir raises after write_disposition published, a clean/quarantined run would exit 4 with a wrong 'left for run close' diagnostic — B2 must key the exit on a published disposition
- 2026-10-17T11:55:57Z (main): From the egress amendment (decision 13) and its plan autonomy-e4c0b5 (docs/plans/2026-10-17-envelope-plan-egress.md, scope table): B2 wires the egress library into the run. Step 7: EgressSession.start (check_proxy, egress-unproven) beside the actor's prove, with egress_denied(Opened.places.config, Opened.route) in the denied set. Step 9: launch(..., before_release=session.attach); on EgressUnproven kill the session and close unwired with unproven(error). Renew the proxy with the endpoint's lease. Close step 0: session.close() sent together with the seal, each waited on within its own bound; the proxy's pidfd is a close trigger. run close: kill_orphan(run_dir). baseline.json's egress block from Opened.route (name, digest, upstream, url). events.jsonl: the close's start with its trigger and the seal request. E21/E22 full-run arms and the close/seal ordering negatives.
- 2026-10-17T17:47:28Z (plan-egress): from egress plan (autonomy-e4c0b5) final review — B2 must: (1) call kill_orphan only for runs with no settlement event after egress-proxy, or have it rebuild from the recorded event (today it re-settles and can turn egress-close-timeout into egress-lost); (2) set MSG_CMSG_CLOEXEC / os.set_inheritable(False) on fds received via recv_fds (helper.make_listener, proxy receive_message) before the orchestrator gains threads/children; (3) split EgressSession.close into send and wait, or run it on a thread, so close step 0 goes out with the seal (close() blocks up to 5 s).
- 2026-10-23T01:37:23Z (docs/spec-run-refusals): from autonomy-cb258b's spec amendment: the exit rule on an unexpected failure is now in decision 12 'On an unexpected failure'. It keys on a durable disposition.json (written, fsynced, directory fsynced), not merely a published one, superseding the 'published' wording of the 2026-10-15 15:39 note: a durable disposition keeps its code whatever fails after it; one linked whose directory fsync failed exits 4 and run close prints it (§9). B2 brings the code to this rule and adds its test.
- 2026-10-23T01:41:52Z (docs/spec-run-refusals): minor (deferred) from autonomy-cb258b review round 2: (m4) add a §12 arm for the durable-disposition rule: fsync_dir raising after the link exits 4 and run close prints the disposition; append_event raising after a durable disposition exits its disposition's code. (m2) specify how run close settles a run directory with no baseline (spec §3 Orphans now says B2 specifies it). Observation: a SIGINT between allocate returning and progress.dirs = dirs (run.py execute) exits 2 with directories left; have allocate set progress itself.
