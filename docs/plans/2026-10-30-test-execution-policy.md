# Test Execution Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Inline execution is the author's recommendation, subject to the user's plan review; use subagent-driven-development if the user chooses it instead.

**Goal:** Implement autonomy-23aeff: split autonomy's front door so mandatory hygiene always runs, prove one hosted full-suite workflow on branch pushes, then switch local broad suites off with `.tt.toml`.

**Architecture:** Adopt the shared ops template's recipe shape and pre-push hook unchanged except for autonomy's commands; the vendored `tools/tt` (version 8) makes every skip decision. One pinned ubuntu-24.04 job runs setup, a namespace/TLS proof, hygiene and the forced suite through the front door. Activation happens in gated steps: local wiring, a hosted pilot on the policy-enabled branch, coverage acceptance, then the policy-off commit.

**Tech Stack:** just 1.59.0, vendored tt v8, pytest under uv 0.13.6 with the system `/usr/bin/python3`, GitHub Actions, the public khughitt/tasks CLI built from a pinned revision.

**Spec:** [Test execution policy design](../specs/2026-10-30-test-execution-policy-design.md), frozen revision `ec27ca5c3a90f66c2178ca7b5a48f35fe1e7e1b3`, approved by the user on 2026-10-30 (task note `review: spec round 2`). Shared authority: ops-8bfa85 and the ops [execution contract](https://github.com/khughitt/ops/blob/main/docs/test-execution-policy.md) (private; read the registered ops checkout's `docs/test-execution-policy.md` and `docs/runbooks/test-policy-rollout.md`).

**State:** Revised after plan review round 1 (Important 3, Minor 11, all addressed); awaiting review of this revision. No implementation code changed. Local policy is enabled (no `.tt.toml`).

## Global Constraints

- "Never edit tools/tt or add a second policy parser."
- "Preserve test-one's argument forwarding and test-fast's testmon selector."
- "Do not invent check-code when there is no broad static-check workload."
- Policy file, only after accepted hosted proof and approval: `automatic_broad = false` and `broad_targets = ["test", "test-fast"]`.
- "Publish ci_remote=origin and ci_suite_refs=refs/heads/* only with the matching push workflow. Tags are not covered."
- Workflow: "ubuntu-24.04 x64", "branches ['**'] and workflow_dispatch, no duplicate pull_request event, workflow/ref concurrency with cancellation, contents: read", "Set TT_FORCE=1 at job scope", "Pin action commits and tool versions".
- "Use the image's /usr/bin/python3 (3.12 or later)… Do not substitute uv-managed Python." "Install bubblewrap, OpenSSL, bash, dash and zsh." "Missing sandbox capability is a failed setup, not permission to exclude bwrap tests."
- "never change the developer host or persist a sysctl"; the AppArmor runtime adjustment is a separately approved exception, not part of this plan's default workflow.
- "Do not need or fetch private ops, beliefs or science checkouts, credentials or a personal task registry." Checkout uses `persist-credentials: false`.
- "Target zero excluded modules and no additional skips; any difference requires explicit coverage acceptance before activation."
- Every push, workflow publication, sysctl exception and main push is an external action requiring the user's approval at that moment, for the exact revision named in its packet. Every `gh` command is prefixed `GH_TOKEN=$(gh auth token --user khughitt)`, never `gh auth switch`. `git push` goes over SSH: before each push, `ssh -T git@github.com` must greet `khughitt`.
- Task records: through Task 4 Step 4 every `tasks` write runs in the worktree. From Task 4 Step 5 on, every `tasks` write (notes, attachments, child start/done) runs in the main checkout, and the branch runs `git merge main` before each later commit and before its final merge, so the record files never diverge and the policy notes sit where tt-latency reads them.
- Fixtures build subprocess environments key by key (PATH, temporary HOME, USER, fake Git identity, `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`, `TT_LOG`) and never inherit `TT_FORCE`, `GITHUB_ACTIONS` or `GIT_*` from the runner.
- Tests run with policy enabled: Setup runs the full baseline (`just test`) before Task 1; each task uses `just test-one <path>` while working and `just test-fast` before committing.

## Review Focus

1. **CI job-scope `TT_FORCE=1` leaking into the wiring tests.** The suite itself runs with `TT_FORCE=1` and `GITHUB_ACTIONS=true` in the hosted job; a fixture that inherited either would force every "skip" case and pass for the wrong reason, or refuse. Expected: fixtures see neither unless a test sets it. Pinned by `test_the_fixture_environment_holds_no_force_or_hosted_marker` in Task 1.
2. **A nested branch or a tag push.** `refs/heads/feature/x` must take the covered route (Actions `'**'`), while `refs/tags/v1` must take the full local gate. Pinned by `test_a_nested_branch_takes_the_covered_route` and `test_a_tag_push_takes_the_full_gate` in Task 2.
3. **A push to a remote CI does not watch while policy is off.** Expected: hygiene runs, the suite is skipped with a coverage warning, never silently run or silently passed. Pinned by `test_uncovered_push_warns_without_running_the_suite` in Task 1.
4. **The hosted image lacking a sandbox capability** (AppArmor-restricted user namespaces, missing `os.setns`). Expected: the job fails at its capability or proof step before the suite, never a green run with bwrap tests skipped. Pinned by the workflow's step order, asserted in `test_the_capability_proof_precedes_the_suite` (Task 2), and observed in Task 4.
5. **`uv` resolving a managed Python through `.python-version` (3.14) on a 3.12 image.** Expected: the job uses `/usr/bin/python3` or fails; it never downloads an interpreter. Pinned by `test_the_workflow_uses_the_system_interpreter_frozen` (Task 2) and observed in Task 4's log.

---

### Task 1: Split the front door and adopt the shared push hook

**Files:**
- Modify: `justfile` (commands block, `check`, `setup`, hook recipes; header comments)
- Modify: `.githooks/pre-push` (replace with ops `templates/githooks/pre-push`, byte for byte)
- Modify: `AGENTS.md` (Gates section)
- Create: `python/tests/test_front_door.py`

**Interfaces:**
- Produces: recipes `check-hygiene` (timed, runs `check_hygiene_cmd`), `check` (untimed, `just check-hygiene`), `test-full` (untimed, `TT_FORCE=1 just test`); hook recipes that time `check_hygiene_cmd` once and then call `just test` (`hook-pre-push`) or `just test-fast` (`hook-pre-push-fast`); variable `check_hygiene_cmd` replacing `check_cmd`, with `docs_check_cmd := check_hygiene_cmd`; `push_fast_cmd` removed.
- Produces for Tasks 2 and 5: fixture `front_door` in `test_front_door.py` returning an object with `.root: Path`, `.env: dict[str, str]`, `.policy(enabled: bool, targets: list[str]) -> None`, `.recipe(name: str, *args: str, **env: str) -> CompletedProcess`, `.push(remote: str, refs: str, **env: str) -> CompletedProcess`, `.markers() -> list[list[str]]`, `.rows() -> list[dict]`.

- [ ] **Step 1: Write the fixture and failing tests in `python/tests/test_front_door.py`**

The fixture builds an isolated Git repository under `tmp_path.resolve() / "code"`: `git init`, then assert `git rev-parse --show-toplevel` equals that resolved path and `--absolute-git-dir` lies inside it before any write. Copy the repository's `justfile`, `tools/tt` and `.githooks/pre-push` in (repository root is `Path(__file__).parents[2]`), write `tasks/.config.toml` with `prefix = "autonomy"`, and a `marker.py` that appends `json.dumps(sys.argv[1:])` to `markers` and exits 7 when `FAIL_TARGET` equals `sys.argv[1]`. Rewrite the copied justfile's command lines with `re.subn(rf'(?m)^{key} := ".*"$', …)` and assert exactly one substitution per key (fail early on a renamed variable), not `just` CLI overrides, because nested `just test` calls do not inherit overrides:

```python
COMMANDS = dict(check_hygiene_cmd="python3 marker.py hygiene", fast_cmd="python3 marker.py fast",
                test_cmd="python3 marker.py suite", one_cmd="python3 marker.py focused")
```

`env` is built key by key: `PATH` from the directories of `shutil.which` for `just`, `git`, `python3` and `sh` plus `os.defpath`; `HOME` a fresh `tmp_path / "home"`; `USER="fixture"`; `GIT_CONFIG_GLOBAL="/dev/null"`; `GIT_CONFIG_NOSYSTEM="1"`; `GIT_AUTHOR_NAME/EMAIL` and `GIT_COMMITTER_NAME/EMAIL` fixture values; `TT_LOG=str(tmp_path / "runs.jsonl")`; `ALLOWED_GIT` is the set of those six `GIT_*` names. A missing `just` or `git` fails the fixture (`pytest.fail`), never skips. `push(remote, refs)` runs `sh .githooks/pre-push <remote> /fixture/remote` with `refs` on stdin. Tests (`rows()` reads TT_LOG; `(target, execution)` pairs):

```python
def test_the_fixture_environment_holds_no_force_or_hosted_marker(front_door):
    assert not {"TT_FORCE", "GITHUB_ACTIONS", "CI"} & front_door.env.keys()
    assert not any(k.startswith("GIT_") and k not in ALLOWED_GIT for k in front_door.env)

def test_recipes_follow_the_shared_shape(front_door):
    # `just --summary`, split on whitespace
    assert recipes == {"test-fast", "test-one", "test", "test-full", "live-egress", "check",
                       "check-hygiene", "gate", "docs", "work-link", "setup", "hook-pre-commit",
                       "hook-pre-commit-docs", "hook-pre-push", "hook-pre-push-fast"}

def test_setup_syncs_from_the_frozen_lock(front_door):
    # `just --evaluate setup_cmd` on the real justfile
    assert value == "just work-link python/.venv && cd python && uv sync --frozen"

def test_policy_off_push_runs_hygiene_once_and_records_the_suite_skip(front_door):
    # policy(False, ["test", "test-fast"]); recipe("hook-pre-push")
    assert result.returncode == 0
    assert front_door.markers() == [["hygiene"]]
    assert pairs == [("hook-pre-push", "ran"), ("test", "skipped")]

def test_policy_off_covered_push_skips_the_fast_suite(front_door):
    # recipe("hook-pre-push-fast")
    assert pairs == [("hook-pre-push-fast", "ran"), ("test-fast", "skipped")]

def test_policy_on_push_runs_hygiene_then_the_suite(front_door):
    # policy(True, ["test", "test-fast"]); recipe("hook-pre-push")
    assert front_door.markers() == [["hygiene"], ["suite"]]
    assert [(r["target"], r["execution_reason"]) for r in rows] == [("hook-pre-push", "default"), ("test", "policy-enabled")]

def test_hygiene_failure_stops_before_the_suite(front_door):
    # policy on; recipe("hook-pre-push", FAIL_TARGET="hygiene")
    assert result.returncode == 7 and [r["target"] for r in rows] == ["hook-pre-push"]

def test_a_suite_failure_is_the_push_status(front_door):
    # policy on; recipe("hook-pre-push-fast", FAIL_TARGET="fast")
    assert result.returncode == 7 and front_door.markers() == [["hygiene"], ["fast"]]

def test_commit_hooks_keep_hygiene_under_policy_off(front_door):
    # both hook-pre-commit and hook-pre-commit-docs, policy off
    assert front_door.markers() == [["hygiene"], ["hygiene"]]
    assert all(r["execution"] == "ran" for r in rows)

def test_full_alias_records_one_forced_run_and_preserves_failure(front_door):
    # policy off; recipe("test-full", FAIL_TARGET="suite")
    assert result.returncode == 7 and front_door.markers() == [["suite"]]
    assert [(r["target"], r["execution_reason"], r["exit"]) for r in rows] == [("test", "forced", 7)]

def test_focused_route_runs_and_forwards_each_argument_under_policy_off(front_door):
    # recipe("test-one", "a b", "$x", "*")
    assert front_door.markers() == [["focused", "a b", "$x", "*"]]
    assert [(r["target"], r["execution"]) for r in rows] == [("test-one", "ran")]

def test_a_hosted_nested_suite_without_force_fails_loudly(front_door):
    # policy off; recipe("hook-pre-push-fast", GITHUB_ACTIONS="true")
    assert result.returncode == 2 and "TT_FORCE=1" in result.stderr
    assert front_door.markers() == [["hygiene"]]
    assert not any(r["execution"] == "skipped" for r in rows)

def test_a_hosted_forced_nested_suite_runs(front_door):
    # policy off; recipe("hook-pre-push-fast", GITHUB_ACTIONS="true", TT_FORCE="1")
    assert front_door.markers() == [["hygiene"], ["fast"]]

def test_uncovered_push_warns_without_running_the_suite(front_door):
    # policy off; push("backup", "refs/heads/x <40 hex> refs/heads/x <40 zeros>\n")
    assert result.returncode == 0 and "remote full-suite coverage" in result.stderr
    assert front_door.markers() == [["hygiene"]]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `just test-one tests/test_front_door.py`
Expected: every test ERRORS at fixture setup, because the current justfile has no `check_hygiene_cmd` line for `re.subn` to substitute. That is the RED for the whole module; the assertions are exercised from Step 5 on.

- [ ] **Step 3: Rewrite the justfile to the shared shape**

Follow ops `templates/justfile`'s recipe bodies for `check-hygiene`, `check`, `test-full`, `hook-pre-commit`, `hook-pre-commit-docs`, `hook-pre-push` and `hook-pre-push-fast`, with these autonomy differences: no `check_code_cmd`/`check-code` and no `just check-code` lines; no `push_fast_cmd`/`test-push-fast` (`hook-pre-push-fast` calls `just test-fast`); `docs_check_cmd := check_hygiene_cmd`; `setup_cmd` ends `uv sync --frozen`. Keep `fast_cmd`, `test_cmd`, `one_cmd`, `test-one`, `live-egress`, `work-link`, `docs`, `gate`, `ci_remote` and `ci_suite_refs := ""` unchanged. Update the header and recipe comments to say that `check` is now an untimed composition, that hooks time mandatory work only, and that `.tt.toml` at the Git top level decides broad execution.

- [ ] **Step 4: Replace `.githooks/pre-push` with the shared template**

Run: `OPS=$(tasks projects --paths --pretty | awk '$1 == "ops" {print $NF}') && cp "$OPS/templates/githooks/pre-push" .githooks/pre-push && cmp "$OPS/templates/githooks/pre-push" .githooks/pre-push`
Expected: no output (the only difference was the policy-warning block). Keep the file mode executable.

- [ ] **Step 5: Run the tests and the shared adoption regression**

Run: `just test-one tests/test_front_door.py`
Expected: PASS, all 14.

Run from the ops checkout: `OPS_ADOPTION_HOOK=<absolute path to .worktrees/autonomy-23aeff/.githooks/pre-push> OPS_ADOPTION_FAST=1 just test-one tests.test_pre_push_adoption`
Expected: PASS (`test_lfs_failure_stops_before_gate` skipped: no LFS handoff).

- [ ] **Step 6: Update AGENTS.md Gates**

State: `.tt.toml` at this checkout's Git top level (worktrees included) decides broad execution, never records or a sibling; `just check` composes `check-hygiene`; `just test-one` is always on; `just test-full` (or `TT_FORCE=1 just test`) is the deliberate broad route; `test-fast` reselects only on Python changes, so justfile and hook edits use `just test-one tests/test_front_door.py`; hook timing from this revision measures mandatory work only and is incomparable with earlier whole-hook durations. Write no project-qualified backticked path (a project name followed by a path): ops-check resolves those through the task registry, which the hosted job lacks.

- [ ] **Step 7: Fast check and commit**

Run: `just test-fast` then `just check`
Expected: both exit 0; `tasks check` may still print the 2 existing plan-link warnings from the closed-messages plan.

```bash
git add justfile .githooks/pre-push AGENTS.md python/tests/test_front_door.py
git commit -m "feat(gates): split mandatory hygiene from broad suites"
```

### Task 2: Declare the hosted push workflow

**Files:**
- Create: `.github/workflows/test.yml`
- Modify: `justfile` (`ci_suite_refs`)
- Modify: `AGENTS.md` (Gates: coverage and omissions)
- Test: `python/tests/test_front_door.py` (add tests)

**Interfaces:**
- Consumes: Task 1's `front_door` fixture and recipes `check-hygiene`, `test-full`, `test-one`, `setup`.
- Produces: workflow `Test suite` whose job `test` Task 4 inspects; `ci_suite_refs := "refs/heads/*"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_workflow_covers_all_branches_forces_once_and_cancels_stale_heads():
    # read REPO / ".github/workflows/test.yml" as text
    assert re.search(r"(?m)^    branches: \['\*\*'\]$", wf) and "  workflow_dispatch:" in wf
    assert "pull_request" not in wf and "runs-on: ubuntu-24.04" in wf
    assert "group: ${{ github.workflow }}-${{ github.ref }}" in wf and "cancel-in-progress: true" in wf
    assert re.search(r"(?m)^permissions:\n  contents: read$", wf)
    assert "TT_FORCE: '1'" in wf and wf.count("run: just test-full") == 1
    assert re.search(r"timeout-minutes: \d+", wf) and "persist-credentials: false" in wf
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", a) for a in re.findall(r"uses: (\S+)", wf))
    assert "setup-python" not in wf

def test_the_workflow_uses_the_system_interpreter_frozen():
    assert "UV_PYTHON: /usr/bin/python3" in wf and "UV_PYTHON_DOWNLOADS: never" in wf and "UV_FROZEN: '1'" in wf
    assert "enable-cache: false" in wf

def test_the_capability_proof_precedes_the_suite():
    # indices of the run lines, in order
    assert idx("apt-get install") < idx("os.setns") < idx("run: just setup") < idx("run: just test-one") < idx("run: just check-hygiene") < idx("run: just test-full")
    for package in ("bubblewrap", "openssl", "bash", "dash", "zsh"):
        assert package in install_line

def test_the_hook_declares_every_branch_covered():
    # just --evaluate on the real justfile
    assert ci_suite_refs == "refs/heads/*" and ci_remote == "origin"

def test_a_nested_branch_takes_the_covered_route(front_door):
    # policy on; push("origin", "refs/heads/feature/x <hex> refs/heads/feature/x <zeros>\n")
    assert front_door.markers() == [["hygiene"], ["fast"]]

def test_a_tag_push_takes_the_full_gate(front_door):
    # policy on; push("origin", "refs/tags/v1 <hex> refs/tags/v1 <zeros>\n")
    assert front_door.markers() == [["hygiene"], ["suite"]]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `just test-one tests/test_front_door.py`
Expected: the five new workflow/ref tests FAIL (no workflow file; `ci_suite_refs` empty, so the nested branch takes the full gate); `test_a_tag_push_takes_the_full_gate` passes already.

- [ ] **Step 3: Write `.github/workflows/test.yml`**

Shape it on the ops pilot workflow (ops `.github/workflows/ci.yml`) with these values. `on.push.branches: ['**']`, `workflow_dispatch`; `permissions: contents: read`; concurrency as asserted; job `test`, `runs-on: ubuntu-24.04`, `timeout-minutes: 15` (provisional; Task 4 resets it from the measured run). Job `env`: `TT_FORCE: '1'`, `GIT_CONFIG_NOSYSTEM: '1'`, `UV_PYTHON: /usr/bin/python3`, `UV_PYTHON_DOWNLOADS: never`, `UV_FROZEN: '1'`, `PYTEST_ADDOPTS: -rs` (skip reasons in the log). Steps, in order:

1. Isolate state: append to `$GITHUB_ENV` `GIT_CONFIG_GLOBAL=$RUNNER_TEMP/gitconfig` and `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME` under `$RUNNER_TEMP`.
2. `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1`, `persist-credentials: false`.
3. `extractions/setup-just@53165ef7e734c5c07cb06b3c8e7b647c5aa16db3 # v4`, `just-version: '1.59.0'`.
4. `astral-sh/setup-uv@68559e99cc807c1eb7e9238fd43a15bba460eec2 # v10.3.3`, `version: '0.13.6'`, `enable-cache: false` (the spec proposes no new storage), no `python-version` input.
5. `sudo apt-get update && sudo apt-get install --no-install-recommends -y bubblewrap openssl bash dash zsh`.
6. Capability check, failing on any absence: `/usr/bin/python3 -I -c` asserting `sys.version_info >= (3, 12)` and `hasattr` for `os.setns`, `os.pidfd_open`, `signal.pidfd_send_signal`; then print `sysctl -n kernel.apparmor_restrict_unprivileged_userns` (or `absent`) for the record. No sysctl write.
7. Pinned tasks CLI, outside the workspace so tt does not record the checkout dirty: `git clone https://github.com/khughitt/tasks "$RUNNER_TEMP/tasks"` then `git -C "$RUNNER_TEMP/tasks" checkout --detach 43b6eee5ae6c95ba83ac77e6108915ec9557f2b5` (public, no credentials); `rustup toolchain install 1.99.1 --profile minimal`; `cargo +1.99.1 build --locked --release --manifest-path "$RUNNER_TEMP/tasks/Cargo.toml"`; append the absolute `$RUNNER_TEMP/tasks/target/release` to `$GITHUB_PATH`.
8. `run: just setup`.
9. Namespace and TLS proof: `run: just test-one tests/test_sandbox_probe.py tests/test_egress_helper.py tests/test_egress_upstream.py`.
10. `run: just check-hygiene`.
11. `run: just test-full`.

Re-verify each pin with `GH_TOKEN=$(gh auth token --user khughitt) gh api` (tag ref → commit sha; tasks `commits/main`) before committing, and use any newer released pin the check returns.

- [ ] **Step 4: Declare coverage in the justfile**

Set `ci_suite_refs := "refs/heads/*"` and replace the comment above it with one naming `.github/workflows/test.yml` as the covering workflow and stating that tags are not covered.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `just test-one tests/test_front_door.py`
Expected: PASS, all 20.

- [ ] **Step 6: Update AGENTS.md Gates with coverage and omissions**

Name the workflow, its trigger (every branch push and manual dispatch, no tags, no PR event), that a declaration is scheduling intent rather than proof the latest head passed, and the known hosted omissions: `tasks check` cannot validate foreign task dependencies and `ops-check` cannot compare vendored contracts without a private ops checkout, so both stay mandatory locally; `just live-egress` runs in neither.

- [ ] **Step 7: Fast check and commit**

Run: `just test-fast` then `just check`
Expected: both exit 0.

```bash
git add .github/workflows/test.yml justfile AGENTS.md python/tests/test_front_door.py
git commit -m "ci: run the forced full suite on every branch push"
```

### Task 3: Review the local wiring and prepare the pilot packet

**Files:**
- Create (scratch, not committed): `$WORK_ROOT/autonomy/autonomy-23aeff/activation-packet-a.md`, `local-suite.log`, the review reports

**Interfaces:**
- Consumes: Tasks 1-2's branch head.
- Produces: a reviewed branch head, packet A (attached to autonomy-23aeff) and the local baseline counts Task 4 compares against: collected, executed, passed, failed, skipped, per-module skip list.

- [ ] **Step 0: Review Tasks 1-2**

Dispatch a fresh read-only reviewer on the frozen branch head (repository, full SHA, the spec revision and this plan's revision) for a whole-branch review of Tasks 1-2. Note `review: impl round <n> — …` before acting, record rulings in the plan workspace ledger, and fix Critical and Important findings in corrective rounds (up to five, each with a scoped fresh re-review), proving each fix RED→GREEN with `just test-one`. Minor findings go to the ledger as `minor (deferred)`. Packet A names the reviewed head.

- [ ] **Step 1: Record the scratch directory**

Create `$WORK_ROOT/autonomy/autonomy-23aeff/` and immediately `tasks note autonomy-23aeff` with host, path, purpose ("activation evidence for Tasks 3-5") and owner.

- [ ] **Step 2: Run the forced local suite with skip reasons**

Run: `set -o pipefail; PYTEST_ADDOPTS=-rs just test-full 2>&1 | tee "$WORK_ROOT/autonomy/autonomy-23aeff/local-suite.log"`
Expected: exit 0 (the suite's status, through `pipefail`), nonzero `collected N items`, summary line, and `SKIPPED [...]` lines naming each skip's module and reason. A failure here stops the task for repair with policy still enabled.

- [ ] **Step 2b: Rehearse hosted hygiene**

Build tasks `43b6eee5ae6c95ba83ac77e6108915ec9557f2b5` with `cargo +1.99.1 build --locked --release` into the scratch directory, then run `just check-hygiene` from the worktree with that binary first on `PATH` and `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME` and `HOME` pointed at empty scratch directories.
Expected: exit 0, with only the foreign-dependency and plan-link warnings already known. Anything that fails here would fail the hosted job: fix it before packet A.

- [ ] **Step 3: Write packet A**

Contents: branch name and head revision to push (`design/autonomy-23aeff-test-policy` → `refs/heads/design/autonomy-23aeff-test-policy`); the workflow diff summary and every pin; setup (`just setup` with system Python, frozen lock); run limits (one job per push, 15-minute timeout, per-ref cancellation, at most 5 pilot pushes of this branch); the local counts and skip list from Step 2; known omissions (remote hygiene limits, `live-egress`); visibility re-read at this moment with `GH_TOKEN=$(gh auth token --user khughitt) gh api repos/verifiably/autonomy --jq .visibility` and the cost basis (public repository, standard hosted runner, free; if it reads private, stop and follow the spec's allowance rule instead); that `workflow_dispatch` works only from the default branch, so pilot reruns are pushes until main is pushed; the contingency that a namespace-proof failure caused by AppArmor returns with a separate request for a runtime-only `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0` step on the hosted VM.

- [ ] **Step 4: Attach and present**

Run: `tasks attach autonomy-23aeff "$WORK_ROOT/autonomy/autonomy-23aeff/activation-packet-a.md" --caption "Pilot push packet A"`, then present packet A to the user and stop for approval of the pilot pushes. Park with `--waiting-on user --reason approval` if the session ends first.

### Task 4: Prove hosted coverage on the policy-enabled branch

**Files:**
- Modify: `.github/workflows/test.yml` (`timeout-minutes`, and the sysctl step only if separately approved)
- Create (scratch): `hosted-run-<id>.log`, `activation-packet-b.md`

**Interfaces:**
- Consumes: packet A approval; Task 3's local counts.
- Produces: an accepted hosted run id and the merge revision of the policy-enabled branch on local main.

- [ ] **Step 1: Push the branch**

Run: `ssh -T git@github.com` (must greet `khughitt`), then `git push origin design/autonomy-23aeff-test-policy`
Expected: the pre-push hook takes `hook-pre-push-fast` (the ref is covered) and runs hygiene plus `test-fast`; the push succeeds.

- [ ] **Step 2: Wait for and fetch the run**

Find it with `GH_TOKEN=$(gh auth token --user khughitt) gh run list --repo verifiably/autonomy --branch design/autonomy-23aeff-test-policy --json databaseId,headSha,status,conclusion`, retrying every 15 seconds for up to 3 minutes until a run with `headSha` equal to the pushed head appears (none: unverified, stop and report). Then `GH_TOKEN=$(gh auth token --user khughitt) gh run watch <id> --repo verifiably/autonomy --exit-status` in the background with a 30-minute timeout, and save `GH_TOKEN=$(gh auth token --user khughitt) gh run view <id> --repo verifiably/autonomy --log` to `hosted-run-<id>.log`.
Expected: conclusion `success`, nonzero collected count. Failure, cancellation or an absent job is unverified: diagnose without dropping assertions, fix on the branch with focused RED→GREEN where a test changes, and push again within packet A's limit. A namespace-proof failure from AppArmor stops here for the separate exception request.

- [ ] **Step 3: Compare and set the timeout**

Tabulate local versus hosted: collected, executed, passed, failed, skipped, excluded modules (target 0) and modules with skipped tests, with each hosted-only skip and its reason. Set `timeout-minutes` to three times the measured job duration rounded up to whole minutes, minimum 10; commit as `ci: bound the suite job from the pilot run` and push it (counts against packet A's limit). Repeat Step 2 for that push: the run packet B cites is the one for the branch head that Step 5 merges.

- [ ] **Step 4: Present packet B and stop**

Packet B: the branch head's full SHA, its successful run URL and the table from Step 3; any difference for the user's explicit coverage acceptance; and the one action to authorize next: one branch push of the policy-off commit (Task 5 Step 5). The main push is not in packet B; packet C asks for it once its revision exists. Attach packet B with `tasks attach` and stop for the user's acceptance. Without acceptance, local policy stays enabled.

- [ ] **Step 5: Integrate the hook split locally and record the floor**

After acceptance: in the main checkout, `git merge --no-ff design/autonomy-23aeff-test-policy` (main has no commits since the branch point `9b5007c`; recheck with `git log 9b5007c..main`, and resolve any record conflict by keeping both note sets in time order, then `tasks check`). `just check` passes on main; then, from the main checkout, note `policy: enabled at <merge commit time, RFC3339 UTC> revision <full merge sha>` on autonomy-23aeff exactly in that form. From here on, task writes follow the Global Constraints' record rule.

### Task 5: Activate policy-off

**Files:**
- Create: `.tt.toml`
- Modify: `AGENTS.md` (Gates: policy state and rollback)
- Test: `python/tests/test_front_door.py` (add a test)

**Interfaces:**
- Consumes: packet B's acceptance and push authorization; the `front_door` fixture.
- Produces: the policy-disabled revision and time Task 6 uses.

- [ ] **Step 1: Write the failing test**

```python
def test_the_repository_policy_disables_only_the_broad_suites():
    # load REPO / "tools/tt" with importlib (SourceFileLoader) and call its read_policy(REPO)
    assert policy["automatic_broad"] is False and policy["broad_targets"] == ["test", "test-fast"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `just test-one tests/test_front_door.py::test_the_repository_policy_disables_only_the_broad_suites`
Expected: FAIL (no `.tt.toml`; the policy reads as absent).

- [ ] **Step 3: Write `.tt.toml` and the guide's policy state**

Exactly the two lines from Global Constraints. Before editing, `git merge main` into the branch. In AGENTS.md Gates, say local broad suites are off, `just test-full` runs them deliberately, and rollback sets `automatic_broad = true`, updates `test_the_repository_policy_disables_only_the_broad_suites` to match, and records `policy: enabled at <RFC3339-UTC> revision <full-sha>` at the landed rollback.

- [ ] **Step 4: Verify the activated behavior locally**

Run: `just test-one tests/test_front_door.py` — PASS, all 21 (focused execution under policy-off).
Run: `just test` — exit 0, prints the policy skip and `TT_FORCE=1` route, and the newest TT_LOG row for `test` reads `execution: skipped`, `exit: null`, `tests: null`.
Run: `TT_FORCE=1 just test` — exit 0, row `execution_reason: forced` with a nonzero test count. Forced-failure propagation is pinned by `test_full_alias_records_one_forced_run_and_preserves_failure` and the nested hosted refusal by `test_a_hosted_nested_suite_without_force_fails_loudly`.

- [ ] **Step 5: Commit, review and push the branch**

```bash
git add .tt.toml AGENTS.md python/tests/test_front_door.py
git commit -m "feat(gates): turn local broad suites off"
```

Dispatch a fresh read-only reviewer scoped to this commit's diff (frozen SHA), with the same note, ledger and corrective-round rules as Task 3 Step 0. Then `ssh -T git@github.com` (must greet `khughitt`) and `git push origin design/autonomy-23aeff-test-policy` under packet B.
Expected: the hook runs hygiene, records `test-fast` as skipped, and the push succeeds. Inspect the hosted run as in Task 4 Step 2; it must succeed with the accepted counts.

- [ ] **Step 6: Integrate, record and push main**

`git merge main` into the branch once more, then merge the branch into main (`git merge --no-ff`) and, from the main checkout, note `policy: disabled at <merge time, RFC3339 UTC> revision <full merge sha>` on autonomy-23aeff. Present packet C (attached with `tasks attach`): the exact main SHA to push, `git log --oneline origin/main..main`, and the successful run for the policy-off branch head. Stop for approval; then `ssh -T git@github.com` and `git push origin main`, and confirm main's hosted run for that SHA succeeds. A failing main run stops here with policy left as landed and the failure reported; rollback is the user's call.

### Task 6: Dispose latency obligations and report adoption

**Files:** none in the tree; task records only.

**Interfaces:**
- Consumes: Task 5's disabled revision and time, hosted run ids.

- [ ] **Step 1: Inspect timing incidents at registered main**

Run: `tasks list --project autonomy --tag test-latency` and `tasks list --project autonomy --tag halt`, plus any incident naming autonomy found by `tasks list --all-projects --tag test-latency`.
Expected: none (as observed 2026-10-30); note `no test-latency incident or timing halt at <sha>; nothing retired` on autonomy-23aeff. For any incident found, follow the rollout runbook's per-obligation commands: retire only `test`/`test-fast` obligations, keep other targets and unrelated halts, and never claim performance verification.

- [ ] **Step 2: Report**

Note on ops-8bfa85 autonomy's adoption state: disabled revision and time, accepted hosted run URLs and counts, omissions. Note on ops-56aab7 the same evidence links for the 30-day regret review.

- [ ] **Step 3: Account for retained items and close**

Record the scratch directory's manifest and SHA-256 under the retained-item rule, attach the hosted logs and packets, run `tt-report`, then release the worktree and close autonomy-23aeff with `tasks done` naming the disabled revision.
