# autonomy-23aeff — packet C: push local main

Prepared 2026-10-30. Asks for approval of one external action: `git push origin main`.
That publishes the policy adoption, the hosted workflow and the sandbox layout fix on the
default branch. Its hosted run is then checked.

## What would be pushed

- Remote: `origin` = `git@github.com:verifiably/autonomy.git` (SSH as khughitt;
  repository public).
- `origin/main` = `55417bcccff956599acf2aa518a4e3e0049aa2e6`.
- Local `main` = the head at push time. It is now
  `58424643b83d8d3107b12f6ff6e4aa249da15494`; any later commits are task records
  only (`tasks/`), checked with `git diff --stat 5842464 <head> -- . ':!tasks'` printing
  nothing, immediately before the push.
- Range `origin/main..main`: 97 commits. Listed in `origin-main..main.txt`; first-parent
  view:
  - `9b5007c` start autonomy-23aeff (task record, made before this session's work)
  - `714d6b9`..`f84eaa6` task records for autonomy-7f4bc7 and autonomy-b38b76
  - `f0c0d37` merge: sandbox mirrors the host's merged-/usr links (autonomy-7f4bc7;
    reviewed in 2 rounds, accepted)
  - `3335569` merge: split hygiene from broad suites, hosted workflow (Tasks 1-4)
  - `0ab3671` **chore(tools): vendor ops-check version 16**: committed on main by
    another session at 17:58:32Z, not by this work
  - `b6fdc72` merge: turn local broad suites off (Task 5)
  - task-record commits after `b6fdc72`

## Evidence

- Accepted coverage (packet B): run 41095831866, 1394/1394, identical to local.
- Policy-off head `26c8a0e`: run https://github.com/verifiably/autonomy/actions/runs/41101402802,
  conclusion `success`. Its counts:
  - namespace proof 45/45;
  - full suite collected 1395, passed 1395, skipped 0 (the accepted 1394 plus the policy test);
  - 21 modules, the same set as local;
  - no policy skip in the hosted job.
  - Log sha256 `84ec72c2056fe009e6cfbc8002bc7bb8490b9ace3875a1266c6d44d695cfea2a`.
- `git diff --stat 26c8a0e 5842464 -- . ':!tasks'` shows exactly one difference:
  `tools/ops-check` (+246/-30), the ops-check v16 vendoring above. That change is
  **not** covered by run 41101402802. On local main, `just check` passes with it, and
  main's own hosted run, after the push, would be its first hosted check.
- Reviews: Tasks 1-2 (impl round 1, accept), the sandbox fix (2 rounds, accept) and the
  policy-off commit (rounds 2-3: one Important finding fixed, then accept).
- Local main: `.tt.toml` is active; `just test` records a skip and `just check` exits 0.
- Recorded on autonomy-23aeff:
  - `policy: enabled at 2026-10-30T17:37:39Z revision 333556916b25706c852e2c893f21ceca68f0aeba`
  - `policy: disabled at 2026-10-30T17:59:04Z revision b6fdc728a1ac80f947751d5bda0c7507a457b154`
- Latency: there is no autonomy test-latency incident or halt, so nothing is retired.

## After the push

I find main's run for the pushed SHA and check it succeeds with 1395/1395. Then I report
to ops-8bfa85 and ops-56aab7, account for the retained items, and close the task. If
main's run fails, I stop and report; local policy stays as landed, and rollback is your
call.

## Alternative

If you prefer not to publish another session's ops-check commit under this approval,
the option is to push only up to `b6fdc72`'s first parent excluding `0ab3671`. That is
not possible without rewriting main, so I don't recommend it. You can also defer the
main push until that session confirms its vendoring.
