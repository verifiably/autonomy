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
- Execution settings include scratch tmpfs, read-only binds, recreated symlinks and a working directory. Bubblewrap clears the inherited environment. The probe uses `--setenv` and the launch gate applies the declared environment at exec. Both default to `PATH=/usr/bin`.

Pre-launch verification proceeds through four mandatory phases:
1. **Static Bind Checks (`autonomy.sandbox.static`):** `system_symlinks` verifies the merged-`/usr` links (`layout-unsupported`). The static bind check compares real paths and inode ancestry (`bind-overlaps-denied`). Missing denied paths still contribute their nearest existing ancestor's inode and its ancestry. Unresolvable denied paths fail with `denied-unreadable`. The input walk checks aliases of entries beneath denied roots. Bind sources passed to bubblewrap must exist and use their absolute real paths (`bind-missing`, `bind-unreadable`). The host must keep that path layout stable through launch.
2. **Pre-Launch Input Walk (`autonomy.analyst.walk`):** `walk(user_trees, system_trees, denied, *, digest_inputs=())` collects denied inodes (`denied-unreadable`, `denied-unlistable`) and mount points from `/proc/self/mountinfo`. It walks trees without following symlinks:
   - Mount points below root or `st_dev != root_dev` raise `SandboxUnproven("walk-submount", ...)`.
   - Regular files with `st_nlink > 1` in user trees raise `SandboxUnproven("walk-hardlink", ...)`.
   - Inodes matching denied targets raise `SandboxUnproven("walk-alias", ...)`.
   - Unreadable directories raise `SandboxUnproven("walk-unlistable", ...)`.
   - Non-regular or non-directory entries in `digest_inputs` raise `SandboxUnproven("walk-special", ...)`.
3. **Preflight and Denial Probe (`autonomy.sandbox.bwrap`):** `preflight()` checks for `bwrap` (`bwrap-missing`) and functional user namespaces (`userns-unavailable`). The probe requires at least one denied path (`probe-failed`). Inside the container, it checks that `stat` returns `ENOENT` for each denied path (`probe-reachable`). TCP connections to the IPv4 and IPv6 documentation addresses on port 443 must return `ENETUNREACH`. An IPv6 `EAFNOSUPPORT` also counts as unreachable (`probe-network`).
4. **Gated Launch (`autonomy.sandbox.bwrap`):** Launch requires a nonempty executable argument and interpreter pidfd support. After opening a pidfd from bubblewrap's `child-pid` report, the supervisor confirms that bubblewrap is still running before using the handle. It compares the host and child network namespace identities and polls the pidfd to confirm that the namespace init survived those reads. A shared namespace, unreadable identity, or exited init aborts before actor execution (`probe-network`). After any `before_release` callback, the supervisor releases the gate through its dedicated pipe. The gate execs the actor with exactly the environment declared by the sandbox, including its configured or default `PATH`. If the release pipe closes early, launch reports `launch-failed`. A failed launch closes the gate and pidfd, attempts to kill the sandbox, and waits up to five seconds to reap bubblewrap. Unconfirmed cleanup is reported as `launch-failed`.

## Command lifecycles

The envelope defines distinct lifecycles across three commands:

### autonomy run

#### Science mode

`autonomy run --tier TIER [--deadline SECONDS] [--toolchain PATH] -- ACTOR …`
supervises one science actor. It uses the operator's `SCIENCE_CONFIG` and the
resolved `science` executable. The monotonic run deadline defaults to 3600
seconds. Repeat `--toolchain` to admit the actor's required read-only runtime
paths. Operator tier, stdio, runtime and route refusals exit 2 before an
opening report. An inherited science handle permits local allocation and
closes unwired before reading the science config or opening a writer.

The supervisor serializes allocation and baseline capture. Admission checks
the whole resolving footprint, including the configured read mounts, for
unfinished writers. A detached heads read can identify a matching chain at
a different root. If an unfinished writer's footprint is unknown, admission
refuses to resolve. A resolving process waits for its identity to be journaled
before it can write. Admission waits respect the opening deadline and stop
signals. The actor stays behind the gate until the endpoint
ledger agrees with the tier and actor, written heads match the baseline, the
sandbox passes the same bind and network proof used for launch, and the
endpoint acknowledges the actor's PID namespace. A routed run also requires a
listener acknowledgement from the proxy.

The supervisor renews the endpoint and route leases until stop or deadline. Actor, endpoint or proxy
exit, an elapsed deadline, or a stop signal starts closing. The supervisor
sends the route close and endpoint seal independently, waits for the seal,
then terminates and reaps the actor namespace. For a governed research actor it signals the worker beneath namespace init using the pidfd pinned before release. If the worker outlives its grace period, the supervisor kills the namespace and records the escalation. The supervisor checks the issued grant before actor release and during the running wait. On close it refuses new reservations while still servicing settlements from both draining peers. The final check accounts for the
written intervals and publishes `disposition.json`. The exit is 0 for clean,
3 for quarantined or 4 for unwired. The report fd carries the opening and
closing lines when available. A half-closed report socket can lose either
line. The run journal records each drop and the durable receipt determines
the exit. [Run directory records](records.md)

`autonomy run stop ID` sends SIGTERM through the verified supervisor pidfd.
Initialized runs can be stopped while another run holds the admission lock.
Science and development share that lock during mode publication.

`autonomy run close ID` recovers a lost science supervisor from protected
state alone. It confirms that any recorded resolver, endpoint and actor
have exited before reading the written chains. An acknowledged seal bounds
the interval. A seal file alone also needs the matching ledger's session-close
and a complete journal without a seal failure. Otherwise recovery uses
detached closing tips. Recovery verifies the original chain identities after
a config edit. An unavailable interval contributes an unwired finding and
readable chains still contribute their evidence. If the corpus interval is
unavailable, store records that could belong to a ledgered corpus intent
remain unverified. Independent foreign evidence still quarantines the run.
An already terminal close reuses the validated receipt and returns its
durable exit even if the output consumer closes.

#### Development mode

`autonomy run --development --repository REPO --base OID --deadline SECONDS
[--report-fd N] -- <actor argv>` authorizes one supervised offline candidate
attempt. The base must be a full local commit ID and the deadline must be
positive and finite. Omit the science tier, route and lease and any model
route. Development state contains only protected records and scratch, so the
run needs no XDG runtime directory. The actor receives the caller's byte
channels. The CLI releases its copies immediately after the gate opens so the
caller's streams can reach EOF before validation ends.

The supervisor gives the actor the base OID, full development ref, and
`/run/va/outputs/candidate.bundle` through `VERIFIABLY_DEVELOPMENT_BASE`,
`VERIFIABLY_DEVELOPMENT_REF` and `VERIFIABLY_DEVELOPMENT_BUNDLE`.
An immutable grant records the proved exposure and bounds. The supervised
invocation grants this attempt. Unattended caller admission and aggregate
scratch quotas require a separate activation gate.

##### Workspace preparation

The development preparer opens the full approved commit ID in a private Git
repository with only the local source's object data mounted read-only.
Supported sources have a regular Git directory or are local bare repositories.
The supervisor pins the source object-directory identities during bounded
enumeration. The confined reader checks the mounted identities before Git
reads object data. It uses private configuration and ignores source refs, hooks,
alternates and external stores. It exports one prerequisite-free
`refs/heads/base` bundle, verifies it in an empty bare repository with strict
full object checking, and seeds an independent checkout at
`refs/heads/development`. The scratch repository has its own objects and
configuration. Its sibling home, harness state and output directories are
outside the working tree.

The supervisor checks the completed scratch alongside the admitted system
trees. It rejects hardlinks in scratch, submounts and denied inode aliases
before proving denied paths and network isolation from inside the sandbox.
The source worktree and Git metadata never enter the actor's mounts.

##### Supervision

A development sandbox requires a fresh user namespace and disables nested
user namespaces. The trusted launcher sets both file-size limits before it
execs bubblewrap in place. The supervisor verifies both limits on the held
namespace before release. The cap is per file.

Under the publication lock, the supervisor checks for stop and records the
namespace's identity durably before opening the gate. The monotonic actor
deadline starts immediately before the gate write. While scheduled, the
supervisor checks for stop or exit at least every second and sends TERM on
stop or deadline. At most ten seconds of grace precede KILL. Output
validation requires a timely zero exit and confirmed namespace shutdown.

`autonomy run stop <id>` records a protected stop request. The request wins
if recorded before terminal publication. `autonomy run close <id>` refuses a
run with a live supervisor. Recovery uses a pidfd, boot ID and process start
ticks to confirm containment or limit signals to the recorded namespace.
Only an intact journal proving the gate never opened permits an unfinished
run to close unwired. All other unfinished runs close quarantined.

##### Candidate validation

Only a timely zero exit with confirmed containment permits transfer of
`outputs/candidate.bundle`. The supervisor opens the output by descriptor,
requires one regular single-link file, and checks its byte count and identity
before publishing protected staging. The independent candidate limit applies
both before and during copying.

A separate bubblewrap receiver uses private configuration, limited writable
storage and process address space, and a separate elapsed-time bound. It checks
that the header advertises the declared branch exactly once with exactly the
pinned base as prerequisite. The receiver imports the base into an empty bare
repository, validates the candidate with `fetch.fsckObjects=true` and
`git fsck --strict --full`, and checks that the imported tip is a proper
descendant of the base. Git never opens the actor's repository from the host
or checks out the candidate in the receiver.

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
- `membership.classify(chains, ledger, run_actor, *, sealed, later_ledgers=())` in `python/src/autonomy/membership.py` evaluates session ledger entries against `Intent`, `Registration`, and `Settlement` chains. It detects `chain-discontinuous`, `entry-foreign`, `outcome-unknown`, `intent-unfulfilled`, `act-unverified`, and single-act crash recovery (owning an unrecorded store registration through an in-progress `write`, `delete`, or `move-source` intent when no registered path is `objects` or under `objects/` and `location` is in `registered_paths`, or through an in-progress `tree-write` intent when `registered_paths` holds a single canonical `objects/sha256/<hh>/<64-lowercase-hex>` path with matching shard).

## Failure

### Exit Codes

| Command | Exit Code | Meaning |
| --- | --- | --- |
| `autonomy run` | 0 | Clean disposition. A development candidate is eligible for separate acceptance. |
| `autonomy run` | 2 | Refused before execution; no run directory created. |
| `autonomy run` | 3 | Quarantined. Science evidence failed or development output is ineligible. |
| `autonomy run` | 4 | Unwired or unfinished. Inspect the retained run directory for a verdict. |
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
`layout-unsupported`, `denied-unreadable`, `denied-unlistable`, `bind-missing`, `bind-unreadable`, `bind-overlaps-denied`, `bwrap-missing`, `userns-unavailable`, `pidfd-unavailable`, `walk-submount`, `walk-hardlink`, `walk-alias`, `walk-special`, `walk-unlistable`, `walk-timeout`, `probe-failed`, `probe-network`, `probe-reachable`, `launch-failed`.

### Closing Finding Severities

Finding codes mapped in `closing.SEVERITY`:
- **quarantined**: `chain-discontinuous`, `entry-foreign`, `world-moved`, `basis-moved`.
- **unwired**: `baseline-unavailable`, `ledger-unavailable`, `read-unavailable`, `ledger-malformed`, `seal-missing`, `outcome-unknown`, `intent-unfulfilled`, `seal-timeout`, `act-unverified`, `session-unclosed`, `permit-mismatch`, `orchestrator-lost`, `egress-unproven`.
- **informational (None)**: `egress-lost`, `egress-close-timeout`, `mount-moved`, `after-run`.

Development admission and findings use the same exit and severity catalog.
The [negative verification matrix](development.md#development-decision-matrix)
lists each supervised development code and its verification arm.

## Operator allowance commands

`autonomy allowance issue NAME` reads the owned 0600 JSON file
`allowances/NAME.json` under the Autonomy config directory. It issues the
campaign once. The receipt names its grant and tariff digests, issuer, original
limits, members, expiration and storage identity. `autonomy allowance revoke ID`
durably closes the campaign and reports which envelopes still owe a close.
These are operator commands. They write a JSON receipt on stdout and refuse
with exit 2 and a diagnostic on stderr. A Band host can attach a validated
`band-turn.v1` projection on stdin using `autonomy allowance record-turn
CAMPAIGN/MEMBER --conversation-id C --envelope R`. Redelivery of identical
evidence is idempotent, including after an envelope closes.

The operator pins a private durable directory in `allowance-storage.json`
(mode 0600). Its exact fields are `version` (1), `path` (absolute canonical
directory), `device` and `inode` (integer stat identities). Use an owned 0700
directory outside file synchronization on a qualified local ext4, XFS or Btrfs
volume. Qualify independent-process locking, durable commit and interrupted
transaction recovery on that volume before selecting it. Replacing the pinned
directory requires explicit operator reconfiguration. A caller cannot initialize
missing accounting state. Preserve the grant database for the full lifetime of
its identity, including after revocation.

A routed run or analyst selects the issued member with `--allowance CAMPAIGN/MEMBER`
or the operator's route setting. A conflicting selection refuses at startup.
At envelope close, the host closes new reservations before draining the proxy
and Science endpoint. After supervisor loss, state-only `run close` seals the
recorded envelope in its original campaign before publishing a disposition.
Previously admitted work can settle while either peer drains.
On a governed research launch the supervisor passes a separate job descriptor
to Science and requires the open reply to echo the canonical research-action
digest before actor release. A model-only run requires the report-only tier.
