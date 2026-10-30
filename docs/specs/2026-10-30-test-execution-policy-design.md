# Autonomy test execution policy and remote verification

Status: proposed; user design review precedes implementation planning.
Task: autonomy-23aeff. No workflow publication or policy activation is authorized.

## Intent and authority

Keep focused implementation tests and cheap hygiene on the development host;
move routine broad regression testing to one GitHub-hosted workflow per branch
push. This reduces repeated local contention while accepting later discovery of
unrelated regressions. A skipped request is never a passing suite.

The original human request and follow-up in the filing session on 2026-10-29
asked for a wrapper-owned switch, focused testing, push CI, policy-aware latency
handling and instruction changes. The project adoption task was agent-filed from
that approved rollout; its project-specific choices below are the author's calls,
not additional decisions attributed to the user.

Shared authority: ops-8bfa85, approved spec revision
`1ce9abe7c9d4f9f5ad6dd8b39e764a597e96eaec` and implementation plan revision
`ddcfdab5dbb6b60d6891d0aa84283a766275b69c`, available through tasks doc. The ops
pilot ops-68729d is done. The skip-aware ops readers, obs schema 17/parser 2 and
lore instruction delivery are recorded as landed; the current session contains
the delivered policy instructions. Autonomy already vendors tt version 8.

The [governing layer design](https://github.com/verifiably/beliefs/blob/main/docs/superpowers/specs/2026-08-29-user-and-autonomy-layer-design.md)
continues to govern the product. This change adds no kernel import or science
integration and changes no actor permissions or production sandbox behavior.

## Verified current state

Inspected at code revision `9b5007c` on 2026-10-30, before design work:

- This is an independent personal-profile Git root with in-tree task records.
  There is no .tt.toml; automatic broad execution is enabled.
- The GitHub API reports verifiably/autonomy PUBLIC, default branch main, and
  zero Actions workflows. Local origin points to that repository. No remote
  regression coverage is currently declared or established.
- The justfile runs pytest under python/. test-fast uses pytest-testmon;
  test-one forwards each caller argument intact; test runs the unselected suite.
  Both push recipes currently combine hygiene and a suite in one timed command.
- check runs ops-check, ops-docs check and tasks check. There is no broad lint or
  typecheck command to split out. Guide generation and docs classification remain
  part of the existing commit-hook behavior.
- just setup runs work-link for python/.venv and uv sync. The lockfile declares
  pytest and pytest-testmon, with no runtime dependency or private sibling package.
  Twenty test modules exist; this is a source inventory, not an executed-test count.
- Sandbox and egress tests need Linux /proc, namespaces, bubblewrap, pidfds and
  system /usr/bin/python3 with os.setns (3.12 or later). The package's declared
  Python minimum of 3.11 alone does not establish those runtime capabilities.
  OpenSSL creates fixture certificates; upstream HTTP/TLS traffic stays local.
- Existing skip conditions cover a missing IPv4 default route, missing dash,
  and missing bash/zsh terminal-recipe cases. OpenSSL absence fails the tests.
  The bwrap marker does not itself skip tests. No module exclusion is proposed.
- A clean-config tasks check exited 0 with 23 warnings: 7 unreachable foreign
  dependencies, 14 cycle checks through those dependencies, and 2 existing
  unlinked plan headings. This proves local record validation can run without
  sibling checkouts; it does not prove the missing cross-project graph valid.
- Current task inventories contain no open test-latency incident or halt. Recheck
  registered main at activation; this observation retires no obligation.

## Approaches

**Recommended author's call: adopt the shared binary policy and one Linux job.**
Reuse tt's shipped decision and existing selectors; split opaque hook commands so
mandatory hygiene always runs. Establish actual hosted coverage before switching
local broad execution off. This follows the approved shared design with the least
project-specific machinery.

**Retain local broad suites and add CI:** useful while preparing and validating
the workflow, but not the endpoint because it preserves local contention.

**Build a new selector or sample suites:** rejected for this adoption. testmon
already exists, and a second selection system adds maintenance without supplying
the requested explicit policy and remote coverage.

## Local commands and hook boundaries

Preserve test-one's argument forwarding and test-fast's testmon selector. Keep
setup, docs generation, SSH keepalive checks, push-ref validation/forwarding and
clearing inherited Git variables. Use the landed shared pre-push template through
the normal adoption route, adapting only the project's command declarations.
Never edit tools/tt or add a second policy parser.

Expose check-hygiene for the current three checks, and make check compose that
route. Do not invent check-code when there is no broad static-check workload.
Hook targets time their mandatory part once and then invoke the appropriate
broad recipe separately: test for an uncovered push, test-fast for a covered one.
The ordinary and docs commit hooks retain mandatory hygiene.

After accepted remote proof and external activation approval, add:

```toml
automatic_broad = false
broad_targets = ["test", "test-fast"]
```

This file belongs only at the invoking code checkout's Git root, including its
worktrees. It is never read from records or a sibling checkout. test-one and
check-hygiene remain protected; malformed policy fails even under force.
Expose the untimed test-full alias, implemented as TT_FORCE=1 just test. Direct
TT_FORCE=1 just test remains supported and propagates the suite's actual status.

Both push routes retain hygiene under policy-off; tt records broad skips with
null result/test fields. Uncovered remotes or refs warn without secretly running
a local suite. Publish ci_remote=origin and ci_suite_refs=refs/heads/* only with
the matching push workflow. Tags are not covered. A declaration is scheduling
intent, not proof that the latest head passed.

Update AGENTS.md and justfile guidance to name policy lookup, focused testing,
test-full, trigger coverage and known omissions. Document that split-hook timing
measures mandatory work only and is incomparable with historical whole-hook data.
Record the enabled-regime floor when the hook split lands:

```text
policy: enabled at <RFC3339-UTC> revision <full-sha>
```

## Hosted setup and verification

Author's call: one standard ubuntu-24.04 x64 VM job, not a new platform matrix.
Use branch pushes with branches ['**'] and workflow_dispatch, no duplicate
pull_request event, workflow/ref concurrency with cancellation, contents: read,
and a bounded job timeout chosen from the preparation pilot. Set TT_FORCE=1 at
job scope so nested broad invocations execute. Missing force must fail loudly.
Pin action commits and tool versions during implementation planning/preparation.

Use the image's /usr/bin/python3 (3.12 or later) for the package environment as
well as the existing sandbox helper. Check os.setns, os.pidfd_open and
signal.pidfd_send_signal explicitly. Do not substitute uv-managed Python, whose
pidfd omissions the package configuration already documents. Install bubblewrap,
OpenSSL, bash, dash and zsh; require a working namespace/egress preflight before
the full suite. Missing sandbox capability is a failed setup, not permission to
exclude bwrap tests.

Ubuntu 24.04 restricts unprivileged user namespaces through AppArmor. Preparation
must test the image's actual behavior. The activation packet may request a
runtime-only kernel.apparmor_restrict_unprivileged_userns=0 adjustment on the
disposable hosted VM if needed. Name that exception explicitly and obtain approval
with external activation; never change the developer host or persist a sysctl.
No further host-security change follows implicitly from design approval.

Run the declared just setup using a frozen lockfile sync and the chosen system
interpreter. Make the existing setup command frozen rather than adding another
dependency installer; preserve its local work-link behavior. Install pinned uv
and just. Check out and build a pinned public khughitt/tasks revision in an
isolated CI tools directory, using its locked build and an explicit Rust version.
Then run the same hygiene checks and forced full suite through the front door.
Do not need or fetch private ops, beliefs or science checkouts, credentials or a
personal task registry. Isolate Git global/system config and CI task state;
checkout must not persist credentials. The precise pins and CI-tool path belong
in the reviewed plan or preparation packet, verified against public availability.

Remote hygiene's known limitation is explicit: tasks check cannot validate the
foreign task graph without those projects, and ops-check cannot compare vendored
contracts against an unregistered private ops checkout. Keep those local checks
mandatory and retain remote warnings; a hosted success does not certify them.

Capture collected/executed/passed/failed/skipped counts and skip reasons from the
full suite, plus excluded-module and skipped-module counts. Report actual local
versus hosted differences. Target zero excluded modules and no additional skips;
any difference requires explicit coverage acceptance before activation. Keep
the paid live-egress command outside CI as it is outside the suite today; its
mocked script tests still run. Hosted portability failures are diagnosed and
reviewed without dropping assertions merely to make CI green.

Before an extended run, exercise a small case through setup, namespace proof,
local TLS egress and verdict. Implementation Setup runs the current required
full-suite baseline; this design-only phase runs no suite. Fresh focused tests
cover changed recipe/hook/workflow behavior. Fixtures build subprocess environments
key by key and isolate all Git writes. Do not duplicate tt's upstream unit suite;
test the project's wiring, force propagation, hygiene, skip logging and exit status.

## Approval, activation and rollback

1. User reviews this frozen design, then the separately frozen implementation
   plan. Implementation prepares reviewed local changes with policy still enabled.
2. Present a concrete activation packet naming exact revisions, branch/ref pushes,
   run limits, setup, namespace exception if needed, pins, local test evidence,
   coverage omissions, visibility and cost basis. Check the profile account before
   writes and use khughitt explicitly per command without switching global state.
3. After approval, push the prepared policy-enabled revision and inspect a completed
   hosted invocation with nonzero tests. Failure, cancellation or absent jobs is
   unverified. Leave policy enabled until actual coverage is accepted.
4. Only then commit policy-off and obtain its covered remote verification within
   the authorized action limits. Integrate locally under the personal profile;
   main pushes still require external authorization. Verify focused execution,
   recorded skip/null evidence and forced failing-command propagation, including
   a nested hosted refusal when force is missing.
5. Record policy-disabled UTC time and full revision on autonomy-23aeff. Inspect
   every existing timing incident by host/target at registered main, explicitly
   retire disabled obligations with that revision, preserve unrelated diagnosis
   and halts, and make no performance-verification claim. Branch-local policy
   changes alone retire nothing. Report actual adoption state to ops-8bfa85;
   ops-39bff6 is closed and names that open goal as its successor.

The repository is currently public. GitHub documents standard public hosted
compute as free; private-minute allowance/no-paid-overage proof is not applicable
to this setup. Recheck visibility at activation. If private, stop and supply the
current allowance when available and enforced no-paid-overage setting before
requesting activation. Do not enable paid overage, larger runners or billing changes.
No new artifact-storage service is proposed.

Rollback sets automatic_broad=true, restores the policy-enabled local cadence in
guidance, and records the exact enabled-regime note above at its landed revision
and time. Keep the workflow unless separately decided otherwise. Existing slow
history does not establish a new latency breach after re-enablement. The shared
30-day regret review already exists as ops-56aab7; link this adoption's evidence
there rather than inventing another first-activation date or scheduler.

## Boundaries and acceptance

This adoption changes verification commands, hooks, setup, guides and CI; no
production package behavior, new selector, test deletion or live API invocation.
The implementation plan must enumerate its touched tests and fixtures. A new
correctness failure needs repair or explicit disposition while policy remains on.

Complete only after reviewed local wiring, approved hosted proof before and after
activation, registered-main policy evidence, per-obligation latency disposition,
and current reporting/retention records. Pending preparation stays pending.
The builder chooses small fixture structure and exact version pins within this
contract; changing runner security beyond the named exception, accepting omitted
coverage, changing ownership or spending money requires a further decision.

Sources checked 2026-10-30:
[GitHub hosted runner specifications and public pricing](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
[Ubuntu 24.04 namespace restrictions](https://documentation.ubuntu.com/release-notes/24.04/),
[shared execution contract](https://github.com/khughitt/ops/blob/main/docs/test-execution-policy.md)
(private; the task-resolved local copy is authoritative for this preparation).
