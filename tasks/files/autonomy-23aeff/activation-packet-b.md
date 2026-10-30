# autonomy-23aeff — packet B: coverage acceptance and the policy-off branch push

Prepared 2026-10-30. Asks for two decisions:

1. Accept the hosted coverage below as equivalent to local verification.
2. Approve one push of the policy-off commit (Task 5) to the pilot branch.

The main push is not covered here; packet C asks for it, naming its exact SHA.

## The accepted run

- Run: https://github.com/verifiably/autonomy/actions/runs/41095831866, conclusion
  `success`. Every step passed; the job took 3 min 02 s (17:06:07 to 17:09:09 UTC).
- Head: `9523dc4ae73140efdfb2e25fabdd4f1a27a7c863`, i.e. code `a17172577904537cfa8c339b7a707ab5fa51b80b`
  plus `tasks/` changes only.
- Log: `hosted-run-41095831866.log`, sha256 `1b208a41e691fdaaf80b75f0f6e41bca9b0239924cc54a4bf17e634887dc0fea`.
- The namespace and TLS egress proof passed (45 of 45) with the approved AppArmor runtime
  sysctl and the sandbox layout fix (autonomy-7f4bc7).

## Local versus hosted, same head

| | local (this host, Arch, Python 3.14.8) | hosted (ubuntu-24.04, Python 3.12.3) |
|---|---|---|
| collected | 1394 | 1394 |
| executed | 1394 | 1394 |
| passed | 1394 | 1394 |
| failed | 0 | 0 |
| skipped | 0 | 0 |
| test modules | 21 | 21 (identical set) |
| excluded modules | 0 | 0 |
| modules with skipped tests | 0 | 0 |
| hygiene (`check-hygiene`) | exit 0, 23 known warnings | exit 0, the same 23 warnings |

The local run is `PYTEST_ADDOPTS=-rs just test-full` at the same head; its log sha256 is
`0911fc7267306f75a5c7f45dae7db951b65644ce725b9f142f6c9b90eb395482`. There are no differences to accept beyond the known omissions.

## Known omissions (unchanged from packet A)

- Hosted `tasks check` cannot validate dependencies on other projects' tasks (7
  unreachable, 14 unverifiable cycles). ops-check cannot compare vendored tools with an
  ops checkout. Both stay mandatory locally.
- The paid live-egress recipe runs in neither place. Tags are not covered.
- The hosted job lifts Ubuntu's AppArmor user-namespace restriction on its disposable
  VM, as approved.

## Pilot pushes so far

1. `2f261d7`: failed at the namespace proof (AppArmor restriction).
2. `29e81e2`: failed at the namespace proof (sandbox `/lib64` layout; product defect fixed in autonomy-7f4bc7).
3. `9523dc4`: success (above).

## The push to approve

After acceptance, these happen in order:

- **Integrate the hook split into main locally.** `git merge --no-ff` of the branch head
  at that moment. It differs from `9523dc4` only in `tasks/`, which I check with
  `git diff --stat 9523dc4 <head> -- . ':!tasks'` printing nothing. Then record
  `policy: enabled at <merge time> revision <merge sha>`.
- **Commit `.tt.toml`** (`automatic_broad = false`, `broad_targets = ["test", "test-fast"]`),
  the AGENTS.md policy and rollback text, and a policy test.
- **Lower `timeout-minutes` from 15 to 10** in the same commit (3 × the measured
  3 min 02 s, rounded up, minimum 10). This is a ruling: one push instead of two.
- **Run a fresh scoped review** of that commit.
- **Push it to `refs/heads/design/autonomy-23aeff-test-policy`.** This is pilot push 4 of
  5. Its pre-push hook runs hygiene and records `test-fast` as skipped.

I then inspect that push's hosted run, which must pass with the accepted counts plus the
new policy test. Packet C follows with the exact main SHA.
