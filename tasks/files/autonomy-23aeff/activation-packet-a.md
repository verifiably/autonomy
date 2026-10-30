# autonomy-23aeff — packet A: pilot push of the policy-enabled branch

Prepared 2026-10-30. Asks for approval of one external action: pushing the branch
below to origin, which publishes `.github/workflows/test.yml` and starts its first
hosted run. Local policy stays enabled (no `.tt.toml`) throughout.

## The push

- Remote: `origin` = `git@github.com:verifiably/autonomy.git` (SSH authenticates as
  khughitt, checked 2026-10-30).
- Ref: `design/autonomy-23aeff-test-policy` → `refs/heads/design/autonomy-23aeff-test-policy`
  (new branch; main is untouched).
- Reviewed code revision: `f71c605` (Tasks 1-2). The pushed head is the branch head at
  push time; every commit after `f71c605` touches only `tasks/` (task records), checked
  with `git diff --stat f71c605 <head> -- . ':!tasks'` printing nothing, immediately
  before the push.
- Local gate at push: the ref is covered (`ci_suite_refs = refs/heads/*`), so the hook
  runs hygiene plus `test-fast` (policy enabled, testmon selection).

## What the workflow does

`Test suite`, on push to any branch (`'**'`) and `workflow_dispatch`; no tags, no
`pull_request`. `permissions: contents: read`; concurrency per workflow and ref with
cancel-in-progress. One job, `ubuntu-24.04`, `timeout-minutes: 15` (provisional; reset
from the measured run before packet B). Job env: `TT_FORCE=1`, `GIT_CONFIG_NOSYSTEM=1`,
`UV_PYTHON=/usr/bin/python3`, `UV_PYTHON_DOWNLOADS=never`, `UV_FROZEN=1`,
`PYTEST_ADDOPTS=-rs`.

Steps: isolate Git config and XDG state under `$RUNNER_TEMP`; checkout
(`persist-credentials: false`); just 1.59.0; uv 0.13.6 (cache disabled); apt
`bubblewrap openssl bash dash zsh`; system-interpreter check (3.12+, `os.setns`,
`os.pidfd_open`, `signal.pidfd_send_signal`) and a read-only print of
`kernel.apparmor_restrict_unprivileged_userns`; build public khughitt/tasks at
`43b6eee5ae6c95ba83ac77e6108915ec9557f2b5` with Rust 1.99.1 under `$RUNNER_TEMP`;
`just setup`; namespace and TLS egress proof
(`just test-one tests/test_sandbox_probe.py tests/test_egress_helper.py tests/test_egress_upstream.py`);
`just check-hygiene`; `just test-full`.

Pins, verified against public GitHub 2026-10-30 (each is the latest release):
- `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` (v7.0.1)
- `extractions/setup-just@53165ef7e734c5c07cb06b3c8e7b647c5aa16db3` (v4)
- `astral-sh/setup-uv@68559e99cc807c1eb7e9238fd43a15bba460eec2` (v10.3.3)
- khughitt/tasks `43b6eee5ae6c95ba83ac77e6108915ec9557f2b5` (main head)

No credentials, secrets, private checkouts (ops, beliefs, science) or task registry are
fetched or needed.

## Run limits and cost

- One job per push; a newer push to the same ref cancels the older run.
- Pilot limit: at most 5 pushes of this branch in total. That is a cap. Each retry after
  the first push still needs your approval for its exact revision.
- `workflow_dispatch` works only from the default branch, so until main is pushed,
  pilot reruns are pushes.
- Visibility re-read 2026-10-30: `verifiably/autonomy` is **public**, with 0 workflows.
  Standard GitHub-hosted runners are free for public repositories, so no private-minute
  allowance or overage setting applies. If it reads private at push time, I stop and
  bring the allowance and no-overage evidence instead. No larger runners, billing
  changes or artifact storage.

## Local evidence (policy enabled)

- Baseline before Task 1: `just test` → 1362 passed.
- Branch at `f71c605`, `PYTEST_ADDOPTS=-rs just test-full`: collected 1382,
  executed 1382, passed 1382, failed 0, skipped 0; 21 test modules, 0 excluded,
  0 with skipped tests.
- Wiring: `just test-one tests/test_front_door.py` 20 passed; the ops shared pre-push
  adoption regression ran 4 tests (1 skipped: no LFS); `just check` 0.
- Hosted-hygiene rehearsal: pinned tasks `43b6eee` built locally, `env -i` with empty
  HOME and XDG dirs → `just check-hygiene` exit 0 with the 23 known warnings.
- Review: fresh whole-branch review of Tasks 1-2 (impl round 1) accepted with no
  Critical or Important findings; 4 minors deferred.

## Known omissions

- Hosted `tasks check` cannot validate dependencies on other projects' tasks (7
  unreachable, 14 unverifiable cycles); ops-check cannot compare vendored tools with an
  ops checkout. Both stay mandatory locally; a hosted pass does not certify them.
- The paid live-egress recipe runs neither locally nor hosted; its mocked script tests
  run in the suite.
- Tags are not covered.

## Separate exception (approve or decline independently)

Ubuntu 24.04 ships `kernel.apparmor_restrict_unprivileged_userns=1`, which may block the
sandbox's user namespaces on the hosted VM. If the first run's namespace proof fails on
that restriction, the fix is one workflow step before setup:
`sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`. It is runtime only, on
the disposable VM, never persisted and never run on this host. If you approve it now, I
add it only if the first run shows it is needed, and that retry's revision still comes
to you for approval. If you decline, a failure stops the pilot and comes back to you.

## What follows

After the run completes I compare hosted and local counts. Packet B then asks you to
accept coverage and approve one push of the policy-off branch. Until then nothing
merges into main.
