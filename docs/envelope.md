# Envelope and Sandbox Protocol

Type: protocol; document types 1. Currently unversioned.

The autonomy envelope enforces process, filesystem, descriptor, network, and model egress confinement around untrusted actor workloads and evaluates post-run evidence. Outbound model traffic is routed through the [model egress proxy and route protocol](egress.md), while execution provenance, output files, and session ledgers are captured in [run directory records](records.md). It holds no private kernel access and never imports `beliefs`: it reaches `beliefs` only through `science`'s commands as tools and published record formats.

## Participants and boundary

The protocol coordinates five distinct participants:

| Participant | Implementation | Role |
| --- | --- | --- |
| **Caller** | CLI / API invoker | Invokes `autonomy` commands, provides standard descriptors 0, 1, 2, and optional `--report-fd`. |
| **Supervisor** | `autonomy.run`, `autonomy.analyst.launch` | Allocates run storage, preflights dependencies, conducts pre-launch walks and probes, launches the sandbox, supervises lifecycles, runs descriptor release, and writes verdicts. |
| **Sandbox & Gate** | `autonomy.sandbox.bwrap` | Executes bubblewrap (`bwrap --unshare-all --die-with-parent --new-session`) running an isolated Python gate wrapper (`/usr/bin/python3 -I -c`). Blocks child execution until released. |
| **Actor** | Confined workload | Untrusted child process (`pi` coding agent in RPC mode, or pinned command executables) running in isolated user, mount, IPC, PID, network, and UTS namespaces. |
| **Model Proxy** | `autonomy.egress.session` | Egress gateway running in a separate sandbox with host network access, bound to `http://127.0.0.1:4780` in the actor network namespace before gate release. |

## Descriptors and channels

Standard descriptors are validated by `stdio.check_stdio(fds=(0, 1, 2))` in `python/src/autonomy/stdio.py` before any run directory is allocated:
- Admitted descriptors: anonymous pipes (`fstatfs` `f_type == PIPEFS_MAGIC = 0x50495045`), connected `AF_UNIX` `SOCK_STREAM` sockets with zero default timeouts (`SO_RCVTIMEO` and `SO_SNDTIMEO` both zero), or `/dev/null` (`makedev(1, 3)`).
- Refused descriptors: closed fds (`EBADF`), regular files, directories, terminal character devices, non-`AF_UNIX` or non-`SOCK_STREAM` sockets, unconnected sockets, non-zero timeouts, or stdout/stderr (fds 1 or 2) sharing an open file description with stdin (fd 0). Violations raise `StdioRefused("stdio-refused", ...)`.

The optional status channel is verified by `stdio.check_report_fd(fd, actor_fds=(0, 1, 2))`:
- Must be an open pipe (`PIPEFS_MAGIC` with `O_WRONLY` or `O_RDWR`) or connected `AF_UNIX` `SOCK_STREAM` socket with zero default timeout.
- Must be distinct in integer descriptor number and `(st_dev, st_ino)` identity from actor stdio fds.

`channel.LineChannel(fd)` in `python/src/autonomy/channel.py` manages non-blocking single-line reporting:
- Reopens pipes via `/proc/self/fd/<fd>` with `O_WRONLY | O_NONBLOCK | O_CLOEXEC` to prevent modifying caller flags; duplicates sockets via `os.dup` with `MSG_DONTWAIT | MSG_NOSIGNAL`.
- Polls `POLLOUT` up to `POLL_WAIT = 1.0` second. If the channel is full or unready, lines drop silently without stalling supervision, logging a `report-unwritten` event in `<run_dir>/events.jsonl`.

## Sandbox and pre-launch checks

The sandbox environment is specified by `SandboxSpec` in `python/src/autonomy/sandbox/spec.py`:
- System mounts: `SYSTEM_RO = (Path("/usr"), Path("/etc"))` mounted read-only, with merged-`/usr` symlinks `SYSTEM_LINKS = ("/bin", "/lib", "/lib64", "/sbin")`.
- Sandbox paths: `IN_SANDBOX_SOCKET = PurePosixPath("/run/va/endpoint.sock")`, `IN_SANDBOX_TOKEN = PurePosixPath("/run/va/token")`, `IN_SANDBOX_OUTPUTS = PurePosixPath("/run/va/outputs")`.
- Execution settings: scratch tmpfs, read-only binds, recreated symlinks, working directory, and sanitized environment (`PATH=/usr/bin` following `--clearenv`).

Pre-launch verification proceeds through four mandatory phases:
1. **Static Bind Checks (`autonomy.sandbox.static`):** `check_sources` verifies merged-`/usr` layout (`layout-unsupported`), resolves bind sources (`bind-missing`, `bind-unreadable`), and checks denied paths (`denied-unreadable`). `check_binds` and `check_recreated_links` reject any source sharing an inode or ancestry with a denied target (`bind-overlaps-denied`).
2. **Pre-Launch Input Walk (`autonomy.analyst.walk`):** `walk(user_trees, system_trees, denied, *, digest_inputs=())` collects denied inodes (`denied-unreadable`, `denied-unlistable`) and mount points from `/proc/self/mountinfo`. It walks trees without following symlinks:
   - Mount points below root or `st_dev != root_dev` raise `SandboxUnproven("walk-submount", ...)`.
   - Regular files with `st_nlink > 1` in user trees raise `SandboxUnproven("walk-hardlink", ...)`.
   - Inodes matching denied targets raise `SandboxUnproven("walk-alias", ...)`.
   - Unreadable directories raise `SandboxUnproven("walk-unlistable", ...)`.
   - Non-regular or non-directory entries in `digest_inputs` raise `SandboxUnproven("walk-special", ...)`.
3. **Preflight and Denial Probe (`autonomy.sandbox.bwrap`):** `preflight()` ensures `bwrap` is installed (`bwrap-missing`) and user namespaces function (`userns-unavailable`). `probe(spec, denied)` executes `/usr/bin/python3 -I -c` inside the container before launch, confirming denied paths return `ENOENT` on `os.lstat` (`probe-reachable`) and TCP connections to `NET_TARGETS = ("net:192.0.2.1", "net:2001:db8::1")` on port 80 fail with `ENETUNREACH` or `EAFNOSUPPORT` (`probe-network`).
4. **Gated Launch (`autonomy.sandbox.bwrap`):** `bwrap.launch` starts the container running `_GATE` with synchronization pipes. The supervisor reads `child-pid` from `--info-fd`, opens a `pidfd` (`os.pidfd_open(child_pid)`, `pidfd-unavailable`), executes `before_release(child_pid, pidfd)` (attaching the proxy listener), writes `b"go"`, and verifies `_GATE` executes the actor argv (`launch-failed`). `Sandboxed.kill()` sends `SIGKILL` to `pidfd`, terminating the PID namespace.

## Command lifecycles

The envelope defines distinct lifecycles across three commands:

### autonomy run

1. **Refusal:** Validates `lease >= LEASE_FLOOR (10.0)` (`lease-below-floor`), stdio fds, report fd, tier configuration (`TierRefused`), and unique route kinds (`route-repeated`).
2. **Resolution:** Checks `XDG_RUNTIME_DIR` is an absolute path (`runtime-dir-unset`), resolves `HOME` (`home-unknown`), and loads route TOML/credentials (`RouteRefused`). Failure exits 2 (`EXIT_REFUSED`).
3. **Allocation:** Atomically creates `<state>/runs/<run-id>/`, `<cache>/scratch/<run-id>/`, and `$XDG_RUNTIME_DIR/va/<run-id[:12]>/` (mode `0700`; `allocation-failed`), and writes opening report line.
4. **Execution:** Currently invokes `endpoint_side_unbuilt`, recording finding `baseline-unavailable`.
5. **Verdict:** Derives disposition `"unwired"`, atomically hard-links `<run_dir>/disposition.json`, writes closing report line, and exits 4 (`EXIT_CODES["unwired"]`).

### autonomy analyst

1. **Refusal:** Validates lease (`>= 10.0`), stdio fds, report fd, route TOML, model routing (`model-unrouted`), toolchain (`check_pi`, `PI_VERSION = "1.1.0"`, `ANALYST_TOOLS = ("read", "bash", "grep", "find", "ls", "write")`, `pi-mismatch`), thinking level (`check_thinking`, `THINKING_LEVELS`), node binary (`check_node`, `TOOLS_SHADOWED = ("rg", "fd")` absent), inputs, denied paths, and empty destination (`check_release_dir`, `release-unusable`).
2. **Allocation:** Creates `<state>/analyst/<run-id>/` and `<cache>/analyst/<run-id>/scratch/` with subdirectories `agent`, `agent/bin`, `home`, `sessions`, `outputs` (mode `0700`). Writes `models.json` (`MODEL_URL = "http://127.0.0.1:4780"`), `<run_dir>/epoch.json`, logs `allocated`, and writes opening report line.
3. **Pre-Launch Verification:** Executes `preflight()`, `check_binds()`, `walk()` (writing `<run_dir>/walk.json`), and `probe()`. Failures log `unproven` and exit 4 (`EXIT_UNSTARTED`). Success logs `proved`.
4. **Launch:** Starts `EgressSession.start`, launches gated `pi` in `--mode rpc` with `before_release=session.attach`, logs `launched`.
5. **Supervision:** Renews proxy lease every `min(lease / 3.0, 1.0)` seconds while caller drives RPC over fds 0 and 1. On deadline or signal, sends `SIGTERM`, waits `TERMINATE_GRACE = 10.0` seconds, then kills namespace. Closes proxy session.
6. **Release & Completion:** Runs `release(scratch / "outputs", release_dir)` (writing `<run_dir>/release.json`), logs `closed`, writes closing report line, and exits 0 (`EXIT_CLEAN`) or 3 (`EXIT_FINDINGS`).

### autonomy command

1. **Refusal:** Validates `deadline > 0` (`deadline-invalid`), report fd, declared inputs (regular files or directories), working directory within an input, and executable `argv[0]` under `/usr` or an input directory (recreating intermediate directory symlinks).
2. **Allocation:** Creates `<state>/command/<run-id>/` and `<cache>/command/<run-id>/scratch/` with subdirectories `home`, `outputs`. Writes initial `<run_dir>/epoch.json`, logs `allocated`, and writes opening report line.
3. **Pre-Launch Verification:** Executes `preflight()`, `check_binds()`, `walk(digest_inputs=...)` (writing `<run_dir>/walk.json` and updating `<run_dir>/epoch.json`), and `probe()`. Sets `/run/va/outputs` symlink pointing to `<scratch>/outputs` (`outputs_link=True`) and exports `VERIFIABLY_SCRATCH` and `VERIFIABLY_OUTPUTS`.
4. **Execution:** Stdin is `/dev/null`; stdout and stderr are captured to `<run_dir>/stdout.log` and `<run_dir>/stderr.log` (mode `0600`). Supervises until completion or deadline.
5. **Release & Completion:** Runs `release`, hashes logs, logs `closed`, writes closing report line, and exits 0 (`EXIT_CLEAN`) or 3 (`EXIT_FINDINGS`).

Concrete command invocation example:
```bash
autonomy command \
  --input /path/to/data \
  --workdir /path/to/data \
  --release /path/to/release \
  --deadline 300.0 \
  --report-fd 3 \
  -- /usr/bin/python3 script.py
```

## Output release

Outputs cross from scratch storage to the operator's release destination via `release.release(outputs_dir, release_dir)` in `python/src/autonomy/analyst/release.py`:
- Opens directories with `O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC` and traverses iteratively by descriptor to prevent symlink traversal and TOCTOU races.
- Creates destination subdirectories with `os.mkdir(..., mode=0o700, dir_fd=dest_fd)` and files with `os.open(..., flags=O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, mode=0o600)`.
- Copies single-link regular files in 1 MiB chunks (`_CHUNK = 1 << 20`), hashes bytes with SHA-256, and records `{"path", "size", "sha256"}` in `ReleaseReport.released`.
- Refuses non-regular entries into `ReleaseReport.refused` without aborting traversal: `"symlink"`, `"hardlinked"`, `"fifo"`, `"socket"`, `"device"`, `"collision"`, or `"unopenable"`.

## Closing and membership

Post-run evaluation determines the final research disposition:
- `closing.close(evidence: RunEvidence) -> Verdict` in `python/src/autonomy/closing.py` evaluates run evidence against severity mapping `SEVERITY`. It returns `Verdict(disposition, findings, members)` where `Disposition = Literal["clean", "unwired", "quarantined"]` ranked by `_RANK = {"clean": 0, "unwired": 1, "quarantined": 2}`.
- `membership.classify(chains, baseline_heads, closing_heads, ledger, run_actor, later_ledgers=())` in `python/src/autonomy/membership.py` evaluates session ledger entries against `Intent`, `Registration`, and `Settlement` chains. It detects `chain-discontinuous`, `entry-foreign`, `outcome-unknown`, `intent-unfulfilled`, `act-unverified`, and single-act crash recovery.

## Failure

### Exit Codes

| Command | Exit Code | Meaning |
| --- | --- | --- |
| `autonomy run` | 0 | Clean run; closing disposition clean. |
| `autonomy run` | 2 | Refused before execution; no run directory created. |
| `autonomy run` | 3 | Quarantined; run findings indicate world, basis, or chain discontinuity. |
| `autonomy run` | 4 | Unwired; baseline or science reads unbuilt or unavailable. |
| `autonomy analyst` / `command` | 0 | Clean execution; outputs released without findings. |
| `autonomy analyst` / `command` | 2 | Refused at step 1 before run directory allocation. |
| `autonomy analyst` / `command` | 3 | Ran with findings (non-zero actor exit, release refusals, or egress errors). |
| `autonomy analyst` / `command` | 4 | Never started; pre-launch verification or launch gate failed. |

### Refusal Exceptions

| Exception | Codes |
| --- | --- |
| `StdioRefused` | `stdio-refused` |
| `TierRefused` | `unknown-tier`, `publishes-unattended`, `routes-unexpected`, `mints-empty`, `unknown-kind`, `route-not-admitted`, `family-unreachable` |
| `RunRefused` | `route-repeated`, `lease-below-floor`, `runtime-dir-unset`, `home-unknown`, `allocation-failed`, re-raised `StdioRefused`, `TierRefused`, `RouteRefused` |
| `AnalystRefused` | `lease-below-floor`, `deadline-invalid`, `model-unrouted`, `pi-mismatch`, `model-unknown`, `thinking-unsupported`, `node-missing`, `toolchain-shadowed`, `input-missing`, `input-unsupported`, `input-nested`, `denied-unreadable`, `release-unusable`, `workdir-invalid`, `workdir-unbound`, `command-missing`, `command-invalid`, `command-not-executable`, `command-unbound`, `allocation-failed` |

### Sandbox Unproven Codes

`SandboxUnproven` error codes raised during pre-launch checks:
`layout-unsupported`, `denied-unreadable`, `denied-unlistable`, `bind-missing`, `bind-unreadable`, `bind-overlaps-denied`, `bwrap-missing`, `userns-unavailable`, `pidfd-unavailable`, `walk-submount`, `walk-hardlink`, `walk-alias`, `walk-special`, `walk-unlistable`, `probe-failed`, `probe-network`, `probe-reachable`, `launch-failed`.

### Closing Finding Severities

Finding codes mapped in `closing.SEVERITY`:
- **quarantined**: `chain-discontinuous`, `entry-foreign`, `world-moved`, `basis-moved`.
- **unwired**: `baseline-unavailable`, `ledger-unavailable`, `read-unavailable`, `ledger-malformed`, `seal-missing`, `outcome-unknown`, `intent-unfulfilled`, `seal-timeout`, `act-unverified`, `session-unclosed`, `permit-mismatch`, `orchestrator-lost`, `egress-unproven`.
- **informational (None)**: `egress-lost`, `egress-close-timeout`, `mount-moved`, `after-run`.
