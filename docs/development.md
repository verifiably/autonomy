# Development and Verification Guide

Type: guide; document types 1.

This guide documents the development workflow, local verification commands, test execution policies, and environment boundaries for `verifiably-autonomy`.

## Audience and prerequisites

This guide serves contributors and automated agents developing, maintaining, or verifying the `verifiably-autonomy` codebase. Development requires a Linux host environment equipped with unprivileged user namespaces and modern process isolation primitives.

### Host requirements

- **Operating System:** Linux kernel 5.8 or later (requires kernel support for `os.setns` with `NS_GET_USERNS`, `os.pidfd_open`, and `signal.pidfd_send_signal`).
- **Python:** Python 3.12 or later. The test runner uses the system interpreter at `/usr/bin/python3` to ensure kernel namespace and pidfd features are available without virtualenv isolation overhead.
- **Package and Workspace Managers:** `uv` (fast Python package manager) and `just` (command runner).
- **Process Isolation:** `bubblewrap` (`bwrap`) installed and functional, with unprivileged user namespaces enabled (`kernel.apparmor_restrict_unprivileged_userns=0` on systems with Ubuntu AppArmor restrictions).
- **Optional Toolchain for Analyst:** Pinned `pi` 1.1.0 installation (resolved via `--pi-dir`, `PI_DIR`, or `~/.local/share/pi/1.1.0`) and Node.js (resolved via `--node-dir`, `NODE_DIR`, or `PATH`). The Node prefix must not contain `rg` or `fd` binaries in its `bin/` directory, preventing them from shadowing host tools.

### Reading order

Before implementing changes or debugging issues, consult the primary reference documents:

1. [envelope.md](envelope.md) — Sandbox isolation boundaries, static checks, pre-launch input walks, denial probes, gated launches, descriptor validation, command lifecycles, and output release.
2. [egress.md](egress.md) — Model egress proxy architecture, route configuration, closed `anthropic-messages` dialect, streaming HTTP framing, and namespace helper.
3. [records.md](records.md) — XDG directory layout, run IDs, on-disk schemas for disposition records, events logs, epoch records, walk reports, release reports, and session ledgers.

## Package and test map

The codebase is organized into the `verifiably-autonomy` package under `python/src/autonomy/`, helper scripts under `python/scripts/`, and corresponding pytest suites under `python/tests/`. Shared test fixtures and artifact builders are consolidated in `python/tests/builders.py` and `python/tests/egress_fixtures.py`.

| Package Module / Script | Responsibility | Test Suite |
| --- | --- | --- |
| `autonomy.cli` | Command-line interface and subcommand entrypoints | `python/tests/test_cli.py` |
| `autonomy.run` | Unattended research run lifecycle and disposition writing | `python/tests/test_run.py` |
| `autonomy.closing` | Post-run evidence evaluation and disposition derivation | `python/tests/test_closing.py` |
| `autonomy.membership` | Session ledger chain classification and crash recovery | `python/tests/test_membership.py` |
| `autonomy.tiers` | Write-class permits and tier permission definitions | `python/tests/test_tiers.py` |
| `autonomy.ledger` | Session ledger line formats and verification | `python/tests/test_ledger.py` |
| `autonomy.stdio` | Standard descriptor (0, 1, 2) and `--report-fd` validation | `python/tests/test_stdio.py` |
| `autonomy.channel` | Non-blocking single-line status reporting channel | `python/tests/test_channel.py` |
| `autonomy.baseline` | Append-only event journaling and lifecycle timestamps | `python/tests/test_baseline.py` |
| `autonomy.evidence` | Run evidence structures and artifact summaries | `python/tests/test_closing.py` |
| `autonomy.sandbox.spec` | Bubblewrap sandbox mount configurations and arguments | `python/tests/test_sandbox_static.py` |
| `autonomy.sandbox.static` | Static bind source resolution and denied path overlap checks | `python/tests/test_sandbox_static.py` |
| `autonomy.sandbox.bwrap` | Sandbox preflight checks, denial probing, and gated launch | `python/tests/test_sandbox_probe.py`, `python/tests/test_sandbox_launch.py` |
| `autonomy.egress.route` | Route TOML loading, validation, and credential protection | `python/tests/test_egress_route.py` |
| `autonomy.egress.dialect` | Strict parser and schema validator for Anthropic messages | `python/tests/test_egress_dialect.py` |
| `autonomy.egress.request` | HTTP/1.1 head parser, header filtering, and allowance checks | `python/tests/test_egress_request.py` |
| `autonomy.egress.server` | Egress HTTP server, chunked streaming, and error handling | `python/tests/test_egress_server.py` |
| `autonomy.egress.upstream` | Upstream TLS connection establishment and gate management | `python/tests/test_egress_upstream.py` |
| `autonomy.egress.session` | Egress proxy sandbox process management and control loop | `python/tests/test_egress_session.py`, `python/tests/test_egress_proxy.py` |
| `autonomy.egress.helper` | Network namespace helper and listener socket transfer | `python/tests/test_egress_helper.py` |
| `autonomy.analyst.toolchain` | Pinned `pi` installation and Node.js runtime validation | `python/tests/test_analyst_toolchain.py` |
| `autonomy.analyst.walk` | Pre-launch recursive directory walk and input hashing | `python/tests/test_analyst_walk.py` |
| `autonomy.analyst.release` | Symlink-safe descriptor-based output file extraction | `python/tests/test_analyst_release.py` |
| `autonomy.analyst.launch` | Analyst and command execution orchestrators | `python/tests/test_analyst_check.py`, `python/tests/test_analyst_launch.py`, `python/tests/test_command_check.py`, `python/tests/test_command_launch.py` |
| `python/scripts/egress_live.py` | Standalone script for manual live model proxy smoke checks | `python/tests/test_egress_live.py`, `python/tests/test_egress_fixtures_script.py` |
| Front door / harness | Justfile recipes, git hooks, and timing routing | `python/tests/test_front_door.py` |

## Workspace setup and test execution policy

### Hydration and setup

Run `just setup` once after creating a worktree or pulling dependency changes:

```sh
just setup
```

This runs `just work-link python/.venv` and executes `uv sync --frozen` in `python/`. It hydrates dependencies into the isolated virtual environment without touching global state.

### Test execution policy

Test execution policy is controlled by `.tt.toml` at the root of each worktree. Local broad suites are disabled by default:

```toml
automatic_broad = false
broad_targets = ["test", "test-fast"]
```

Because broad targets are disabled locally:
- `just test` and `just test-fast` record a policy skip locally and exit cleanly.
- `just test-one <target>` runs focused tests directly (e.g. `just test-one tests/test_run.py` or `just test-one -k test_cli`). Arguments are passed intact to pytest without shell quoting issues.
- `just check-hygiene` runs mandatory repository hygiene (ops-check, ops-docs check, and tasks check). It is never skipped by policy.
- `just test-full` (or `TT_FORCE=1 just test`) deliberately bypasses the skip policy to execute the entire test suite locally.
- `just docs` runs `python3 tools/ops-docs write` to update the generated identity and family regions across `README.md` and `AGENTS.md`.

Whenever modifying `justfile` or any script in `.githooks/`, verify front-door routing and policy enforcement:

```sh
just test-one tests/test_front_door.py
```

### Git hooks integration

Git hooks configured via `core.hooksPath .githooks` enforce hygiene and test policies automatically:
- Pre-commit: executes `just hook-pre-commit` (or `just hook-pre-commit-docs` when only documentation paths are staged).
- Pre-push: executes `just hook-pre-push` (or `just hook-pre-push-fast` when targeting origin branches covered by hosted continuous integration).

## Environment-gated tests and live egress

### Marker-gated tests

Certain tests require specific host privileges or external binaries and are marked in pytest:

- `bwrap`: Tests requiring `bubblewrap` and unprivileged user namespaces (`test_sandbox_probe.py`, `test_sandbox_launch.py`, `test_egress_helper.py`, `test_egress_session.py`, `test_analyst_walk.py`, `test_analyst_check.py`, `test_analyst_launch.py`, `test_command_check.py`, `test_command_launch.py`).
- `pi`: Tests requiring the pinned `pi` 1.1.0 toolchain and Node.js prefix (`test_analyst_check.py`, `test_analyst_launch.py`). These tests resolve `PI_DIR` and `NODE_DIR` through `autonomy.analyst.toolchain` and skip gracefully if the binaries are absent or shadow host utilities.

### Manual live-egress smoke check

The test suite never makes live outbound network calls or spends model provider quota. A separate manual script is provided for live integration verification:

```sh
just live-egress <route> [model]
```

This executes `python/scripts/egress_live.py`, which launches the model egress proxy with real upstream credentials for the specified route and issues a single minimal request. It prints the proxy's recorded events and token accounting. Use this recipe only for interactive debugging of provider compatibility.

### Public and maintainer boundary

Public operation is entirely offline and requires only standard Linux utilities and Python dependencies. Maintainer gates such as `tasks check` and `tools/ops-check` validate task tracking integrity and consistency against sibling checkouts; when running outside a full maintainer environment, these tools degrade gracefully or run portable subsets.

## Hosted continuous integration

Hosted verification is defined in `.github/workflows/test.yml` and triggers on every branch push to `origin`:

1. **Environment Setup:** Provisions Python 3.12, `just`, `uv`, `bubblewrap`, and required shell interpreters.
2. **Interpreter Verification:** Asserts that `/usr/bin/python3` provides `os.setns`, `os.pidfd_open`, and `signal.pidfd_send_signal`.
3. **AppArmor Configuration:** Lifts Ubuntu's unprivileged user namespace restriction on the disposable runner VM via `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`.
4. **Namespace and Egress Proof:** Runs focused tests (`tests/test_sandbox_probe.py`, `tests/test_egress_helper.py`, `tests/test_egress_upstream.py`) before running the broad suite.
5. **Hygiene and Full Suite:** Executes `just check-hygiene` followed by `just test-full` with `TT_FORCE=1`.

The hosted workflow omits `pi`-marked tests (as the runner image does not vendor the pinned `pi` distribution), cross-project task dependencies, and the paid `just live-egress` recipe. Hosted job runs are grouped by workflow and reference with in-progress cancellation enabled.
