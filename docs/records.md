# Run Directory Records, Permits, and Ledger Schemas

Type: data model; document types 1. Version 1 for disposition.json and ledger.v1; other run-directory records are currently unversioned.

The autonomy runtime records structured, append-only JSON and JSONL artifacts within dedicated state and cache directories for every run. These records capture pre-launch environment provenance, real-time lifecycle transitions, egress accounting, released files, and closing research dispositions.

## XDG layout and run IDs

Run directories and transient scratch spaces follow the XDG Base Directory specification as resolved by `places(env)` in `python/src/autonomy/run.py` and `python/src/autonomy/analyst/launch.py`:

| Directory Type | Default Filesystem Location | Permissions | Purpose |
| --- | --- | --- | --- |
| **Config** | `$XDG_CONFIG_HOME/verifiably-autonomy` (`~/.config/verifiably-autonomy`) | `0755` | Route definitions under `routes/<name>.toml`. |
| **State (`runs`)** | `$XDG_STATE_HOME/verifiably-autonomy/runs/<run-id>/` | `0700` | Run artifacts for `autonomy run`. |
| **State (`analyst`)** | `$XDG_STATE_HOME/verifiably-autonomy/analyst/<run-id>/` | `0700` | Run artifacts for `autonomy analyst`. |
| **State (`command`)** | `$XDG_STATE_HOME/verifiably-autonomy/command/<run-id>/` | `0700` | Run artifacts for `autonomy command`. |
| **Cache (`scratch`)** | `$XDG_CACHE_HOME/verifiably-autonomy/scratch/<run-id>/` | `0700` | Actor scratch tmpfs for `autonomy run`. |
| **Cache (`analyst`)** | `$XDG_CACHE_HOME/verifiably-autonomy/analyst/<run-id>/scratch/` | `0700` | Subdirectories `agent`, `agent/bin`, `home`, `sessions`, `outputs`. |
| **Cache (`command`)** | `$XDG_CACHE_HOME/verifiably-autonomy/command/<run-id>/scratch/` | `0700` | Subdirectories `home` and `outputs`. |
| **Runtime** | `$XDG_RUNTIME_DIR/va/<run-id[:12]>/` | `0700` | Endpoint socket for `autonomy run`; uses first 12 hex digits of `run_id`. |

Every run is identified by `run_id`, a string of 32 lowercase hexadecimal characters generated via `secrets.token_hex(16)`. The runtime path uses `<run-id[:12]>` to guarantee socket paths remain well within the 107-byte `AF_UNIX` limit. `XDG_RUNTIME_DIR` must be an absolute path for `autonomy run` (`runtime-dir-unset`), but is unused by `analyst` and `command`.

## Disposition record

The terminal verdict is written to `<run_dir>/disposition.json` by `run.write_disposition` in `python/src/autonomy/run.py`. It is a Version 1 record with schema:

```json
{
  "version": 1,
  "run": "0123456789abcdef0123456789abcdef",
  "disposition": "unwired",
  "findings": [
    {
      "code": "baseline-unavailable",
      "ref": "science",
      "message": "this build has no science reads or run endpoint yet"
    }
  ],
  "closed_at": "2026-11-05T12:00:00.000000Z",
  "members": {},
  "closing_heads": null
}
```

The disposition must be one of `"clean"`, `"unwired"`, or `"quarantined"`.
Publication invariant: To ensure atomic publication without concurrent corruption or partial reads, the record is written to temporary path `<run_dir>/.disposition.json.<16-hex>.tmp` with mode `0600`, fsynced, hard-linked to `<run_dir>/disposition.json` via `os.link` (which fails if the target already exists), unlinked from the temporary path, and the directory is fsynced.

## Events log

The lifecycle event journal is maintained in `<run_dir>/events.jsonl` via `baseline.append_event` in `python/src/autonomy/baseline.py`. It is an append-only, line-delimited JSON log created with mode `0600` and fsynced after every entry. Every record carries `"event"` (string identifier) and `"at"` (RFC 3339 UTC timestamp):

| Event | Associated Fields | Command | Description |
| --- | --- | --- | --- |
| `allocated` | `run`, `scratch`, `release`, `inputs`, `denied`, toolchain details | `analyst`, `command` | Emitted immediately after run and scratch directories are created. |
| `unproven` | `code`, `path`, `message` | `analyst`, `command` | Emitted when pre-launch verification fails (`SandboxUnproven` or `EgressUnproven`). |
| `proved` | `walk_seconds` | `analyst`, `command` | Emitted when static checks, input walks, and sandbox probes succeed. |
| `egress-proxy` | `pid`, `start_time` | `analyst` | Emitted when egress proxy container starts. |
| `egress-ready` | none | `analyst` | Emitted when proxy acknowledges route configuration. |
| `proxy` | `pid` | `analyst` | Emitted recording proxy PID. |
| `egress-listening` | none | `analyst` | Emitted when proxy accepts listener socket in actor namespace. |
| `launched` | `child_pid`, `start_time`, `argv` | `analyst`, `command` | Emitted when sandbox gate releases child process execution. |
| `egress-closed` | `cause`, `last_seq` | `analyst` | Emitted on orderly proxy closure (`"close"`, `"lease"`, `"eof"`, `"term"`). |
| `egress-lost` | `cause` | `analyst` | Emitted when proxy crashes or closes unexpectedly. |
| `egress-close-timeout` | `timeout` | `analyst` | Emitted when proxy fails to shut down within timeout. |
| `report-unwritten` | `line` (`"run"` or `"closing"`) | all | Emitted when non-blocking `--report-fd` channel drops a line. |
| `closed` | exit codes, egress status, release counts, log hashes | `analyst`, `command` | Emitted when actor process exits and output release concludes. |

## Epoch, walk, and release records

Toolchain provenance, filesystem walking reports, and output release digests are serialized as JSON:
- `<run_dir>/epoch.json`:
  - `autonomy analyst`: Captures toolchain environment versions:
    ```json
    {"model": "claude-3-5-sonnet-20241022", "thinking": "off", "pi": {"version": "1.1.0", "lock_sha256": "..."}, "node": "/usr/bin/node", "bwrap": "/usr/bin/bwrap", "rg": "/usr/bin/rg", "fd": "/usr/bin/fd"}
    ```
  - `autonomy command`: Records declared inputs, argument digests, executable path, and bwrap version:
    ```json
    {"inputs": [{"path": "/path/data", "kind": "directory", "sha256": "...", "files": 4, "bytes": 1024}], "argv": ["python3", "run.py"], "argv_sha256": "...", "executable": {"path": "/usr/bin/python3", "realpath": "/usr/bin/python3", "sha256": "..."}, "workdir": "/path/data", "bwrap": {"version": "0.11.0", "path": "/usr/bin/bwrap"}}
    ```
- `<run_dir>/walk.json` (`WalkReport.to_json`): Logs scanned trees, entry counts, skipped paths, scanning durations, and total denied inodes:
  ```json
  {"trees": [{"root": "/usr", "rules": ["submount", "alias"], "entries": 4200, "skipped": [], "seconds": 0.08}], "denied_inodes": 14, "seconds": 0.09}
  ```
- `<run_dir>/release.json` (`ReleaseReport.to_json`): Contains `released` list and `refused` list:
  ```json
  {"released": [{"path": "result.csv", "size": 1024, "sha256": "..."}], "refused": [{"path": "bad.sock", "reason": "socket"}]}
  ```

## Egress records and logs

Egress proxy transactions and execution logs are captured alongside run records:
- `<run_dir>/egress.jsonl`:
  - Per-request line:
    ```json
    {"at": "2026-11-05T12:00:00Z", "seq": 1, "method": "POST", "path": "/v1/messages", "query": "", "model": "claude-3-5-sonnet-20241022", "status": 200, "refused": null, "upstream_request_id": "req_123", "request_bytes": 512, "response_bytes": 1024, "forwarded": true, "ended": "complete"}
    ```
  - Closing line:
    ```json
    {"at": "2026-11-05T12:00:05Z", "closed": "close", "last_seq": 1}
    ```
- `<run_dir>/launcher.log`: Supervisor execution log, containing orchestration events and subprocess diagnostics.
- `<run_dir>/proxy.log`: Egress proxy standard error capture.
- `<run_dir>/stdout.log` and `<run_dir>/stderr.log`: Captured standard output and error for `autonomy command` (mode `0600`), whose byte sizes and SHA-256 digests are recorded on the `closed` event in `<run_dir>/events.jsonl`.

## Report-fd lines

When `--report-fd` is supplied, the supervisor writes newline-terminated JSON lines across `channel.LineChannel`:
- Opening line (emitted across all commands upon directory allocation):
  ```json
  {"run": "0123456789abcdef0123456789abcdef", "run_dir": "/path/to/state/runs/0123456789abcdef0123456789abcdef", "scratch": "/path/to/cache/scratch/0123456789abcdef0123456789abcdef"}
  ```
- Closing line:
  - `autonomy run`: `{"run": "<run-id>", "disposition": "clean" | "unwired" | "quarantined", "exit": 0 | 3 | 4}`
  - `autonomy analyst`: `{"run": "<run-id>", "exit": 0 | 3, "pi_exit": 0, "egress": "close", "released": 2, "refused": 0}`
  - `autonomy command`: `{"run": "<run-id>", "exit": 0 | 3, "command_exit": 0, "released": 1, "refused": 0}`

## Permits, tiers, and session ledger

Autonomy integrates with verifiable session ledgers via permissions and tier declarations:
- `Permit` (`python/src/autonomy/tiers.py`):
  Carries `kinds` (admitted record kinds), `act_families` (permitted write families), and `ungoverned` (boolean). `COMMAND_REACHABLE_FAMILIES = frozenset({"corpus-write", "run", "holdings"})`. `KIND_FAMILIES` maps 24 schema record kinds to write families:
  - Coordination and assertions: `project`, `question`, `hypothesis`, `topic`, `theme`, `task`, `decision`, `note`, `proposition`, `source-assertion`, `assessment`, `analysis-spec`, `verification`, `dataset`, `source`, `retraction`, `instrument-certification`, `coreference-attestation`, `composite` (mapped to `corpus-write`).
  - Execution and holdings: `run` and `act-report` (mapped to `run` and `corpus-write`); `holdings-observation` (mapped to `holdings`).
  - Publication: `publication` and `publication-binding` (mapped to `publish`). The `"publish"` family is forbidden in unattended permits (`permit-unknown-family`).
- `Tier` (`python/src/autonomy/tiers.py`):
  - `REPORT_ONLY`: `name="report-only"`, empty routes and permit.
  - `COORDINATION`: `name="coordination"`, routes `ORDINARY_COORDINATION_KINDS = ("project", "question", "hypothesis", "topic", "theme", "task", "decision", "note")` to `"corpus-write"`.
  - `mints(routes)`: `name="mints"`, maps custom record kinds to reachable act families.
- `ledger.v1` JSONL lines (`python/src/autonomy/ledger.py`):
  - `session-open`: `{"line": "session-open", "session": "<64-hex>", "actor": "session:<64-hex>", "permit": <Permit>, "world": {"store": "<64-hex>|none", "work": "<64-hex>|none"}, "at": "<timestamp>", "project": "<name>"}`
  - `invocation-open`: `{"line": "invocation-open", "invocation": "<32-hex>", "command": "<cmd>", "input_digest": "<64-hex>", "at": "<timestamp>"}`
  - `act`: `{"line": "act", "invocation": "<32-hex>", "intent": "<64-hex>", "entry": "<64-hex>", "corpus": "store"|"work", "records": ["<kind>"]}`
  - `select`: `{"line": "select", "invocation": "<32-hex>", "project": "<name>"}`
  - `invocation-close`: `{"line": "invocation-close", "invocation": "<32-hex>", "outcome": "committed"|"refused"|"failed"}`
  - `session-close`: `{"line": "session-close", "at": "<timestamp>"}`
- `RunEvidence` (`python/src/autonomy/evidence.py`):
  Evaluated at closing by `membership.classify`: `run_actor`, `tier_permit`, `baseline_available`, `ledger`, `chains`, `sealed`, `seal_timeout`, `orchestrator_lost`, `world_baseline`, `world_closing`, `mounts_baseline`, `mounts_closing`, `basis_open`, `basis_seal`, `later_ledgers`.
