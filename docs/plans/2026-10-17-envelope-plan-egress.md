# Envelope Egress Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** draft, for review.

**Goal:** Build decision 13's model route and proxy as a library that Plan B2 wires
into the run, and prove it under real `bwrap`:

- no sandbox shares the host's network, and the probe proves it for IPv4 and IPv6;
- the model route: parsed strictly, its credential file checked at step 2, its paths
  added to the denied set;
- the proxy: strict HTTP/1.1, the `anthropic-messages` body checks, its own upstream
  framing over verified TLS, streaming, `egress.jsonl`, the lease, and the close
  transition;
- the namespace helper, which puts the proxy's listener on `127.0.0.1:4780` inside
  the actor's network namespace before the gate's release;
- the orchestrator's session: the proxy's own sandbox, start, hand-off, renewal and
  close;
- rows E21 and E22 on their launch arms, and a live recipe that runs pi through the
  proxy to the real API.

**Architecture:** A new `autonomy.egress` package with one module per concern:
- **pure:** `errors`, `route`, `request`, `dialect`;
- **stateful:** `upstream` (the gate and the TLS client) and `server` (the proxy's
  request handling);
- **process boundaries:** `proxy` (the proxy process's entry and control loop) and
  `helper` (the namespace helper);
- **orchestrator side:** `session`.

`sandbox` gains a `before_release` hook on `launch`, a network check in the probe, and
a static check with exempt paths. `run` and `cli` gain `--model-route` and step 2's
route refusals.

**Tech Stack:** Python ≥ 3.11 for the package and stdlib only at runtime (`tomllib`,
`ssl`, `socket.send_fds`), with `/usr/bin/python3` ≥ 3.12 inside the sandboxes
(`os.setns`). Tests use pytest, pytest-testmon, bubblewrap and the `openssl` CLI (test
certificates only), on Linux.

**Spec:** `docs/specs/2026-10-12-envelope-design.md`:
- decision 13 (all of it) and decision 12's caller obligation;
- §3 step 2 (the route refusals), step 7 (the proxy's static check) and step 9 (the
  proxy start and listener before the release);
- §6 (`egress.jsonl`, `proxy.log`, the `events.jsonl` entries);
- §7 (the sandbox spec without `network`, the probe's network check, the denied set);
- §8 (the proxy holds the lease);
- §9 rows `egress-lost` and `egress-close-timeout`;
- §12 rows E21 and E22, and E20's helper and proxy children;
- §13 item 5.

Plan B1 is `docs/plans/2026-10-15-envelope-plan-b1.md`, and this plan changes its
`launch`, `run` and `cli`.

## Scope: this plan and B2

B1's `autonomy run` closes every run `unwired` at step 3, before the actor starts,
because steps 3–9 need the science endpoint (Plan B2, autonomy-f6efe8). So this plan
builds and proves everything decision 13 needs that does not need the run's steps 3–9.
B2 composes it:

| spec item | here | B2 |
|---|---|---|
| step 2: `route-unknown`, `route-invalid`, `credential-unavailable` | Tasks 2, 3 | — |
| the denied set's `<config>`, route and credential entries | Task 2 (`egress_denied`) | adds them to the run's denied set |
| the probe's IPv4 and IPv6 `ENETUNREACH` | Task 1 | — |
| no `host` network mode | Task 1 | — |
| step 7: the proxy's static check (`egress-unproven`) | Task 9 (`EgressSession.start`) | calls it at step 7 |
| step 9: the proxy start, the listener hand-off before the release | Tasks 1 (`before_release`), 8, 9 | passes `session.attach` to `launch` |
| close step 0, concurrent with the seal | Task 9 (`EgressSession.close`) | sends it with the seal |
| the proxy's lease renewal | Task 9 (`EgressSession.renew`) | calls it with the endpoint's |
| the proxy's pidfd as a close trigger | Task 9 (`EgressSession.pidfd`) | watches it |
| *Orphans*: `run close` kills a live proxy | Task 9 (`kill_orphan`) | calls it from `run close` |
| `baseline.json`'s `egress` block | Task 3 (`Opened.route`: name, digest, upstream) | writes it |
| E21 and E22 launch arms | Tasks 4–9 | — |
| E21's live pi recipe | Task 10 | — |
| E21 and E22 full-run arms | — | B2 |

## Global Constraints

- No kernel import: the package depends on neither `verifiably-beliefs` nor
  `verifiably-science` (AGENTS.md *Rules*; spec decision 1).
- Runtime is the stdlib only, and `requires-python = ">=3.11"` is unchanged. The proxy and
  the helper run under `/usr/bin/python3 -I`. A helper interpreter without
  `os.setns` (Python < 3.12) fails `listener-failed`, which makes the run `unwired`
  (`egress-unproven`). It is never a fallback.
- The listener is `127.0.0.1:4780`, and the actor's variable is
  `VERIFIABLY_MODEL_URL=http://127.0.0.1:4780` (decision 13).
- The route lives at `<config>/routes/<name>.toml`. `<config>` defaults to
  `$XDG_CONFIG_HOME/verifiably-autonomy`, with `XDG_CONFIG_HOME` defaulting to
  `~/.config`.
- The proxy's credential is bound at `/run/va/credential` and its `ca_file` at
  `/run/va/ca.pem`.
- Refusals are answered `403` with
  `{"type": "error", "error": {"type": "egress_refused", "code": "<code>", "message": "<one line>"}}`.
  The codes are `request-malformed`, `target-refused`, `operation-refused`,
  `header-refused`, `model-refused`, `body-refused`, `request-too-large`,
  `route-closed` and `allowance-refused`.
- The proxy's timeouts:
  - it must report `ready` within 10 s and `listening` within 5 s;
  - `close` waits 5 s, then kills.
- Header names are compared ASCII case-insensitively everywhere.
- Tests run through the front door: `just test-one <pytest args>` while working (paths
  relative to `python/`), then `just test-fast` before each commit. Never call
  `pytest` directly.
- Tests that need bubblewrap carry `@pytest.mark.bwrap` (module-level `pytestmark`
  where every test needs it). Tests that need the `openssl` CLI get it from the
  `tls` fixture in `tests/egress_fixtures.py`, which fails, not skips, when it is
  missing.
- Commit messages are conventional commits. No AI attribution.

## Review Focus

1. **An HTTP client that reuses its connection** (pi's undici keeps connections
   alive). The proxy answers one request per connection and closes it. A second
   request pipelined behind the first is never parsed or forwarded. That case is
   tested in Task 7.
2. **An upstream that answers garbage**: a malformed status line, a header block over
   64 KiB, or a chunk size that is not hex. The actor gets `502` with
   `ended: upstream-error`, and the proxy never hangs. Tested in Task 6.
3. **An actor that hangs up mid-stream.** The proxy's upstream connection closes at
   once, the line says `actor-closed`, and no worker thread is left. Tested in Task 7.
4. **Many concurrent requests** (pi's sub-agents). Twenty parallel requests are all
   served and each gets its own `seq`, and `admit` sees the requests in flight.
   Tested in Task 7.
5. **A credential file written with `echo key > file`.** One trailing newline is
   accepted. A CRLF ending, two lines, an empty file and non-ASCII bytes are refused
   `credential-invalid`, so the run is `egress-unproven`. Tested in Task 8.

## File structure

- Create `python/src/autonomy/egress/__init__.py`, holding the module docstring only.
- Create `python/src/autonomy/egress/errors.py`: `RouteRefused`, `EgressUnproven`,
  `Refused`.
- Create `python/src/autonomy/egress/route.py`: `Route`, `Operation`,
  `parse_route`, `LoadedRoute`, `load_route`, `check_credential`, `egress_denied`,
  `always_dropped`.
- Create `python/src/autonomy/egress/request.py`: `Request`, `parse_head`,
  `forwarded_headers`, `frame`, `refusal`, `MAX_HEAD`.
- Create `python/src/autonomy/egress/dialect.py`: `parse_body`, `check_body`.
- Create `python/src/autonomy/egress/upstream.py`: `Gate`, `RouteClosed`,
  `UpstreamError`, `send_all`, `connect`, `Response`, `read_response`,
  `response_head`.
- Create `python/src/autonomy/egress/server.py`: `Recorder`, `Allowance`,
  `NoAllowance`, `Hooks`, `ProxyServer`.
- Create `python/src/autonomy/egress/proxy.py`: `BOOT`, `read_credential`,
  `control_loop`, `main`, and the control messages.
- Create `python/src/autonomy/egress/helper.py`: `MODEL_PORT`, `MODEL_URL`,
  `make_listener`.
- Create `python/src/autonomy/egress/session.py`: `ProxyBinds`, `proxy_binds`,
  `proxy_argv`, `EgressSession`, `EgressClosed`, `kill_orphan`.
- Modify `python/src/autonomy/sandbox/spec.py`: drop `network`.
- Modify `python/src/autonomy/sandbox/bwrap.py`: no `--share-net`, the probe's network
  lines, `read_info` made public, and `launch(..., before_release=)`.
- Modify `python/src/autonomy/sandbox/static.py`: `check_sources(sources, denied,
  exempt)`, with `check_binds` delegating to it.
- Modify `python/src/autonomy/closing.py`: `SEVERITY` gains `egress-unproven`,
  `egress-lost` and `egress-close-timeout`.
- Modify `python/src/autonomy/run.py`: `Places.config`, `RunRequest.model_route`,
  `Opened.route`, and route loading in `execute`.
- Modify `python/src/autonomy/cli.py`: `--model-route NAME`.
- Create `python/tests/egress_fixtures.py`: `tls` (openssl certificates),
  `FakeUpstream`, `write_route`, `PI_ROUTE`.
- Create the tests `python/tests/test_egress_route.py`, `test_egress_request.py`,
  `test_egress_dialect.py`, `test_egress_upstream.py`, `test_egress_server.py`,
  `test_egress_proxy.py`, `test_egress_helper.py` and `test_egress_session.py`.
- Modify `python/tests/test_sandbox_probe.py`, `test_sandbox_static.py`,
  `test_sandbox_launch.py`, `test_run.py`, `test_cli.py` and `test_closing.py`.
- Create `python/scripts/egress_live.py`, the live pi recipe, which never runs in the
  suite.
- Modify `justfile` with a `live-egress` recipe, `README.md` with the model route
  section, and `docs/specs/2026-10-12-envelope-design.md` with the status line for
  item 5.

---

### Task 1: The sandbox: no host network, the probe's network check, the release hook

**Files:**
- Modify: `python/src/autonomy/sandbox/spec.py`
- Modify: `python/src/autonomy/sandbox/bwrap.py`
- Modify: `python/src/autonomy/sandbox/static.py`
- Test: `python/tests/test_sandbox_probe.py`, `python/tests/test_sandbox_static.py`,
  `python/tests/test_sandbox_launch.py`

**Interfaces:**
- Consumes: Plan A and B1's `SandboxSpec`, `build_argv`, `probe`, `prove`, `launch`
  and `check_binds`.
- Produces:
  - `SandboxSpec` without `network`;
  - `read_info(fd: int, process: subprocess.Popen) -> dict[str, object] | None`
    (renamed from `_read_info`);
  - `launch(spec, argv, *, stdin: int, stdout: int, stderr: int,
    before_release: Callable[[int, int], None] | None = None) -> Sandboxed`, where
    the hook receives `(child_pid, pidfd)` after the pidfd is held and before
    `RELEASE`, and an exception it raises aborts the launch and propagates
    unchanged;
  - `check_sources(sources: Iterable[Path], denied: Iterable[Path], *, exempt:
    Iterable[Path] = ()) -> None`;
  - `NET_TARGETS = ("net:192.0.2.1", "net:2001:db8::1")`;
  - the probe's network refusal, code `probe-network`.

- [ ] **Step 1: Write the failing tests**

In `python/tests/test_sandbox_probe.py`, replace `test_argv_shape` and
`test_no_network_unless_asked` with:

```python
def test_argv_shape(layout):
    argv = build_argv(layout, ["/usr/bin/true"], info_fd=None)
    assert argv[:3] == ["bwrap", "--unshare-all", "--die-with-parent"]
    assert argv[-2:] == ["--", "/usr/bin/true"]


def test_no_sandbox_shares_the_host_network(layout):
    assert "--share-net" not in build_argv(layout, ["/usr/bin/true"], info_fd=None)
    assert not hasattr(layout, "network")  # Plan A's `host` mode is removed (decision 13)
```

Where `layout` built a `SandboxSpec(..., network="host")`, drop the argument. Then add:

```python
@pytest.mark.bwrap
def test_the_probe_reports_both_addresses_unreachable(layout, monkeypatch):
    seen = {}
    real_run = subprocess.run

    def spy(argv, **kwargs):
        result = real_run(argv, **kwargs)
        seen["stdout"] = result.stdout.decode()
        return result

    monkeypatch.setattr(subprocess, "run", spy)
    probe(layout, [])
    lines = seen["stdout"].splitlines()
    assert lines[-2] == "ENETUNREACH net:192.0.2.1"
    assert lines[-1].split()[0] in ("ENETUNREACH", "EAFNOSUPPORT")
    assert lines[-1].split()[1] == "net:2001:db8::1"


@pytest.mark.bwrap
def test_a_sandbox_sharing_the_host_network_fails_the_probe(layout, monkeypatch):
    # Negative: a test hook that adds --share-net (decision 13's removed mode). On a host
    # with a default route, 192.0.2.1 times out or connects instead of ENETUNREACH.
    from autonomy.sandbox import bwrap

    real = bwrap.build_argv

    def shared(spec, argv, *, info_fd):
        args = real(spec, argv, info_fd=info_fd)
        return [args[0], args[1], "--share-net", *args[2:]]

    monkeypatch.setattr(bwrap, "build_argv", shared)
    with pytest.raises(SandboxUnproven) as caught:
        bwrap.probe(layout, [])
    assert caught.value.code == "probe-network"
    assert caught.value.path == "net:192.0.2.1"
```

Add `import subprocess` and `from autonomy.sandbox.static import SandboxUnproven` to
that file's imports if absent.

In `python/tests/test_sandbox_static.py` add:

```python
from autonomy.sandbox.static import check_sources


def test_an_exempt_source_passes_under_a_denied_ancestor(tmp_path):
    config = tmp_path / "config"
    (config / "credentials").mkdir(parents=True)
    credential = config / "credentials" / "anthropic"
    credential.write_text("k\n")
    check_sources([Path("/usr"), credential], [config], exempt=[credential])


def test_without_the_exemption_the_same_source_is_refused(tmp_path):
    config = tmp_path / "config"
    (config / "credentials").mkdir(parents=True)
    credential = config / "credentials" / "anthropic"
    credential.write_text("k\n")
    with pytest.raises(SandboxUnproven) as caught:
        check_sources([credential], [config])
    assert caught.value.code == "bind-overlaps-denied"


def test_the_exemption_is_exact_not_an_ancestor(tmp_path):
    config = tmp_path / "config"
    (config / "credentials").mkdir(parents=True)
    credential = config / "credentials" / "anthropic"
    credential.write_text("k\n")
    with pytest.raises(SandboxUnproven):
        check_sources([config / "credentials"], [config], exempt=[credential])
```

In `python/tests/test_sandbox_launch.py` add:

```python
def test_before_release_runs_while_the_gate_still_holds_the_actor(tmp_path, stdio):
    flag = tmp_path / "ran"
    spec = SandboxSpec(scratch=tmp_path)
    seen = {}

    def hook(child_pid: int, pidfd: int) -> None:
        seen["child"] = child_pid
        seen["pidfd_alive"] = signal.pidfd_send_signal(pidfd, 0) is None
        seen["ran_before_release"] = flag.exists()

    sandbox = launch(spec, ["/usr/bin/touch", str(flag)], before_release=hook, **stdio)
    try:
        assert sandbox.wait(timeout=30) == 0
    finally:
        sandbox.close()
    assert seen == {"child": sandbox.child_pid, "pidfd_alive": True, "ran_before_release": False}
    assert flag.exists()


class HookFailed(Exception):
    pass


def test_a_failing_hook_aborts_and_propagates_unchanged(tmp_path, stdio):
    flag = tmp_path / "ran"

    def hook(child_pid: int, pidfd: int) -> None:
        raise HookFailed("no listener")

    with pytest.raises(HookFailed):
        launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/touch", str(flag)], before_release=hook, **stdio)
    time.sleep(0.5)
    assert not flag.exists()


def test_a_hook_that_swallows_its_failure_releases_the_actor(tmp_path, stdio):
    # Negative (E22): a launch that ignores a helper failure runs the actor anyway,
    # which is why `before_release` must propagate, never be wrapped in a try.
    flag = tmp_path / "ran"

    def careless(child_pid: int, pidfd: int) -> None:
        try:
            raise HookFailed("no listener")
        except HookFailed:
            pass

    sandbox = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/touch", str(flag)], before_release=careless, **stdio)
    try:
        assert sandbox.wait(timeout=30) == 0
    finally:
        sandbox.close()
    assert flag.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-one tests/test_sandbox_probe.py tests/test_sandbox_static.py tests/test_sandbox_launch.py`
Expected: FAIL. The argv still has `--share-net` for `network="host"`, `check_sources`
does not import, the probe prints no network lines, and `launch` does not accept
`before_release`.

- [ ] **Step 3: Implement**

`python/src/autonomy/sandbox/spec.py`: delete the `network` field and the
`Literal` import. The class becomes:

```python
@dataclass(frozen=True)
class SandboxSpec:
    """No spec shares the host's network namespace: the actor's network is its own
    loopback, and its only way out is the model route's listener (decision 13)."""

    scratch: Path
    ro_binds: tuple[Path, ...] = ()
    socket: Path | None = None
    token: Path | None = None
    env: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def bind_sources(self) -> tuple[Path, ...]:
        """Every host path the sandbox binds, in argv order: each one is checked."""
        sources: list[Path] = [*SYSTEM_RO, *self.ro_binds, self.scratch]
        if self.socket is not None:
            sources.append(self.socket)
        if self.token is not None:
            sources.append(self.token)
        return tuple(sources)
```

`python/src/autonomy/sandbox/static.py`: replace `check_binds` with:

```python
def check_sources(sources: Iterable[Path], denied: Iterable[Path], *, exempt: Iterable[Path] = ()) -> None:
    """Each source against each denied path. A source whose real path is exactly an
    exempt path is skipped: the proxy's credential and `ca_file` are bound as single
    files under a denied ancestor such as `<config>` (decision 13). The exemption is
    exact, so their directories are still refused."""
    targets = [_target(path) for path in denied]
    skip = {path.resolve(strict=False) for path in exempt}
    for source in sources:
        try:
            real = source.resolve(strict=True)
            identity, ancestry = _identity(real), _ancestry(real)
        except FileNotFoundError as caught:
            raise SandboxUnproven("bind-missing", str(source), f"a bind source must exist: {caught}") from caught
        except (OSError, RuntimeError) as caught:
            raise SandboxUnproven("bind-unreadable", str(source), f"a bind source must resolve: {caught}") from caught
        if real in skip:
            continue
        for target, target_identity, target_ancestry in targets:
            overlaps = (
                real == target
                or real.is_relative_to(target)
                or target.is_relative_to(real)
                or (target_identity is not None and target_identity in ancestry)
                or identity in target_ancestry
            )
            if overlaps:
                raise SandboxUnproven(
                    "bind-overlaps-denied", str(source), f"is, contains, or lies inside the denied path {target}"
                )


def check_binds(spec: SandboxSpec, denied: Iterable[Path]) -> None:
    check_sources(spec.bind_sources(), denied)
```

`python/src/autonomy/sandbox/bwrap.py`:

1. In `build_argv`, delete the two lines `if spec.network == "host":` and
   `args.append("--share-net")`.
2. Replace `_PROBE` and `probe`:

```python
_PROBE = """\
import errno, os, socket, sys
for path in sys.argv[1:]:
    try:
        os.stat(path)
        print("REACHABLE", path)
    except OSError as caught:
        print(errno.errorcode.get(caught.errno, str(caught.errno)), path)
for family, host in ((socket.AF_INET, "192.0.2.1"), (socket.AF_INET6, "2001:db8::1")):
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.settimeout(5)
            probe.connect((host, 443))
        print("CONNECTED", "net:" + host)
    except OSError as caught:
        name = errno.errorcode.get(caught.errno) if caught.errno else type(caught).__name__
        print(name, "net:" + host)
"""

NET_TARGETS = ("net:192.0.2.1", "net:2001:db8::1")
"""Documentation addresses (RFC 5737, RFC 3849): nothing answers them anywhere."""
_UNREACHABLE = {"net:192.0.2.1": {"ENETUNREACH"}, "net:2001:db8::1": {"ENETUNREACH", "EAFNOSUPPORT"}}


def probe(spec: SandboxSpec, denied: Iterable[Path]) -> None:
    """`ENOENT` on every denied path, and `ENETUNREACH` from a connect to a
    non-loopback IPv4 and IPv6 address (decision 13). A kernel without IPv6 answers
    `EAFNOSUPPORT`, which is as unreachable."""
    paths = [str(p.resolve()) for p in denied]
    argv = build_argv(spec, ["/usr/bin/python3", "-I", "-c", _PROBE, *paths], info_fd=None)
    try:
        result = subprocess.run(argv, capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise SandboxUnproven("probe-failed", "bwrap", "the probe did not exit in 60 s") from None
    stdout = result.stdout.decode("utf-8", errors="replace")
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise SandboxUnproven("probe-failed", "bwrap", stderr or f"exit {result.returncode}")
    lines = stdout.splitlines()
    expected = [*paths, *NET_TARGETS]
    if len(lines) != len(expected):
        raise SandboxUnproven("probe-failed", "bwrap", f"expected {len(expected)} lines, got {len(lines)}")
    for path, line in zip(expected, lines, strict=True):
        status, _, reported = line.partition(" ")
        if reported != path:
            raise SandboxUnproven("probe-failed", path, f"the probe reported {reported!r} out of order")
        if path in _UNREACHABLE:
            if status not in _UNREACHABLE[path]:
                raise SandboxUnproven("probe-network", path, f"a connect inside the sandbox gave {status}, not ENETUNREACH")
        elif status != "ENOENT":
            raise SandboxUnproven("probe-reachable", path, f"stat inside the sandbox gave {status}, not ENOENT")
```

3. Rename `_read_info` to `read_info`. Update its one caller in `launch`, and any
   test that imports it: `grep -rn _read_info python/` must print nothing afterwards.
4. Give `launch` the hook. The signature becomes
   `def launch(spec, argv, *, stdin, stdout, stderr, before_release=None) -> Sandboxed:`.
   Add this sentence to its docstring: "`before_release(child_pid, pidfd)` runs after
   the pidfd is held and before the release. Whatever it raises aborts the launch and
   propagates unchanged: the model proxy's listener (decision 13) must exist before
   the actor can run." Replace the body's `try` block, from `pidfd = -1` to the end,
   with:

```python
    pidfd = -1
    hook_error: BaseException | None = None
    try:
        try:
            info = read_info(info_read, process)
        finally:
            os.close(info_read)
        child = None if info is None else info.get("child-pid")
        if type(child) is not int:
            raise SandboxUnproven("launch-failed", "bwrap", "bwrap reported no child in time")
        try:
            pidfd = os.pidfd_open(child)
        except OSError as caught:
            raise SandboxUnproven("launch-failed", "bwrap", f"no handle on child {child}: {caught.strerror}") from caught
        if before_release is not None:
            try:
                before_release(child, pidfd)
            except BaseException as caught:
                hook_error = caught
                raise
        os.write(gate_write, RELEASE)
    except BaseException as caught:
        _abort(process, pidfd)
        if caught is hook_error or isinstance(caught, SandboxUnproven) or not isinstance(caught, Exception):
            raise
        raise SandboxUnproven("launch-failed", "bwrap", f"{type(caught).__name__}: {caught}") from caught
    finally:
        os.close(gate_write)
    return Sandboxed(process, child, pidfd)
```

Add `Callable` to the `collections.abc` import if absent (it is imported for
`preflight`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `just test-one tests/test_sandbox_probe.py tests/test_sandbox_static.py tests/test_sandbox_launch.py`
Expected: PASS.

- [ ] **Step 5: Run the fast suite, then commit**

Run: `just test-fast`. Expected: PASS. A test elsewhere that built
`SandboxSpec(network=...)` fails with `TypeError`; drop the argument there.

```bash
git add python/src/autonomy/sandbox python/tests/test_sandbox_probe.py python/tests/test_sandbox_static.py python/tests/test_sandbox_launch.py
git commit -m "feat(sandbox): no host network, a network probe, and a release hook (decision 13)"
```

---
### Task 2: The model route: strict parsing, the credential file, the denied set

**Files:**
- Create: `python/src/autonomy/egress/__init__.py`
- Create: `python/src/autonomy/egress/errors.py`
- Create: `python/src/autonomy/egress/route.py`
- Create: `python/tests/egress_fixtures.py`
- Test: `python/tests/test_egress_route.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `RouteRefused(code: str, message: str)`, with `.code` and `.message`;
  - `EgressUnproven(code: str, message: str)`, the same shape;
  - `Refused(code: str, message: str)`, the same shape;
  - `Operation`, with fields `method, path: str` and
    `queries, models, fields, tool_types, block_types, source_types: frozenset[str]`;
  - `Route`, with fields `api, host: str`, `port: int`, `ca_file: Path | None`,
    `operations: tuple[Operation, ...]`, `forward_headers: frozenset[str]`,
    `header_tokens: Mapping[str, frozenset[str]]`, `credential_file: Path`,
    `credential_header: Literal["x-api-key", "authorization"]` and
    `max_request_bytes: int`;
  - `Route`'s properties `upstream`, an `https://…` origin, and `authority`, the
    `Host` value;
  - `Route.operation(method, path, query) -> Operation | None` and
    `Route.describe() -> str`;
  - `parse_route(data: bytes) -> Route`, which raises `RouteRefused("route-invalid")`;
  - `LoadedRoute`, with fields `name: str`, `path: Path`, `data: bytes`,
    `digest: str` and `route: Route`;
  - `load_route(config: Path, name: str) -> LoadedRoute`, which raises
    `route-unknown`, `route-invalid` or `credential-unavailable`;
  - `check_credential(path: Path) -> None`, which raises `credential-unavailable`;
  - `egress_denied(config: Path, loaded: LoadedRoute) -> tuple[Path, ...]`;
  - `always_dropped(name: str) -> bool`;
  - `KNOWN_BLOCK_TYPES` and `KNOWN_SOURCE_TYPES`;
  - in the fixtures: `to_toml(doc: dict) -> str`, `pi_route(*, credential: Path,
    upstream: str = "https://api.anthropic.com", ca_file: Path | None = None) -> dict`,
    `write_route(config: Path, name: str, doc: dict) -> Path` and
    `write_credential(path: Path, value: str = "sk-canary") -> Path`.

- [ ] **Step 1: Write the fixtures and the failing tests**

`python/tests/egress_fixtures.py`:

```python
"""Shared fixtures for the egress tests: route documents and files, and (Task 6) a
fake TLS upstream."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

PI_FIELDS = [
    "model", "messages", "system", "max_tokens", "stream", "tools", "tool_choice", "thinking",
    "temperature", "metadata", "stop_sequences", "top_p", "top_k",
]
PI_BLOCKS = ["text", "image", "tool_use", "tool_result", "thinking", "redacted_thinking"]
PI_BETAS = ["fine-grained-tool-streaming-2025-05-14", "interleaved-thinking-2025-05-14"]
MODEL = "claude-haiku-5-5"


def pi_route(*, credential: Path, upstream: str = "https://api.anthropic.com", ca_file: Path | None = None) -> dict:
    """The route pi needs: POST /v1/messages?beta=true, client tools only, base64 sources."""
    doc: dict = {
        "api": "anthropic-messages",
        "upstream": upstream,
        "max_request_bytes": 8_000_000,
        "forward_headers": ["anthropic-version", "anthropic-beta", "content-type", "accept", "user-agent"],
        "header_tokens": {"anthropic-version": ["2023-06-01"], "anthropic-beta": list(PI_BETAS)},
        "credential": {"file": str(credential), "header": "x-api-key"},
        "operations": [
            {
                "method": "POST",
                "path": "/v1/messages",
                "queries": ["beta=true"],
                "models": [MODEL],
                "fields": list(PI_FIELDS),
                "tool_types": [],
                "block_types": list(PI_BLOCKS),
                "source_types": ["base64"],
            }
        ],
    }
    if ca_file is not None:
        doc["ca_file"] = str(ca_file)
    return doc


def _key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key)


def _value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    raise TypeError(f"no TOML form for {value!r}")


def to_toml(doc: dict) -> str:
    """Enough TOML for a route: scalars and lists, then tables, then arrays of tables."""
    lines: list[str] = []
    tables, arrays = [], []
    for key, value in doc.items():
        if isinstance(value, dict):
            tables.append((key, value))
        elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            arrays.append((key, value))
        else:
            lines.append(f"{_key(key)} = {_value(value)}")
    for key, table in tables:
        lines.append(f"[{_key(key)}]")
        lines += [f"{_key(k)} = {_value(v)}" for k, v in table.items()]
    for key, items in arrays:
        for table in items:
            lines.append(f"[[{_key(key)}]]")
            lines += [f"{_key(k)} = {_value(v)}" for k, v in table.items()]
    return "\n".join(lines) + "\n"


def write_route(config: Path, name: str, doc: dict) -> Path:
    path = config / "routes" / f"{name}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_toml(doc))
    return path


def write_credential(path: Path, value: str = "sk-canary") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(value + "\n")
    os.chmod(path, 0o600)
    return path
```

`python/tests/test_egress_route.py`:

```python
import copy
import hashlib
import os
from pathlib import Path

import pytest

from egress_fixtures import pi_route, to_toml, write_credential, write_route
from autonomy.egress.errors import RouteRefused
from autonomy.egress.route import (
    always_dropped, check_credential, egress_denied, load_route, parse_route,
)


@pytest.fixture
def config(tmp_path):
    return tmp_path / "config"


@pytest.fixture
def credential(config):
    return write_credential(config / "credentials" / "anthropic")


def parse(doc: dict):
    return parse_route(to_toml(doc).encode())


def test_the_pi_route_parses(credential):
    route = parse(pi_route(credential=credential))
    assert route.api == "anthropic-messages"
    assert (route.host, route.port, route.upstream, route.authority) == (
        "api.anthropic.com", 443, "https://api.anthropic.com", "api.anthropic.com",
    )
    op = route.operation("POST", "/v1/messages", "beta=true")
    assert op is not None and op.models == {"claude-haiku-5-5"}
    assert route.operation("POST", "/v1/messages", "") is None
    assert route.operation("GET", "/v1/messages", "beta=true") is None
    assert route.header_tokens["anthropic-version"] == {"2023-06-01"}
    assert route.credential_header == "x-api-key"
    assert route.describe() == "POST /v1/messages?beta=true"


def test_a_port_shows_in_the_origin_and_authority(credential):
    route = parse(pi_route(credential=credential, upstream="https://localhost:8443"))
    assert (route.upstream, route.authority) == ("https://localhost:8443", "localhost:8443")


def _without(key):
    def change(doc):
        del doc[key]
    return change


def _op(**fields):
    def change(doc):
        doc["operations"][0].update(fields)
    return change


def _set(**fields):
    def change(doc):
        doc.update(fields)
    return change


INVALID = {
    "unknown dialect": _set(api="openai-chat"),
    "http upstream": _set(upstream="http://api.anthropic.com"),
    "upstream with a path": _set(upstream="https://api.anthropic.com/v1"),
    "upstream with userinfo": _set(upstream="https://u:p@api.anthropic.com"),
    "upstream with a query": _set(upstream="https://api.anthropic.com?x=1"),
    "no operations": _set(operations=[]),
    "operation without models": _op(models=[]),
    "operation without fields": _op(fields=[]),
    "fields without model": _op(fields=["messages"]),
    "operation without block types": _op(block_types=[]),
    "an undefined block type": _op(block_types=["text", "search_result"]),
    "an undefined source type": _op(source_types=["base64", "s3"]),
    "a lower-case method": _op(method="post"),
    "a path without a slash": _op(path="v1/messages"),
    "a path with a query": _op(path="/v1/messages?beta=true"),
    "forwarding x-api-key": _set(forward_headers=["x-api-key"]),
    "forwarding Transfer-Encoding": _set(forward_headers=["Transfer-Encoding"]),
    "forwarding an x-forwarded header": _set(forward_headers=["X-Forwarded-Host"]),
    "forwarding a header twice by case": _set(forward_headers=["accept", "Accept"]),
    "a beta header without tokens": lambda doc: doc["header_tokens"].pop("anthropic-beta"),
    "tokens for an unforwarded header": lambda doc: doc["header_tokens"].update({"x-probe": ["a"]}),
    "an empty token list": lambda doc: doc["header_tokens"].update({"anthropic-beta": []}),
    "an unknown top-level key": _set(timeout=5),
    "an unknown operation key": _op(cost=1),
    "a credential header outside the two": lambda doc: doc["credential"].update({"header": "cookie"}),
    "a relative credential path": lambda doc: doc["credential"].update({"file": "credentials/anthropic"}),
    "a relative ca_file": _set(ca_file="ca.pem"),
    "a zero body limit": _set(max_request_bytes=0),
    "a boolean body limit": _set(max_request_bytes=True),
    "a missing credential table": _without("credential"),
    "a repeated operation": lambda doc: doc["operations"].append(copy.deepcopy(doc["operations"][0])),
}


@pytest.mark.parametrize("case", sorted(INVALID))
def test_an_invalid_route_is_refused(case, credential):
    doc = pi_route(credential=credential)
    INVALID[case](doc)
    with pytest.raises(RouteRefused) as caught:
        parse(doc)
    assert caught.value.code == "route-invalid"


def test_bytes_that_are_not_toml_are_invalid():
    with pytest.raises(RouteRefused) as caught:
        parse_route(b"api = \n")
    assert caught.value.code == "route-invalid"


@pytest.mark.parametrize("name", ["Host", "x-forwarded-for", "SET-COOKIE", "Connection", "expect"])
def test_always_dropped_ignores_case(name):
    assert always_dropped(name)


def test_load_route_reads_digests_and_checks_the_credential(config, credential):
    path = write_route(config, "anthropic", pi_route(credential=credential))
    loaded = load_route(config, "anthropic")
    assert loaded.name == "anthropic"
    assert loaded.path == path.resolve()
    assert loaded.data == path.read_bytes()
    assert loaded.digest == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("name", ["missing", "../anthropic", "Anthropic", ""])
def test_an_unknown_route_name(config, credential, name):
    write_route(config, "anthropic", pi_route(credential=credential))
    with pytest.raises(RouteRefused) as caught:
        load_route(config, name)
    assert caught.value.code == "route-unknown"


def _refused(path: Path) -> str:
    with pytest.raises(RouteRefused) as caught:
        check_credential(path)
    assert caught.value.code == "credential-unavailable"
    return caught.value.message


def test_a_missing_credential(tmp_path):
    assert "missing" in _refused(tmp_path / "nope")


def test_a_directory_credential(tmp_path):
    assert "not a regular file" in _refused(tmp_path)


def test_a_symlinked_credential(tmp_path, credential):
    link = tmp_path / "link"
    link.symlink_to(credential)
    assert "symlink" in _refused(link)


def test_a_group_readable_credential(credential):
    os.chmod(credential, 0o640)
    assert "group or other" in _refused(credential)


def test_a_hard_linked_credential(tmp_path, credential):
    os.link(credential, tmp_path / "second-name")
    assert "2 links" in _refused(credential)


def test_a_credential_owned_by_someone_else():
    assert "owned by uid 0" in _refused(Path("/etc/passwd"))


def test_a_route_whose_credential_fails_is_refused_at_load(config, credential):
    os.chmod(credential, 0o644)
    write_route(config, "anthropic", pi_route(credential=credential))
    with pytest.raises(RouteRefused) as caught:
        load_route(config, "anthropic")
    assert caught.value.code == "credential-unavailable"


def test_the_denied_entries(config, credential):
    write_route(config, "anthropic", pi_route(credential=credential))
    loaded = load_route(config, "anthropic")
    assert egress_denied(config, loaded) == (
        config.resolve(), loaded.path, credential.resolve(),
    )


def test_a_toolchain_bind_holding_the_credential_fails_the_static_check(config, credential):  # E22
    from autonomy.sandbox.spec import SandboxSpec
    from autonomy.sandbox.static import SandboxUnproven, check_binds

    write_route(config, "anthropic", pi_route(credential=credential))
    loaded = load_route(config, "anthropic")
    scratch = config.parent / "scratch"
    scratch.mkdir()
    with pytest.raises(SandboxUnproven) as caught:
        check_binds(SandboxSpec(scratch=scratch, ro_binds=(credential.parent,)), egress_denied(config, loaded))
    assert caught.value.code == "bind-overlaps-denied"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-one tests/test_egress_route.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.egress'`.

- [ ] **Step 3: Implement**

`python/src/autonomy/egress/__init__.py`:

```python
"""Egress and credential custody (envelope design decision 13): the model route, the
proxy that is the actor's only network path, and the orchestrator's side of it."""
```

`python/src/autonomy/egress/errors.py`:

```python
"""The egress refusals (envelope design decision 13), one shape for each audience."""

from __future__ import annotations


class _Coded(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class RouteRefused(_Coded):
    """Step 2: the model route or its credential file cannot be used
    (`route-unknown`, `route-invalid`, `credential-unavailable`). The run exits 2."""


class EgressUnproven(_Coded):
    """The proxy or its listener could not be established or proven. The run is
    `unwired` (`egress-unproven`, with this code as its ref), and the actor is never
    released."""


class Refused(_Coded):
    """A request the proxy refuses, answered `403` with this code."""
```

`python/src/autonomy/egress/route.py`:

```python
"""The model route (envelope design decision 13): operator configuration naming the
one upstream, the operations an actor may ask for, and the credential the proxy adds.
It is parsed strictly. An unknown key, an empty list the dialect needs, or a header
the proxy always drops makes the route `route-invalid`."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal
from urllib.parse import urlsplit

from autonomy.egress.errors import RouteRefused

DIALECTS = frozenset({"anthropic-messages"})
FEATURE_HEADERS: Mapping[str, frozenset[str]] = MappingProxyType(
    {"anthropic-messages": frozenset({"anthropic-beta", "anthropic-version"})}
)
"""Headers that switch provider features or select the body's shape: a route that
forwards one must list its tokens."""
KNOWN_BLOCK_TYPES = frozenset({"text", "image", "document", "tool_use", "tool_result", "thinking", "redacted_thinking"})
"""Block types whose nested positions `anthropic-messages` defines: only these may be listed."""
KNOWN_SOURCE_TYPES = frozenset({"base64", "text", "content", "url", "file"})
ALWAYS_DROPPED = frozenset(
    {
        "host", "forwarded",
        "x-api-key", "authorization", "proxy-authorization", "cookie", "set-cookie",
        "content-length", "transfer-encoding", "connection", "keep-alive", "te", "trailer", "upgrade", "expect",
    }
)
_ROUTE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_METHOD = re.compile(r"[A-Z]+")
_PATH = re.compile(r"/[\x21-\x7e]*")


def always_dropped(name: str) -> bool:
    lowered = name.lower()
    return lowered in ALWAYS_DROPPED or lowered.startswith("x-forwarded-")


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    queries: frozenset[str]
    models: frozenset[str]
    fields: frozenset[str]
    tool_types: frozenset[str]
    block_types: frozenset[str]
    source_types: frozenset[str]


@dataclass(frozen=True)
class Route:
    api: str
    host: str
    port: int
    ca_file: Path | None
    operations: tuple[Operation, ...]
    forward_headers: frozenset[str]
    header_tokens: Mapping[str, frozenset[str]]
    credential_file: Path
    credential_header: Literal["x-api-key", "authorization"]
    max_request_bytes: int

    @property
    def upstream(self) -> str:
        return f"https://{self.authority}"

    @property
    def authority(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return host if self.port == 443 else f"{host}:{self.port}"

    def operation(self, method: str, path: str, query: str) -> Operation | None:
        for op in self.operations:
            if op.method == method and op.path == path and query in op.queries:
                return op
        return None

    def describe(self) -> str:
        return ", ".join(
            f"{op.method} {op.path}" + (f"?{query}" if query else "")
            for op in self.operations
            for query in sorted(op.queries)
        )


def _invalid(message: str) -> RouteRefused:
    return RouteRefused("route-invalid", message)


def _table(value: object, where: str, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise _invalid(f"{where} must be a table")
    unknown = set(value) - required - set(optional)
    if unknown:
        raise _invalid(f"{where} has unknown keys: {', '.join(sorted(unknown))}")
    missing = required - set(value)
    if missing:
        raise _invalid(f"{where} lacks: {', '.join(sorted(missing))}")
    return value


def _strings(value: object, where: str, *, nonempty: bool) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _invalid(f"{where} must be a list of strings")
    if nonempty and not value:
        raise _invalid(f"{where} must not be empty")
    if len(set(value)) != len(value):
        raise _invalid(f"{where} repeats an entry")
    return value


def _absolute(value: object, where: str) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise _invalid(f"{where} must be an absolute path")
    return Path(value)


def _upstream(value: object) -> tuple[str, int]:
    if not isinstance(value, str):
        raise _invalid("upstream must be a string")
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError:
        raise _invalid(f"upstream {value!r} has an invalid port") from None
    if parts.scheme != "https" or not parts.hostname:
        raise _invalid(f"upstream {value!r} must be one https origin")
    if parts.username is not None or parts.password is not None or parts.path or parts.query or parts.fragment:
        raise _invalid(f"upstream {value!r} must be an origin: no userinfo, path, query or fragment")
    return parts.hostname, port or 443


def _headers(value: object, where: str) -> frozenset[str]:
    names = [name.lower() for name in _strings(value, where, nonempty=False)]
    if len(set(names)) != len(names):
        raise _invalid(f"{where} repeats a header (names compare case-insensitively)")
    for name in names:
        if not _TOKEN.fullmatch(name):
            raise _invalid(f"{where}: {name!r} is not a header name")
        if always_dropped(name):
            raise _invalid(f"{where}: {name} is always dropped and cannot be forwarded")
    return frozenset(names)


def _operation(value: object, where: str) -> Operation:
    table = _table(
        value, where,
        {"method", "path", "models", "fields", "block_types"},
        {"queries", "tool_types", "source_types"},
    )
    method = table["method"]
    if not isinstance(method, str) or not _METHOD.fullmatch(method):
        raise _invalid(f"{where}.method must be an upper-case HTTP method")
    path = table["path"]
    if not isinstance(path, str) or not _PATH.fullmatch(path) or "?" in path or "#" in path:
        raise _invalid(f"{where}.path must be an absolute path with no query")
    fields = _strings(table["fields"], f"{where}.fields", nonempty=True)
    if "model" not in fields:
        raise _invalid(f"{where}.fields must include model")
    blocks = _strings(table["block_types"], f"{where}.block_types", nonempty=True)
    undefined = set(blocks) - KNOWN_BLOCK_TYPES
    if undefined:
        raise _invalid(f"{where}.block_types: the dialect defines no nested positions for {sorted(undefined)}")
    sources = _strings(table.get("source_types", []), f"{where}.source_types", nonempty=False)
    if set(sources) - KNOWN_SOURCE_TYPES:
        raise _invalid(f"{where}.source_types: unknown {sorted(set(sources) - KNOWN_SOURCE_TYPES)}")
    return Operation(
        method=method,
        path=path,
        queries=frozenset(_strings(table.get("queries", [""]), f"{where}.queries", nonempty=True)),
        models=frozenset(_strings(table["models"], f"{where}.models", nonempty=True)),
        fields=frozenset(fields),
        tool_types=frozenset(_strings(table.get("tool_types", []), f"{where}.tool_types", nonempty=False)),
        block_types=frozenset(blocks),
        source_types=frozenset(sources),
    )


def parse_route(data: bytes) -> Route:
    try:
        doc = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as caught:
        raise _invalid(f"not UTF-8 TOML: {caught}") from None
    top = _table(
        doc, "the route",
        {"api", "upstream", "operations", "forward_headers", "credential", "max_request_bytes"},
        {"ca_file", "header_tokens"},
    )
    api = top["api"]
    if api not in DIALECTS:
        raise _invalid(f"api {api!r} is not a dialect this build defines ({', '.join(sorted(DIALECTS))})")
    host, port = _upstream(top["upstream"])
    forward = _headers(top["forward_headers"], "forward_headers")
    tokens_table = top.get("header_tokens", {})
    if not isinstance(tokens_table, dict):
        raise _invalid("header_tokens must be a table")
    tokens: dict[str, frozenset[str]] = {}
    for name, values in tokens_table.items():
        lowered = name.lower()
        if lowered not in forward:
            raise _invalid(f"header_tokens names {name}, which is not forwarded")
        listed = _strings(values, f"header_tokens.{name}", nonempty=True)
        if not all(_TOKEN.fullmatch(token) for token in listed):
            raise _invalid(f"header_tokens.{name} holds a value that is not a token")
        tokens[lowered] = frozenset(listed)
    for name in FEATURE_HEADERS[api] & forward:
        if name not in tokens:
            raise _invalid(f"{name} switches provider features: forwarding it needs header_tokens.{name}")
    operations = top["operations"]
    if not isinstance(operations, list) or not operations:
        raise _invalid("the route needs at least one operation")
    parsed = tuple(_operation(op, f"operations[{i}]") for i, op in enumerate(operations))
    if len({(op.method, op.path) for op in parsed}) != len(parsed):
        raise _invalid("two operations share a method and path")
    credential = _table(top["credential"], "credential", {"file", "header"})
    header = credential["header"]
    if header not in ("x-api-key", "authorization"):
        raise _invalid("credential.header must be x-api-key or authorization")
    limit = top["max_request_bytes"]
    if type(limit) is not int or limit <= 0:
        raise _invalid("max_request_bytes must be a positive integer")
    return Route(
        api=api,
        host=host,
        port=port,
        ca_file=_absolute(top["ca_file"], "ca_file") if "ca_file" in top else None,
        operations=parsed,
        forward_headers=forward,
        header_tokens=MappingProxyType(tokens),
        credential_file=_absolute(credential["file"], "credential.file"),
        credential_header=header,
        max_request_bytes=limit,
    )


@dataclass(frozen=True)
class LoadedRoute:
    """The route as read at step 2: these bytes are digested into `baseline.json` and
    handed to the proxy, so the route enforced is the one recorded."""

    name: str
    path: Path
    data: bytes
    digest: str
    route: Route


def check_credential(path: Path) -> None:
    """Step 2's check of the credential file, by `fstat` on an `O_PATH` descriptor:
    the orchestrator never reads its bytes."""

    def refused(why: str) -> RouteRefused:
        return RouteRefused("credential-unavailable", f"{path}: {why}")

    try:
        fd = os.open(path, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        raise refused("missing") from None
    except OSError as caught:
        raise refused(caught.strerror or str(caught)) from None
    try:
        info = os.fstat(fd)
    finally:
        os.close(fd)
    if stat.S_ISLNK(info.st_mode):
        raise refused("a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise refused("not a regular file")
    if info.st_uid != os.getuid():
        raise refused(f"owned by uid {info.st_uid}, not {os.getuid()}")
    if info.st_nlink != 1:
        raise refused(f"has {info.st_nlink} links; a second name could sit in a bound directory")
    if info.st_mode & 0o077:
        raise refused(f"mode {stat.S_IMODE(info.st_mode):04o} has group or other permission bits")


def load_route(config: Path, name: str) -> LoadedRoute:
    if not _ROUTE_NAME.fullmatch(name):
        raise RouteRefused("route-unknown", f"{name!r} is not a route name ([a-z0-9][a-z0-9_-]*)")
    path = config / "routes" / f"{name}.toml"
    try:
        data = path.read_bytes()
        real = path.resolve(strict=True)
    except FileNotFoundError:
        raise RouteRefused("route-unknown", f"no route file {path}") from None
    except OSError as caught:
        raise RouteRefused("route-unknown", f"cannot read {path}: {caught.strerror}") from None
    route = parse_route(data)
    check_credential(route.credential_file)
    return LoadedRoute(name, real, data, hashlib.sha256(data).hexdigest(), route)


def egress_denied(config: Path, loaded: LoadedRoute) -> tuple[Path, ...]:
    """The denied set's entries for a run with this route (decision 13, spec §7)."""
    return (config.resolve(), loaded.path, loaded.route.credential_file.resolve())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `just test-one tests/test_egress_route.py`
Expected: PASS.

- [ ] **Step 5: Run the fast suite, then commit**

Run: `just test-fast`. Expected: PASS.

```bash
git add python/src/autonomy/egress python/tests/egress_fixtures.py python/tests/test_egress_route.py
git commit -m "feat(egress): parse the model route strictly and check its credential file"
```

---
### Task 3: Step 2's route refusals and `--model-route`

**Files:**
- Modify: `python/src/autonomy/run.py`
- Modify: `python/src/autonomy/cli.py`
- Test: `python/tests/test_run.py`, `python/tests/test_cli.py`

**Interfaces:**
- Consumes: `load_route` and `LoadedRoute` (Task 2), `RouteRefused` (Task 2).
- Produces:
  - `Places.config: Path`;
  - `RunRequest.model_route: str | None = None`, as the last field;
  - `Opened.places: Places` and `Opened.route: LoadedRoute | None`;
  - `autonomy run --model-route NAME`.

  B2 writes `baseline.json`'s `egress` block from `Opened.route` and computes the
  denied set from `Opened.places.config`.

- [ ] **Step 1: Write the failing tests**

In `python/tests/test_run.py`, add `"XDG_CONFIG_HOME": str(tmp_path / "config")` to the
`env` fixture (and `"config"` to its directory list), then add:

```python
from egress_fixtures import pi_route, write_credential, write_route


def request_with_route(name: str) -> RunRequest:
    return RunRequest(REPORT_ONLY, 60.0, None, ("/usr/bin/true",), model_route=name)


def config_of(tmp_path) -> Path:
    return tmp_path / "config" / "verifiably-autonomy"


def test_places_has_the_config_directory(tmp_path, env):
    assert places(env).config == config_of(tmp_path)


def test_a_relative_config_home_falls_back_to_the_home_default(tmp_path, env):
    env["XDG_CONFIG_HOME"] = "relative/config"
    assert places(env).config == tmp_path / "home" / ".config" / "verifiably-autonomy"


def test_a_model_route_reaches_the_steps(tmp_path, env, actor):
    config = config_of(tmp_path)
    credential = write_credential(config / "credentials" / "anthropic")
    path = write_route(config, "anthropic", pi_route(credential=credential))
    seen = {}

    def steps(opened):
        seen["route"] = opened.route
        seen["config"] = opened.places.config
        return endpoint_side_unbuilt(opened)

    code = execute(request_with_route("anthropic"), env, steps, diag=lambda _: None, progress=Progress(), actor_fds=actor)
    assert code == 4
    assert seen["route"].name == "anthropic"
    assert seen["route"].data == path.read_bytes()
    assert seen["config"] == config


def test_without_a_route_the_steps_get_none(tmp_path, env, actor):
    seen = {}

    def steps(opened):
        seen["route"] = opened.route
        return endpoint_side_unbuilt(opened)

    execute(request(), env, steps, diag=lambda _: None, progress=Progress(), actor_fds=actor)
    assert seen == {"route": None}


@pytest.mark.parametrize("case", ["route-unknown", "route-invalid", "credential-unavailable"])
def test_a_route_refusal_keeps_nothing_and_writes_no_report_line(tmp_path, env, actor, case):
    config = config_of(tmp_path)
    credential = write_credential(config / "credentials" / "anthropic")
    doc = pi_route(credential=credential)
    if case == "route-invalid":
        doc["api"] = "openai-chat"
    if case == "credential-unavailable":
        os.chmod(credential, 0o644)
    if case != "route-unknown":
        write_route(config, "anthropic", doc)
    read_end, write_end = os.pipe()
    try:
        with pytest.raises(RunRefused) as caught:
            execute(
                RunRequest(REPORT_ONLY, 60.0, write_end, ("/usr/bin/true",), model_route="anthropic"),
                env, endpoint_side_unbuilt, diag=lambda _: None, progress=Progress(), actor_fds=actor,
            )
        assert caught.value.code == case
        assert runs(tmp_path) == []
        os.close(write_end)
        write_end = -1
        assert read_all(read_end) == b""
    finally:
        os.close(read_end)
        if write_end >= 0:
            os.close(write_end)
```

In `python/tests/test_cli.py` add:

```python
from egress_fixtures import pi_route, write_credential, write_route


def default_config(tmp_path) -> Path:
    return tmp_path / "home" / ".config" / "verifiably-autonomy"


def test_an_unknown_model_route_exits_2_with_no_run_directory(tmp_path, pipes):
    status, _ = autonomy(tmp_path, [*RUN, "--model-route", "anthropic", *ACTOR], pipes["io"])
    assert status == 2
    assert runs(tmp_path) == []
    assert b"route-unknown" in drain(pipes["err"])
    assert drain(pipes["out"]) == b""


def test_a_valid_model_route_passes_step_2(tmp_path, pipes):
    environment(tmp_path)
    config = default_config(tmp_path)
    credential = write_credential(config / "credentials" / "anthropic")
    write_route(config, "anthropic", pi_route(credential=credential))
    status, _ = autonomy(tmp_path, [*RUN, "--model-route", "anthropic", *ACTOR], pipes["io"])
    assert status == 4  # this build closes unwired at step 3, after step 2 accepted the route
    assert len(runs(tmp_path)) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-one tests/test_run.py tests/test_cli.py`
Expected: FAIL. `RunRequest` has no `model_route`, `Places` has no `config`, and
`--model-route` is an unrecognized argument.

- [ ] **Step 3: Implement**

In `python/src/autonomy/run.py`:

1. Import `from autonomy.egress.errors import RouteRefused` and
   `from autonomy.egress.route import LoadedRoute, load_route`.
2. Make `RunRequest` end with `model_route: str | None = None`.
3. Give `Places` a fourth field, `config: Path`. In `places`, add
   `config=_xdg(env, "XDG_CONFIG_HOME", ".config") / "verifiably-autonomy",`.
4. Give `Opened` two fields after `stdio`: `places: Places` and
   `route: LoadedRoute | None`.
5. In `execute`, after `where = places(env)` and before `report: LineChannel | None
   = None`, add:

```python
    route = _route(request.model_route, where)
```

   Then construct `Opened(request, dirs, stdio, where, route)`. Add the helper:

```python
def _route(name: str | None, where: Places) -> LoadedRoute | None:
    """Step 2's route refusals (decision 13): before anything exists, so a refusal
    leaves no run directory and writes nothing on the report fd."""
    if name is None:
        return None
    try:
        return load_route(where.config, name)
    except RouteRefused as caught:
        raise RunRefused(caught.code, caught.message) from None
```

   Update `execute`'s docstring: step 2 is "`refuse`, `places` and the model route".

In `python/src/autonomy/cli.py`, add after the `--report-fd` argument:

```python
    run.add_argument(
        "--model-route", metavar="NAME",
        help="the model route under <config>/routes/NAME.toml: the actor's only network path (decision 13)",
    )
```

   In `_run`, build the request as
   `RunRequest(chosen, args.lease, args.report_fd, tuple(args.actor), args.model_route)`.

Any existing test that constructs `Places(...)` or `Opened(...)` positionally needs
the new fields. Fix each one that `just test-fast` reports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `just test-one tests/test_run.py tests/test_cli.py`
Expected: PASS.

- [ ] **Step 5: Run the fast suite, then commit**

Run: `just test-fast`. Expected: PASS.

```bash
git add python/src/autonomy/run.py python/src/autonomy/cli.py python/tests/test_run.py python/tests/test_cli.py
git commit -m "feat(run): --model-route and step 2's route refusals (decision 13)"
```

---

### Task 4: Strict HTTP/1.1, the header policy, and the proxy's own framing

**Files:**
- Create: `python/src/autonomy/egress/request.py`
- Test: `python/tests/test_egress_request.py`

**Interfaces:**
- Consumes: `Route`, `always_dropped` (Task 2); `Refused` (Task 2).
- Produces:
  - `MAX_HEAD = 65536`;
  - `Request`, with fields `method, path, query: str`,
    `headers: tuple[tuple[str, str], ...]` (lower-cased names) and
    `content_length: int`;
  - `parse_head(head: bytes) -> Request`, where `head` is the bytes before the blank
    line, without the final `\r\n\r\n`;
  - `forwarded_headers(request: Request, route: Route) -> tuple[tuple[str, str], ...]`;
  - `frame(request: Request, route: Route, headers, body: bytes, credential: str) -> bytes`;
  - `refusal(code: str, message: str) -> bytes`, a complete `403` response.

- [ ] **Step 1: Write the failing tests**

`python/tests/test_egress_request.py`:

```python
import json

import pytest

from egress_fixtures import pi_route, to_toml
from autonomy.egress.errors import Refused
from autonomy.egress.request import forwarded_headers, frame, parse_head, refusal
from autonomy.egress.route import parse_route

ROUTE = parse_route(to_toml(pi_route(credential="/nonexistent/credential")).encode())


def head(*lines: str) -> bytes:
    return "\r\n".join(lines).encode("latin-1")


def refused(raw: bytes) -> str:
    with pytest.raises(Refused) as caught:
        parse_head(raw)
    return caught.value.code


def test_a_well_formed_request():
    request = parse_head(head(
        "POST /v1/messages?beta=true HTTP/1.1", "Host: 127.0.0.1:4780",
        "Content-Length: 12", "Anthropic-Version:  2023-06-01 ",
    ))
    assert (request.method, request.path, request.query, request.content_length) == (
        "POST", "/v1/messages", "beta=true", 12,
    )
    assert ("anthropic-version", "2023-06-01") in request.headers


@pytest.mark.parametrize(("raw", "code"), [
    (head("CONNECT api.anthropic.com:443 HTTP/1.1", "Host: x"), "target-refused"),
    (head("POST http://other/v1/messages HTTP/1.1", "Host: x"), "target-refused"),
    (head("POST other:443 HTTP/1.1", "Host: x"), "target-refused"),
    (head("OPTIONS * HTTP/1.1", "Host: x"), "target-refused"),
    (head("POST /v1/messages HTTP/1.1", "Upgrade: h2c"), "target-refused"),
    (head("POST /v1/messages HTTP/1.0", "Host: x"), "request-malformed"),
    (head("POST /v1/messages  HTTP/1.1", "Host: x"), "request-malformed"),
    (head("post /v1/messages HTTP/1.1", "Host: x"), "request-malformed"),
    (head("POST /v1/messages#frag HTTP/1.1", "Host: x"), "request-malformed"),
    (head("POST /v1/messages HTTP/1.1", "Host: x", " folded"), "request-malformed"),
    (head("POST /v1/messages HTTP/1.1", "Host : x"), "request-malformed"),
    (head("POST /v1/messages HTTP/1.1", "X-Bad: a\x00b"), "request-malformed"),
    (head("POST /v1/messages HTTP/1.1", "Transfer-Encoding: chunked"), "request-malformed"),
    (head("POST /v1/messages HTTP/1.1", "Content-Length: 5", "Content-Length: 5"), "request-malformed"),
    (head("POST /v1/messages HTTP/1.1", "Content-Length: +5"), "request-malformed"),
    (head("POST /v1/messages HTTP/1.1", "Content-Length: 1e3"), "request-malformed"),
])
def test_refused_heads(raw, code):
    assert refused(raw) == code


def test_paths_are_kept_byte_for_byte():
    for target in ("/v1/messages/../x", "/v1/%2e%2e/x", "//other/v1/messages", "/v1/messages/./"):
        request = parse_head(head(f"POST {target} HTTP/1.1", "Host: x"))
        assert request.path == target
        assert ROUTE.operation("POST", request.path, request.query) is None


def test_unlisted_headers_are_dropped_and_listed_ones_kept():
    request = parse_head(head(
        "POST /v1/messages?beta=true HTTP/1.1", "Host: other", "X-Forwarded-Host: other",
        "X-Probe: 1", "x-api-key: placeholder", "Authorization: Bearer sk-ant-oat-placeholder",
        "Connection: x-api-key", "Content-Type: application/json", "Content-Length: 2",
    ))
    assert forwarded_headers(request, ROUTE) == (("content-type", "application/json"),)


@pytest.mark.parametrize("lines", [
    ("anthropic-beta: interleaved-thinking-2025-05-14", "anthropic-beta: mcp-client-2025-04-04"),
    ("Anthropic-Beta: interleaved-thinking-2025-05-14", "anthropic-beta: interleaved-thinking-2025-05-14"),
    ("anthropic-beta: interleaved-thinking-2025-05-14, mcp-client-2025-04-04",),
    ("anthropic-version: 2099-01-01",),
])
def test_feature_headers_are_checked_token_by_token(lines):
    request = parse_head(head("POST /v1/messages?beta=true HTTP/1.1", *lines))
    with pytest.raises(Refused) as caught:
        forwarded_headers(request, ROUTE)
    assert caught.value.code == "header-refused"


def test_tokens_are_trimmed_of_optional_whitespace():
    request = parse_head(head(
        "POST /v1/messages?beta=true HTTP/1.1",
        "anthropic-beta:  interleaved-thinking-2025-05-14 ,\tfine-grained-tool-streaming-2025-05-14",
    ))
    assert len(forwarded_headers(request, ROUTE)) == 1


def test_the_proxy_frames_the_upstream_request_itself():
    request = parse_head(head("POST /v1/messages?beta=true HTTP/1.1", "Host: other", "Content-Length: 2"))
    raw = frame(request, ROUTE, (("anthropic-version", "2023-06-01"),), b"{}", "sk-canary")
    head_part, _, body = raw.partition(b"\r\n\r\n")
    lines = head_part.decode().split("\r\n")
    assert lines[0] == "POST /v1/messages?beta=true HTTP/1.1"
    assert lines[1:] == [
        "host: api.anthropic.com", "anthropic-version: 2023-06-01", "x-api-key: sk-canary",
        "content-length: 2", "connection: close",
    ]
    assert body == b"{}"


def test_a_bearer_route_sends_authorization():
    doc = pi_route(credential="/nonexistent/credential")
    doc["credential"]["header"] = "authorization"
    route = parse_route(to_toml(doc).encode())
    request = parse_head(head("POST /v1/messages HTTP/1.1"))
    assert b"authorization: Bearer sk-canary\r\n" in frame(request, route, (), b"", "sk-canary")


def test_a_refusal_names_its_code():
    raw = refusal("operation-refused", "allowed: POST /v1/messages?beta=true")
    head_part, _, body = raw.partition(b"\r\n\r\n")
    assert head_part.startswith(b"HTTP/1.1 403 Forbidden\r\n")
    assert b"connection: close" in head_part
    assert json.loads(body) == {"type": "error", "error": {
        "type": "egress_refused", "code": "operation-refused", "message": "allowed: POST /v1/messages?beta=true",
    }}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-one tests/test_egress_request.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.egress.request'`.

- [ ] **Step 3: Implement**

`python/src/autonomy/egress/request.py`:

```python
"""Strict HTTP/1.1 on the actor's side, and the request the proxy frames itself for the
upstream (envelope design decision 13). Nothing the actor sends about framing, hops or
destinations crosses: the target must be origin-form, the body comes with one
`Content-Length`, and the proxy writes `Host`, the credential and its own length."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from autonomy.egress.errors import Refused
from autonomy.egress.route import Route

MAX_HEAD = 64 * 1024
_TCHAR = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_METHOD = re.compile(rb"[A-Z]+")
_TARGET = re.compile(rb"/[\x21-\x7e]*")
_VALUE = re.compile(rb"[\t\x20-\x7e\x80-\xff]*")
_DIGITS = re.compile(r"[0-9]{1,15}")


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    query: str
    headers: tuple[tuple[str, str], ...]
    content_length: int


def _malformed(message: str) -> Refused:
    return Refused("request-malformed", message)


def parse_head(head: bytes) -> Request:
    lines = head.split(b"\r\n")
    parts = lines[0].split(b" ")
    if len(parts) != 3:
        raise _malformed("the request line is not METHOD TARGET HTTP/1.1")
    method, target, version = parts
    if not _METHOD.fullmatch(method):
        raise _malformed("the method is not an upper-case token")
    if method == b"CONNECT":
        raise Refused("target-refused", "CONNECT is refused: the proxy opens no tunnel")
    if version != b"HTTP/1.1":
        raise _malformed("the version is not HTTP/1.1")
    if not _TARGET.fullmatch(target):
        raise Refused("target-refused", "only an origin-form target (/path) is accepted")
    if b"#" in target:
        raise _malformed("a request target carries no fragment")
    path, _, query = target.decode("ascii").partition("?")
    headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        if not line or line[:1] in (b" ", b"\t"):
            raise _malformed("an empty or folded header line")
        name, colon, value = line.partition(b":")
        if not colon or not _TCHAR.fullmatch(name):
            raise _malformed("a header line is not NAME: VALUE")
        value = value.strip(b" \t")
        if not _VALUE.fullmatch(value):
            raise _malformed(f"header {name.decode('ascii')} holds a control character")
        headers.append((name.decode("ascii").lower(), value.decode("latin-1")))
    names = [name for name, _ in headers]
    if "transfer-encoding" in names:
        raise _malformed("a request body must come with Content-Length; Transfer-Encoding is refused")
    if "upgrade" in names:
        raise Refused("target-refused", "Upgrade is refused: the proxy forwards no other protocol")
    lengths = [value for name, value in headers if name == "content-length"]
    if len(lengths) > 1:
        raise _malformed("Content-Length is repeated")
    if lengths and not _DIGITS.fullmatch(lengths[0]):
        raise _malformed("Content-Length is not a decimal number")
    return Request(method.decode("ascii"), path, query, tuple(headers), int(lengths[0]) if lengths else 0)


def forwarded_headers(request: Request, route: Route) -> tuple[tuple[str, str], ...]:
    """The route's `forward_headers`, each once. Every other header is dropped. A
    repeated forwarded header, or a token outside `header_tokens`, is refused."""
    counts = Counter(name for name, _ in request.headers)
    kept: list[tuple[str, str]] = []
    for name, value in request.headers:
        if name not in route.forward_headers:
            continue
        if counts[name] > 1:
            raise Refused("header-refused", f"header {name} is repeated")
        allowed = route.header_tokens.get(name)
        if allowed is not None:
            tokens = [token.strip(" \t") for token in value.split(",")]
            outside = [token for token in tokens if token not in allowed]
            if outside:
                raise Refused("header-refused", f"header {name} holds {outside}; the route allows {sorted(allowed)}")
        kept.append((name, value))
    return tuple(kept)


def frame(request: Request, route: Route, headers: tuple[tuple[str, str], ...], body: bytes, credential: str) -> bytes:
    target = request.path + (f"?{request.query}" if request.query else "")
    lines = [f"{request.method} {target} HTTP/1.1", f"host: {route.authority}"]
    lines += [f"{name}: {value}" for name, value in headers]
    if route.credential_header == "x-api-key":
        lines.append(f"x-api-key: {credential}")
    else:
        lines.append(f"authorization: Bearer {credential}")
    lines += [f"content-length: {len(body)}", "connection: close"]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


def refusal(code: str, message: str) -> bytes:
    body = json.dumps({"type": "error", "error": {"type": "egress_refused", "code": code, "message": message}}).encode()
    head = (
        "HTTP/1.1 403 Forbidden\r\ncontent-type: application/json\r\n"
        f"content-length: {len(body)}\r\nconnection: close\r\n\r\n"
    )
    return head.encode("ascii") + body
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `just test-one tests/test_egress_request.py`
Expected: PASS.

- [ ] **Step 5: Run the fast suite, then commit**

Run: `just test-fast`. Expected: PASS.

```bash
git add python/src/autonomy/egress/request.py python/tests/test_egress_request.py
git commit -m "feat(egress): strict HTTP/1.1, the header policy, and the proxy's own framing"
```

---
### Task 5: The `anthropic-messages` dialect: strict JSON and closed positions

**Files:**
- Create: `python/src/autonomy/egress/dialect.py`
- Test: `python/tests/test_egress_dialect.py`

**Interfaces:**
- Consumes: `Operation` (Task 2), `Refused` (Task 2).
- Produces:
  - `parse_body(data: bytes) -> dict`, which raises `Refused("request-malformed")`;
  - `check_body(body: dict, op: Operation) -> None`, which raises
    `Refused("model-refused" | "body-refused")`.

- [ ] **Step 1: Write the failing tests**

`python/tests/test_egress_dialect.py`:

```python
import json

import pytest

from egress_fixtures import MODEL, pi_route, to_toml
from autonomy.egress.dialect import check_body, parse_body
from autonomy.egress.errors import Refused
from autonomy.egress.route import parse_route

OP = parse_route(to_toml(pi_route(credential="/nonexistent/credential")).encode()).operations[0]


def body(**extra) -> dict:
    return {"model": MODEL, "max_tokens": 16, "stream": True,
            "messages": [{"role": "user", "content": "hi"}], **extra}


def code_of(data: bytes) -> str:
    with pytest.raises(Refused) as caught:
        check_body(parse_body(data), OP)
    return caught.value.code


def test_a_plain_request_passes():
    check_body(parse_body(json.dumps(body()).encode()), OP)


@pytest.mark.parametrize("data", [
    b'{"model": "claude-haiku-5-5", "model": "claude-opus-5-5"}',
    b'{"model": "claude-haiku-5-5", "metadata": {"a": 1, "a": 2}}',
    b'\xef\xbb\xbf{"model": "claude-haiku-5-5"}',
    b'{"model": "claude-haiku-5-5", "temperature": NaN}',
    b'{"model": "claude-haiku-5-5", "temperature": Infinity}',
    b'["model"]',
    b'{"model": "claude-haiku-5-5", "x": "\xff"}',
    b'{"model": "claude-haiku-5-5", "system": "\\ud800"}',
    b'{"model": ' + b"[" * 100_000 + b"]" * 100_000 + b"}",
    b'{"model": "claude-haiku-5-5", "max_tokens": 1' + b"0" * 5000 + b"}",
    b"not json",
])
def test_strict_json(data):
    with pytest.raises(Refused) as caught:
        parse_body(data)
    assert caught.value.code == "request-malformed"


def test_a_model_outside_the_route():
    assert code_of(json.dumps(body(model="claude-opus-5-5")).encode()) == "model-refused"
    assert code_of(json.dumps({"messages": []}).encode()) == "model-refused"


@pytest.mark.parametrize("extra", [
    {"mcp_servers": [{"type": "url", "url": "https://attacker.example/mcp", "name": "x"}]},
    {"container": "container_123"},
    {"tools": [{"type": "web_fetch_20250910", "name": "web_fetch"}]},
    {"tools": [{"type": "web_search_20250305", "name": "web_search"}]},
    {"tools": [{"type": "custom", "name": "t", "input_schema": {"type": "object"}}]},
    {"messages": [{"role": "user", "content": [
        {"type": "image", "source": {"type": "url", "url": "https://attacker.example/x.png"}}]}]},
    {"messages": [{"role": "user", "content": [
        {"type": "document", "source": {"type": "file", "file_id": "file_1"}}]}]},
    {"messages": [{"role": "user", "content": [{"type": "search_result", "source": "https://x", "content": []}]}]},
    {"messages": [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t",
                                                 "content": [{"type": "search_result"}]}]}]},
    {"messages": [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": [
        {"type": "image", "source": {"type": "url", "url": "https://attacker.example/y.png"}}]}]}]},
    {"system": [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": ""}}]},
])
def test_a_body_that_asks_the_provider_to_reach_out(extra):
    assert code_of(json.dumps(body(**extra)).encode()) == "body-refused"


def test_client_tools_without_a_type_pass():
    check_body(parse_body(json.dumps(body(tools=[{"name": "bash", "input_schema": {"type": "object"}}])).encode()), OP)


def test_a_tool_use_input_is_the_clients_data():
    # The positions are closed, not the whole body: a tool's input may hold anything.
    message = {"role": "assistant", "content": [
        {"type": "tool_use", "id": "t", "name": "fetch", "input": {"type": "url", "url": "https://x"}}]}
    check_body(parse_body(json.dumps(body(messages=[message])).encode()), OP)


def test_a_base64_image_passes():
    message = {"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}]}
    check_body(parse_body(json.dumps(body(messages=[message])).encode()), OP)


def test_nested_sources_are_checked_at_any_depth():
    doc = pi_route(credential="/nonexistent/credential")
    doc["operations"][0]["block_types"].append("document")
    doc["operations"][0]["source_types"].append("content")
    op = parse_route(to_toml(doc).encode()).operations[0]
    nested = {"role": "user", "content": [{"type": "document", "source": {"type": "content", "content": [
        {"type": "image", "source": {"type": "url", "url": "https://attacker.example/z.png"}}]}}]}
    with pytest.raises(Refused) as caught:
        check_body(parse_body(json.dumps(body(messages=[nested])).encode()), op)
    assert caught.value.code == "body-refused"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-one tests/test_egress_dialect.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.egress.dialect'`.

- [ ] **Step 3: Implement**

`python/src/autonomy/egress/dialect.py`:

```python
"""The `anthropic-messages` dialect (envelope design decision 13). The body is parsed
as strict JSON, so the proxy and the upstream read the same values from the same
bytes. Then every position where a provider feature can sit is checked against the
operation's closed lists. A `tool_use` block's `input` and a tool's `input_schema` are
the client's data and are not walked."""

from __future__ import annotations

import json

from autonomy.egress.errors import Refused
from autonomy.egress.route import Operation

_BOM = b"\xef\xbb\xbf"


def _malformed(message: str) -> Refused:
    return Refused("request-malformed", message)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise _malformed(f"the body repeats the key {key!r}")
        seen[key] = value
    return seen


def _constant(name: str) -> object:
    raise _malformed(f"the body holds {name}, which JSON does not define")


def _strings_encode(value: object) -> None:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                raise _malformed("the body holds a lone surrogate escape") from None
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def parse_body(data: bytes) -> dict:
    if data.startswith(_BOM):
        raise _malformed("the body starts with a byte-order mark")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise _malformed("the body is not UTF-8") from None
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except RecursionError:
        raise _malformed("the body nests too deeply") from None
    except ValueError as caught:  # json.JSONDecodeError, and int's digit limit
        raise _malformed(f"the body is not JSON: {caught}") from None
    if not isinstance(value, dict):
        raise _malformed("the body is not a JSON object")
    _strings_encode(value)
    return value


def _refused(message: str) -> Refused:
    return Refused("body-refused", message)


def _source(source: object, op: Operation, where: str) -> None:
    if not isinstance(source, dict):
        raise _refused(f"{where} must be an object")
    kind = source.get("type")
    if not isinstance(kind, str) or kind not in op.source_types:
        raise _refused(f"{where} has source type {kind!r}; the route allows {sorted(op.source_types)}")
    if kind == "content":
        content = source.get("content")
        if not isinstance(content, str):
            _blocks(content, op, f"{where}.content")


def _blocks(blocks: object, op: Operation, where: str) -> None:
    if not isinstance(blocks, list):
        raise _refused(f"{where} must be a string or a list of blocks")
    for index, block in enumerate(blocks):
        here = f"{where}[{index}]"
        if not isinstance(block, dict):
            raise _refused(f"{here} must be an object")
        kind = block.get("type")
        if not isinstance(kind, str) or kind not in op.block_types:
            raise _refused(f"{here} has block type {kind!r}; the route allows {sorted(op.block_types)}")
        if kind == "tool_result":
            content = block.get("content")
            if content is not None and not isinstance(content, str):
                _blocks(content, op, f"{here}.content")
        if "source" in block:
            _source(block["source"], op, f"{here}.source")


def check_body(body: dict, op: Operation) -> None:
    model = body.get("model")
    if not isinstance(model, str) or model not in op.models:
        raise Refused("model-refused", f"model {model!r} is not one the route allows: {sorted(op.models)}")
    extra = set(body) - op.fields
    if extra:
        raise _refused(f"fields {sorted(extra)} are outside the route's {sorted(op.fields)}")
    try:
        tools = body.get("tools")
        if tools is not None:
            if not isinstance(tools, list):
                raise _refused("tools must be a list")
            for index, tool in enumerate(tools):
                if not isinstance(tool, dict):
                    raise _refused(f"tools[{index}] must be an object")
                if "type" in tool and tool["type"] not in op.tool_types:
                    raise _refused(f"tools[{index}] has type {tool['type']!r}; the route allows {sorted(op.tool_types)}")
        system = body.get("system")
        if system is not None and not isinstance(system, str):
            _blocks(system, op, "system")
        messages = body.get("messages")
        if messages is not None:
            if not isinstance(messages, list):
                raise _refused("messages must be a list")
            for index, message in enumerate(messages):
                if not isinstance(message, dict):
                    raise _refused(f"messages[{index}] must be an object")
                content = message.get("content")
                if not isinstance(content, str):
                    _blocks(content, op, f"messages[{index}].content")
    except RecursionError:
        raise _refused("the body's blocks nest too deeply") from None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `just test-one tests/test_egress_dialect.py`
Expected: PASS.

- [ ] **Step 5: Run the fast suite, then commit**

Run: `just test-fast`. Expected: PASS.

```bash
git add python/src/autonomy/egress/dialect.py python/tests/test_egress_dialect.py
git commit -m "feat(egress): the anthropic-messages dialect: strict JSON, closed positions"
```

---
### Task 6: The gate and the upstream client

**Files:**
- Create: `python/src/autonomy/egress/upstream.py`
- Modify: `python/tests/egress_fixtures.py` (add `Tls`, `tls`, `Seen`, `FakeUpstream`)
- Test: `python/tests/test_egress_upstream.py`

**Interfaces:**
- Consumes: `always_dropped` (Task 2).
- Produces:
  - `POLL = 0.2`, the longest a wait goes before it rechecks the gate;
  - `Gate`, with `next_seq() -> int | None`, `close(cause: str) -> bool` (the close
    transition: `True` only for the call that took it), `attempt(sock, data:
    memoryview) -> int | None`, the property `is_open`, and the attributes
    `cause: str | None` and `last_seq: int`;
  - `RouteClosed(sent: int = 0)`, with `.sent`;
  - `UpstreamError`;
  - `send_all(gate: Gate, sock, data: bytes) -> None`, which raises `RouteClosed`;
  - `tls_context(ca_file: Path | None) -> ssl.SSLContext`;
  - `connect(gate: Gate, host: str, port: int, context: ssl.SSLContext, *,
    timeout: float = 30.0) -> ssl.SSLSocket`, which returns a non-blocking socket and
    raises `UpstreamError` or `RouteClosed`;
  - `Response`, with fields `status: int`, `reason: str`,
    `headers: tuple[tuple[str, str], ...]` and `body: Iterator[bytes]`, and the
    property `request_id`;
  - `read_response(gate: Gate, sock) -> Response`;
  - `response_head(response: Response) -> bytes`;
  - in the fixtures: the session-scoped fixture `tls -> Tls(cert: Path, key: Path)`,
    `FakeUpstream(tls, *, mode="json")` with `.port`, `.origin`, `.seen: list[Seen]`,
    `.connections`, `.last_event_at`, `.events`, `.gap`, `.location`,
    `.stalled_bytes() -> int` and `.stop()`, and the dataclass
    `Seen(method, target, headers: dict[str, list[str]], body: bytes)`.

- [ ] **Step 1: Add the TLS fixtures**

Append to `python/tests/egress_fixtures.py` (add `import shutil, socket, ssl,
subprocess, threading, time`, `from dataclasses import dataclass` and `import pytest`
to its imports):

```python
@dataclass(frozen=True)
class Tls:
    cert: Path
    key: Path


@pytest.fixture(scope="session")
def tls(tmp_path_factory) -> Tls:
    """A self-signed certificate for localhost, `other` and 127.0.0.1. The tests need
    the openssl CLI and fail without it: skipping would hide the egress rows."""
    if shutil.which("openssl") is None:
        pytest.fail("the egress tests need the openssl CLI to make their test certificate")
    directory = tmp_path_factory.mktemp("tls")
    cert, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
         "-keyout", str(key), "-out", str(cert), "-days", "2", "-subj", "/CN=localhost",
         "-addext", "subjectAltName=DNS:localhost,DNS:other,IP:127.0.0.1"],
        check=True, capture_output=True, stdin=subprocess.DEVNULL,
    )
    return Tls(cert, key)


@dataclass
class Seen:
    method: str
    target: str
    headers: dict[str, list[str]]
    body: bytes


class FakeUpstream:
    """A TLS server on 127.0.0.1 standing in for the provider. `mode` picks the answer:
    - `json`: 200 with a small JSON body and a Content-Length;
    - `sse`: 200, chunked, `events` server-sent events `gap` seconds apart;
    - `close`: 200 with a body delimited by closing the connection;
    - `continue`: a 100 Continue, then as `json`;
    - `redirect`: 302 to `location`;
    - `stall`: read the head, then never read again (the body fills the buffers);
    - `garbage`, `hugehead`, `badchunk`: malformed answers.
    Every request it reads is in `seen`, and `connections` counts every accept."""

    def __init__(self, tls: Tls, *, mode: str = "json") -> None:
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(tls.cert, tls.key)
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.mode = mode
        self.events = 5
        self.gap = 0.2
        self.location = ""
        self.seen: list[Seen] = []
        self.connections = 0
        self.last_event_at: float | None = None
        self._stalled: list[tuple[Seen, ssl.SSLSocket]] = []
        self._lock = threading.Lock()
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def origin(self) -> str:
        return f"https://localhost:{self.port}"

    def stop(self) -> None:
        self.listener.close()

    def _accept(self) -> None:
        while True:
            try:
                raw, _ = self.listener.accept()
            except OSError:
                return
            with self._lock:
                self.connections += 1
            threading.Thread(target=self._serve, args=(raw,), daemon=True).start()

    def _serve(self, raw: socket.socket) -> None:
        try:
            conn = self.context.wrap_socket(raw, server_side=True)
        except (ssl.SSLError, OSError):
            raw.close()
            return
        keep = False
        try:
            conn.settimeout(10)
            buffer = b""
            while b"\r\n\r\n" not in buffer:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buffer += chunk
            head, _, body = buffer.partition(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            headers: dict[str, list[str]] = {}
            for line in lines[1:]:
                name, _, value = line.partition(":")
                headers.setdefault(name.strip().lower(), []).append(value.strip())
            seen = Seen(method, target, headers, body)
            if self.mode == "stall":
                with self._lock:
                    self.seen.append(seen)
                    self._stalled.append((seen, conn))
                keep = True
                return
            length = int(headers.get("content-length", ["0"])[0])
            while len(seen.body) < length:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                seen.body += chunk
            with self._lock:
                self.seen.append(seen)
            self._answer(conn)
        except OSError:
            pass
        finally:
            if not keep:
                conn.close()

    def _answer(self, conn: ssl.SSLSocket) -> None:
        json_body = b'{"ok":true}'
        if self.mode == "continue":
            conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
        if self.mode in ("json", "continue"):
            conn.sendall(
                b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\nrequest-id: req_json\r\n"
                b"set-cookie: s=1\r\ncontent-length: %d\r\n\r\n" % len(json_body) + json_body
            )
        elif self.mode == "close":
            conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n\r\n" + json_body)
        elif self.mode == "sse":
            conn.sendall(
                b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\nrequest-id: req_sse\r\n"
                b"retry-after: 1\r\ntransfer-encoding: chunked\r\nconnection: keep-alive\r\n\r\n"
            )
            for index in range(self.events):
                if index:
                    time.sleep(self.gap)
                if index == self.events - 1:
                    self.last_event_at = time.monotonic()
                event = b"event: message\ndata: {\"n\": %d}\n\n" % index
                conn.sendall(b"%x\r\n%s\r\n" % (len(event), event))
            conn.sendall(b"0\r\n\r\n")
        elif self.mode == "redirect":
            conn.sendall(b"HTTP/1.1 302 Found\r\nlocation: %s\r\ncontent-length: 0\r\n\r\n" % self.location.encode())
        elif self.mode == "garbage":
            conn.sendall(b"NOT HTTP AT ALL\r\n\r\n")
        elif self.mode == "hugehead":
            conn.sendall(b"HTTP/1.1 200 OK\r\nx-a: " + b"a" * 70_000 + b"\r\n\r\n")
        elif self.mode == "badchunk":
            conn.sendall(b"HTTP/1.1 200 OK\r\ntransfer-encoding: chunked\r\n\r\nzz\r\nhello\r\n0\r\n\r\n")

    def stalled_bytes(self) -> int:
        """Drain every stalled connection now and count the body bytes it ever received."""
        total = 0
        for seen, conn in self._stalled:
            received = len(seen.body)
            conn.settimeout(2)
            try:
                while chunk := conn.recv(65536):
                    received += len(chunk)
            except (OSError, ssl.SSLError):
                pass
            conn.close()
            total += received
        return total
```

- [ ] **Step 2: Write the failing tests**

`python/tests/test_egress_upstream.py`:

```python
import socket
import ssl
import threading
import time

import pytest

from egress_fixtures import FakeUpstream, tls  # noqa: F401  (tls is a fixture)
from autonomy.egress.upstream import (
    POLL, Gate, RouteClosed, UpstreamError, connect, read_response, response_head, send_all, tls_context,
)


def test_the_close_transition_is_taken_once():
    gate = Gate()
    assert (gate.next_seq(), gate.next_seq()) == (1, 2)
    assert gate.close("lease") is True
    assert gate.close("close") is False
    assert (gate.is_open, gate.cause, gate.last_seq) == (False, "lease", 2)
    assert gate.next_seq() is None


def stalled_pair() -> tuple[socket.socket, socket.socket]:
    sender, peer = socket.socketpair()
    for end in (sender, peer):
        end.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        end.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    sender.setblocking(False)
    return sender, peer


def test_a_stalled_send_never_holds_the_close():
    gate = Gate()
    sender, peer = stalled_pair()
    payload = b"x" * (4 << 20)
    outcome = {}

    def send():
        try:
            send_all(gate, sender, payload)
        except RouteClosed as closed:
            outcome["sent"] = closed.sent
            outcome["at"] = time.monotonic()

    worker = threading.Thread(target=send)
    worker.start()
    time.sleep(0.5)  # the peer never reads: the send is waiting for room
    started = time.monotonic()
    assert gate.close("lease") is True
    assert time.monotonic() - started < 0.1
    worker.join(POLL + 1)
    assert not worker.is_alive()
    assert 0 < outcome["sent"] < len(payload)
    sender.close()
    peer.close()


def test_a_blocking_write_under_the_lock_would_hold_the_close():
    # Negative (E22): the lock held across a blocking write. The close transition then
    # waits for the peer to read, which a stalled upstream never does.
    gate = Gate()
    sender, peer = socket.socketpair()
    sender.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)

    def careless():
        with gate._lock:
            sender.sendall(b"x" * (1 << 20))

    holder = threading.Thread(target=careless, daemon=True)
    holder.start()
    time.sleep(0.2)
    closer = threading.Thread(target=gate.close, args=("lease",), daemon=True)
    closer.start()
    closer.join(1.0)
    assert closer.is_alive()  # still waiting on the lock
    peer.setblocking(False)
    deadline = time.monotonic() + 10
    while (holder.is_alive() or closer.is_alive()) and time.monotonic() < deadline:
        try:
            peer.recv(65536)
        except BlockingIOError:
            time.sleep(0.01)
    sender.close()
    peer.close()


def test_after_the_close_nothing_is_written():
    gate = Gate()
    gate.close("close")
    sender, peer = socket.socketpair()
    with pytest.raises(RouteClosed) as closed:
        send_all(gate, sender, b"POST / HTTP/1.1\r\n\r\n")
    assert closed.value.sent == 0
    peer.setblocking(False)
    with pytest.raises(BlockingIOError):
        peer.recv(1)
    sender.close()
    peer.close()


def exchange(upstream: FakeUpstream, tls) -> tuple:
    gate = Gate()
    sock = connect(gate, "localhost", upstream.port, tls_context(tls.cert))
    send_all(gate, sock, b"POST /v1/messages HTTP/1.1\r\nhost: localhost\r\ncontent-length: 2\r\nconnection: close\r\n\r\n{}")
    response = read_response(gate, sock)
    body = b"".join(response.body)
    sock.close()
    return response, body


@pytest.mark.parametrize("mode", ["json", "continue", "close"])
def test_a_response_is_read_whatever_its_framing(tls, mode):
    upstream = FakeUpstream(tls, mode=mode)
    response, body = exchange(upstream, tls)
    assert (response.status, body) == (200, b'{"ok":true}')
    assert upstream.seen[0].body == b"{}"


def test_a_chunked_stream_is_decoded(tls):
    upstream = FakeUpstream(tls, mode="sse")
    response, body = exchange(upstream, tls)
    assert response.request_id == "req_sse"
    assert body.count(b"event: message") == upstream.events


def test_verification_is_never_disabled(tls):
    upstream = FakeUpstream(tls)
    with pytest.raises(UpstreamError) as caught:
        connect(Gate(), "localhost", upstream.port, tls_context(None))
    assert "certificate" in str(caught.value).lower()


@pytest.mark.parametrize("mode", ["garbage", "hugehead", "badchunk"])
def test_a_malformed_answer_is_an_upstream_error_never_a_hang(tls, mode):  # Review Focus 2
    upstream = FakeUpstream(tls, mode=mode)
    outcome = {}

    def run():
        try:
            exchange(upstream, tls)
        except UpstreamError as caught:
            outcome["error"] = caught

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(10)
    assert not worker.is_alive()
    assert "error" in outcome


def test_the_response_head_drops_hop_and_credential_headers(tls):
    upstream = FakeUpstream(tls, mode="sse")
    response, _ = exchange(upstream, tls)
    head = response_head(response).decode()
    assert head.startswith("HTTP/1.1 200 OK\r\n")
    assert "request-id: req_sse" in head and "retry-after: 1" in head
    assert "set-cookie" not in head and "transfer-encoding" not in head and "keep-alive" not in head
    assert head.endswith("connection: close\r\n\r\n")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `just test-one tests/test_egress_upstream.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.egress.upstream'`.

- [ ] **Step 4: Implement**

`python/src/autonomy/egress/upstream.py`:

```python
"""The proxy's upstream side (envelope design decision 13).

`Gate` holds the route's open flag and the lock that the close transition takes. The
lock is held only for a flag check and one non-blocking write, so the transition never
waits on an upstream that stops reading. Every wait (for room to write, for bytes to
read, for a TLS handshake) happens outside the lock and gives up within `POLL` seconds
of the close. Reads off a closed route end the stream."""

from __future__ import annotations

import re
import select
import socket
import ssl
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from autonomy.egress.route import always_dropped

POLL = 0.2
MAX_RESPONSE_HEAD = 64 * 1024
_STATUS = re.compile(rb"HTTP/1\.[01] ([0-9]{3})(?: (.*))?")
_HEX = re.compile(rb"[0-9A-Fa-f]{1,16}")
_DIGITS = re.compile(r"[0-9]{1,15}")


class RouteClosed(Exception):
    """The route closed before this request was done: `sent` bytes went upstream."""

    def __init__(self, sent: int = 0) -> None:
        super().__init__("the route is closed")
        self.sent = sent


class UpstreamError(Exception):
    """The upstream could not be reached, failed TLS verification, or answered
    something that is not HTTP/1.1."""


class Gate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open = True
        self._seq = 0
        self.cause: str | None = None
        self.last_seq = 0

    @property
    def is_open(self) -> bool:
        """A hint for waits. Every write rechecks the flag under the lock."""
        return self._open

    def next_seq(self) -> int | None:
        with self._lock:
            if not self._open:
                return None
            self._seq += 1
            return self._seq

    def close(self, cause: str) -> bool:
        """The close transition: no byte goes upstream after it returns."""
        with self._lock:
            if not self._open:
                return False
            self._open = False
            self.cause = cause
            self.last_seq = self._seq
            return True

    def attempt(self, sock: socket.socket, data: memoryview) -> int | None:
        """One non-blocking write while the route is open; None once it is closed."""
        with self._lock:
            if not self._open:
                return None
            return sock.send(data)


def _wait(gate: Gate, sock: socket.socket, *, readable: bool) -> None:
    while gate.is_open:
        ready = select.select([sock] if readable else [], [] if readable else [sock], [], POLL)
        if ready[0] or ready[1]:
            return
    raise RouteClosed()


def send_all(gate: Gate, sock: socket.socket, data: bytes) -> None:
    """Write `data` in non-blocking attempts under the gate's lock. A TLS write that
    needs a read or a write first, or a full buffer, waits outside the lock and
    retries with the same bytes (OpenSSL requires it), rechecking the flag."""
    view = memoryview(data)
    sent = 0
    while sent < len(data):
        try:
            written = gate.attempt(sock, view[sent:])
        except ssl.SSLWantReadError:
            readable = True
        except (ssl.SSLWantWriteError, BlockingIOError, InterruptedError):
            readable = False
        else:
            if written is None:
                raise RouteClosed(sent)
            sent += written
            continue
        try:
            _wait(gate, sock, readable=readable)
        except RouteClosed:
            raise RouteClosed(sent) from None


def tls_context(ca_file: Path | None) -> ssl.SSLContext:
    """Verification on, always: the system trust store, or the route's `ca_file`."""
    return ssl.create_default_context(cafile=str(ca_file) if ca_file is not None else None)


def connect(gate: Gate, host: str, port: int, context: ssl.SSLContext, *, timeout: float = 30.0) -> ssl.SSLSocket:
    try:
        raw = socket.create_connection((host, port), timeout=timeout)
    except OSError as caught:
        raise UpstreamError(f"cannot reach {host}:{port}: {caught}") from caught
    raw.setblocking(False)
    tls = context.wrap_socket(raw, server_hostname=host, do_handshake_on_connect=False)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                tls.do_handshake()
                return tls
            except ssl.SSLWantReadError:
                readable = True
            except ssl.SSLWantWriteError:
                readable = False
            except ssl.SSLError as caught:
                raise UpstreamError(f"TLS with {host}: {caught}") from caught
            if time.monotonic() > deadline:
                raise UpstreamError(f"the TLS handshake with {host} took over {timeout:g} s")
            _wait(gate, tls, readable=readable)
    except BaseException:
        tls.close()
        raise


class _Reader:
    def __init__(self, gate: Gate, sock: socket.socket) -> None:
        self._gate = gate
        self._sock = sock
        self.buffer = bytearray()

    def _fill(self) -> bool:
        while True:
            try:
                chunk = self._sock.recv(65536)
            except ssl.SSLWantReadError:
                _wait(self._gate, self._sock, readable=True)
                continue
            except ssl.SSLWantWriteError:
                _wait(self._gate, self._sock, readable=False)
                continue
            except (BlockingIOError, InterruptedError):
                _wait(self._gate, self._sock, readable=True)
                continue
            except (ssl.SSLEOFError, ssl.SSLZeroReturnError):
                chunk = b""
            if not chunk:
                return False
            self.buffer += chunk
            return True

    def until(self, marker: bytes, limit: int) -> bytes:
        while (at := self.buffer.find(marker)) < 0:
            if len(self.buffer) > limit:
                raise UpstreamError(f"the upstream sent over {limit} bytes without {marker!r}")
            if not self._fill():
                raise UpstreamError("the upstream closed mid-head")
        if at > limit:
            raise UpstreamError(f"the upstream sent over {limit} bytes before {marker!r}")
        found = bytes(self.buffer[:at])
        del self.buffer[: at + len(marker)]
        return found

    def exactly(self, count: int) -> Iterator[bytes]:
        while count:
            if not self.buffer and not self._fill():
                raise UpstreamError("the upstream closed mid-body")
            piece = bytes(self.buffer[:count])
            del self.buffer[: len(piece)]
            count -= len(piece)
            yield piece

    def rest(self) -> Iterator[bytes]:
        while True:
            if self.buffer:
                piece = bytes(self.buffer)
                self.buffer.clear()
                yield piece
            if not self._fill():
                return


def _chunked(reader: _Reader) -> Iterator[bytes]:
    while True:
        size_text = reader.until(b"\r\n", 1024).split(b";", 1)[0].strip()
        if not _HEX.fullmatch(size_text):
            raise UpstreamError("a chunk size that is not hex")
        size = int(size_text, 16)
        if size == 0:
            while reader.until(b"\r\n", 8192):
                pass
            return
        yield from reader.exactly(size)
        if reader.until(b"\r\n", 16):
            raise UpstreamError("a chunk without its CRLF")


@dataclass
class Response:
    status: int
    reason: str
    headers: tuple[tuple[str, str], ...]
    body: Iterator[bytes]

    @property
    def request_id(self) -> str | None:
        return next((value for name, value in self.headers if name == "request-id"), None)


def read_response(gate: Gate, sock: socket.socket) -> Response:
    reader = _Reader(gate, sock)
    while True:
        head = reader.until(b"\r\n\r\n", MAX_RESPONSE_HEAD)
        status_line, *lines = head.split(b"\r\n")
        match = _STATUS.fullmatch(status_line)
        if match is None:
            raise UpstreamError(f"not an HTTP/1.1 status line: {status_line[:80]!r}")
        headers: list[tuple[str, str]] = []
        for line in lines:
            name, colon, value = line.partition(b":")
            if not colon or not name or name != name.strip():
                raise UpstreamError("a malformed response header")
            headers.append((name.decode("latin-1").lower(), value.strip(b" \t").decode("latin-1")))
        status = int(match[1])
        if 100 <= status < 200:
            continue  # an interim response: the final one follows
        break
    reason = (match[2] or b"").decode("latin-1")
    codings = [value for name, value in headers if name == "transfer-encoding"]
    lengths = [value for name, value in headers if name == "content-length"]
    if status in (204, 304):
        body: Iterator[bytes] = iter(())
    elif codings:
        if codings[-1].split(",")[-1].strip().lower() != "chunked":
            raise UpstreamError(f"a transfer coding the proxy does not decode: {codings[-1]}")
        body = _chunked(reader)
    elif lengths:
        if len(set(lengths)) != 1 or not _DIGITS.fullmatch(lengths[0]):
            raise UpstreamError("an unusable Content-Length")
        body = reader.exactly(int(lengths[0]))
    else:
        body = reader.rest()
    return Response(status, reason, tuple(headers), body)


def response_head(response: Response) -> bytes:
    """The head the actor gets: the upstream's end-to-end headers less the
    always-dropped set, and the proxy's own framing (the body ends at close)."""
    lines = [f"HTTP/1.1 {response.status} {response.reason}".rstrip()]
    lines += [f"{name}: {value}" for name, value in response.headers if not always_dropped(name)]
    lines.append("connection: close")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `just test-one tests/test_egress_upstream.py`
Expected: PASS.

- [ ] **Step 6: Run the fast suite, then commit**

Run: `just test-fast`. Expected: PASS.

```bash
git add python/src/autonomy/egress/upstream.py python/tests/egress_fixtures.py python/tests/test_egress_upstream.py
git commit -m "feat(egress): the close transition's gate and a non-blocking TLS upstream client"
```

---
### Task 7: The proxy server: one request per connection, checked, framed, streamed, recorded

**Files:**
- Create: `python/src/autonomy/egress/server.py`
- Modify: `python/src/autonomy/egress/upstream.py` (a read off a closed route raises
  `RouteClosed`; see Step 3)
- Modify: `python/tests/egress_fixtures.py` (add `raw_request`, `exchange`, `Served`,
  `served`)
- Test: `python/tests/test_egress_server.py`

**Interfaces:**
- Consumes:
  - Tasks 2, 4, 5 and 6: `Route`, `Operation`, `parse_head`, `forwarded_headers`,
    `frame`, `refusal`, `MAX_HEAD`, `parse_body`, `check_body`, `Gate`, `RouteClosed`,
    `UpstreamError`, `connect`, `read_response`, `response_head`, `send_all`,
    `tls_context` and `Refused`;
  - from `autonomy.baseline`: `utc_now` and `write_all`.
- Produces:
  - `JOIN_TIMEOUT = 2.0`;
  - `Recorder(fd)` with `.line(record)`. After the closing line it writes nothing
    more, so the closing line is always last;
  - the protocol `Allowance` with `admit(operation, model, request_bytes, in_flight)
    -> str | None` and `settle(seq, upstream_request_id, usage) -> None`;
  - `NoAllowance`;
  - `Hooks(hold: Callable[[str, int], None])`, with the stages `parsed`,
    `body-checked`, `admit`, `connecting` and `before-send`;
  - `ProxyServer(route, credential, recorder, *, context, allowance=None,
    hooks=Hooks())`, with `.gate`, `.serve(listener)` and `.close(cause) -> bool`;
  - in the fixtures: `raw_request(*, method="POST", target="/v1/messages?beta=true",
    headers=(), body: bytes | dict = b"") -> bytes`, `exchange(port: int, data: bytes,
    *, timeout: float = 10) -> bytes`, and the fixture `served` yielding
    `Served(server, port, upstream, other, records(), canary)`.

- [ ] **Step 1: Add the fixtures**

Append to `python/tests/egress_fixtures.py` (add `from collections.abc import
Iterable` to its imports):

```python
CANARY = "sk-canary-6b1f0e9d2c7a"


def raw_request(*, method: str = "POST", target: str = "/v1/messages?beta=true",
                headers: Iterable[tuple[str, str]] = (), body: bytes | dict = b"") -> bytes:
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    lines = [f"{method} {target} HTTP/1.1", "host: 127.0.0.1:4780",
             "anthropic-version: 2023-06-01", "content-type: application/json"]
    lines += [f"{name}: {value}" for name, value in headers]
    if not any(name.lower() in ("content-length", "transfer-encoding") for name, _ in headers):
        lines.append(f"content-length: {len(data)}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + data


def message(**extra) -> dict:
    return {"model": MODEL, "max_tokens": 16, "stream": True,
            "messages": [{"role": "user", "content": "hi"}], **extra}


def exchange(port: int, data: bytes, *, timeout: float = 10) -> bytes:
    """Send `data` on a fresh connection to 127.0.0.1:`port`, read until the proxy closes."""
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.sendall(data)
        received = b""
        while chunk := sock.recv(65536):
            received += chunk
    return received


def status_and_body(answer: bytes) -> tuple[int, bytes]:
    head, _, body = answer.partition(b"\r\n\r\n")
    return int(head.split(b" ", 2)[1]), body
```

And a fixture that runs a `ProxyServer` in-process against a `FakeUpstream`:

```python
@dataclass
class Served:
    server: "object"
    port: int
    upstream: FakeUpstream
    other: FakeUpstream
    records_path: Path
    canary: str

    def records(self) -> list[dict]:
        return [json.loads(line) for line in self.records_path.read_text().splitlines()]


def make_served(tmp_path: Path, tls: Tls, *, mode: str = "json", hooks=None, allowance=None, route_changes=None) -> Served:
    from autonomy.egress.route import parse_route
    from autonomy.egress.server import Hooks, ProxyServer, Recorder
    from autonomy.egress.upstream import tls_context

    upstream = FakeUpstream(tls, mode=mode)
    other = FakeUpstream(tls)
    upstream.location = other.origin + "/elsewhere"
    doc = pi_route(credential=tmp_path / "credential", upstream=upstream.origin, ca_file=tls.cert)
    if route_changes is not None:
        route_changes(doc)
    route = parse_route(to_toml(doc).encode())
    records_path = tmp_path / "egress.jsonl"
    fd = os.open(records_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    server = ProxyServer(route, CANARY, Recorder(fd), context=tls_context(tls.cert),
                         allowance=allowance, hooks=hooks or Hooks())
    listener = socket.create_server(("127.0.0.1", 0))
    server.serve(listener)
    return Served(server, listener.getsockname()[1], upstream, other, records_path, CANARY)


@pytest.fixture
def served(tmp_path, tls):
    s = make_served(tmp_path, tls)
    yield s
    s.server.close("close")
    s.upstream.stop()
    s.other.stop()
```

- [ ] **Step 2: Write the failing tests**

`python/tests/test_egress_server.py`:

```python
import json
import socket
import threading
import time

import pytest

from egress_fixtures import (  # noqa: F401  (tls and served are fixtures)
    CANARY, MODEL, PI_BETAS, exchange, make_served, message, raw_request, served, status_and_body, tls,
)
from autonomy.egress.server import Hooks
from autonomy.egress.upstream import Gate


def test_an_allowed_request_streams_as_it_arrives(tmp_path, tls):  # E21
    s = make_served(tmp_path, tls, mode="sse")
    s.upstream.events, s.upstream.gap = 5, 0.3
    body = json.dumps(message()).encode()
    first_at = None
    received = b""
    with socket.create_connection(("127.0.0.1", s.port), timeout=10) as sock:
        sock.sendall(raw_request(body=body, headers=[("x-api-key", "placeholder")]))
        while chunk := sock.recv(65536):
            received += chunk
            if first_at is None and b"event: message" in received:
                first_at = time.monotonic()
    s.server.close("close")
    assert first_at is not None and first_at < s.upstream.last_event_at
    assert received.count(b"event: message") == 5
    (seen,) = s.upstream.seen
    assert seen.headers["host"] == [f"localhost:{s.upstream.port}"]
    assert seen.headers["x-api-key"] == [CANARY]
    assert "authorization" not in seen.headers
    assert seen.body == body
    line = s.records()[0]
    assert (line["seq"], line["status"], line["forwarded"], line["ended"], line["refused"]) == (1, 200, True, "complete", None)
    assert line["upstream_request_id"] == "req_sse" and line["model"] == MODEL and line["response_bytes"] > 0


REFUSED = {
    "CONNECT": (raw_request(method="CONNECT", target="api.anthropic.com:443"), "target-refused"),
    "absolute-form": (raw_request(target="http://other/v1/messages?beta=true", body=message()), "target-refused"),
    "authority-form": (raw_request(target="other:443", body=message()), "target-refused"),
    "dot-dot": (raw_request(target="/v1/messages/../x?beta=true", body=message()), "operation-refused"),
    "encoded dot-dot": (raw_request(target="/v1/%2e%2e/x?beta=true", body=message()), "operation-refused"),
    "double slash": (raw_request(target="//other/v1/messages?beta=true", body=message()), "operation-refused"),
    "dot segment": (raw_request(target="/v1/messages/./?beta=true", body=message()), "operation-refused"),
    "query outside the route": (raw_request(target="/v1/messages", body=message()), "operation-refused"),
    "model outside the route": (raw_request(body=message(model="claude-opus-5-5")), "model-refused"),
    "upgrade": (raw_request(headers=[("upgrade", "h2c")], body=message()), "target-refused"),
    "chunked smuggle": (raw_request(
        headers=[("transfer-encoding", "chunked")],
        body=b"0\r\n\r\nPOST /v1/admin HTTP/1.1\r\nhost: x\r\ncontent-length: 0\r\n\r\n"), "request-malformed"),
    "too large": (raw_request(headers=[("content-length", "9000000")]), "request-too-large"),
    "mcp servers": (raw_request(body=message(mcp_servers=[{"type": "url", "url": "https://x", "name": "x"}])), "body-refused"),
    "web fetch": (raw_request(body=message(tools=[{"type": "web_fetch_20250910", "name": "web_fetch"}])), "body-refused"),
    "url source": (raw_request(body=message(messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "url", "url": "https://x/i.png"}}]}])), "body-refused"),
    "file source": (raw_request(body=message(messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "file", "file_id": "f"}}]}])), "body-refused"),
    "unlisted block": (raw_request(body=message(messages=[{"role": "user", "content": [
        {"type": "search_result", "content": []}]}])), "body-refused"),
    "unlisted block in a tool result": (raw_request(body=message(messages=[{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t", "content": [{"type": "search_result"}]}]}])), "body-refused"),
    "unlisted beta": (raw_request(headers=[("anthropic-beta", "mcp-client-2025-04-04")], body=message()), "header-refused"),
    "beta on two lines": (raw_request(headers=[("anthropic-beta", PI_BETAS[0]), ("anthropic-beta", "mcp-client-2025-04-04")],
                                      body=message()), "header-refused"),
    "beta in two cases": (raw_request(headers=[("anthropic-beta", PI_BETAS[0]), ("Anthropic-Beta", PI_BETAS[0])],
                                      body=message()), "header-refused"),
    "unlisted version": (raw_request(headers=[("anthropic-version", "2099-01-01")], body=message())
                         .replace(b"anthropic-version: 2023-06-01\r\n", b"", 1), "header-refused"),
    "model twice": (raw_request(body=b'{"model": "%s", "model": "claude-opus-5-5", "messages": []}' % MODEL.encode()),
                    "request-malformed"),
    "byte-order mark": (raw_request(body=b"\xef\xbb\xbf" + json.dumps(message()).encode()), "request-malformed"),
    "NaN": (raw_request(body=b'{"model": "%s", "temperature": NaN}' % MODEL.encode()), "request-malformed"),
}


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_refused_requests_never_reach_the_upstream(served, case):  # E21
    data, code = REFUSED[case]
    status, body = status_and_body(exchange(served.port, data))
    assert status == 403
    assert json.loads(body)["error"]["code"] == code
    assert served.upstream.seen == [] and served.upstream.connections == 0
    assert served.records()[0]["refused"] == code


def test_an_operation_refusal_names_the_routes_operations(served):
    _, body = status_and_body(exchange(served.port, raw_request(target="/v1/complete", body=message())))
    assert "POST /v1/messages?beta=true" in json.loads(body)["error"]["message"]


def test_actor_credentials_are_stripped_and_replaced(served):  # E21
    exchange(served.port, raw_request(body=message(), headers=[
        ("connection", "x-api-key"), ("x-api-key", "placeholder"), ("authorization", "Bearer sk-ant-oat01-x"),
        ("x-probe", "1"), ("cookie", "c=1"),
    ]))
    (seen,) = served.upstream.seen
    assert seen.headers["x-api-key"] == [CANARY]
    for name in ("authorization", "x-probe", "cookie"):
        assert name not in seen.headers
    assert seen.headers["connection"] == ["close"]


def test_destination_overrides_reach_only_the_upstream(served):  # E21
    for headers in ([("host", "other")], [("x-forwarded-host", "other")], [("forwarded", "host=other")]):
        data = raw_request(body=message(), headers=headers).replace(b"host: 127.0.0.1:4780\r\n", b"", 1)
        assert status_and_body(exchange(served.port, data))[0] == 200
    assert len(served.upstream.seen) == 3
    assert all(seen.headers["host"] == [f"localhost:{served.upstream.port}"] for seen in served.upstream.seen)
    assert served.other.connections == 0


def test_a_redirect_returns_to_the_actor_and_is_never_followed(tmp_path, tls):  # E21
    s = make_served(tmp_path, tls, mode="redirect")
    answer = exchange(s.port, raw_request(body=message()))
    s.server.close("close")
    assert status_and_body(answer)[0] == 302
    assert s.other.origin.encode() in answer
    assert s.other.connections == 0


def test_a_pipelined_second_request_is_never_parsed(served):  # Review Focus 1
    second = raw_request(target="/v1/complete", body=message())
    answer = exchange(served.port, raw_request(body=message()) + second)
    assert answer.count(b"HTTP/1.1 ") == 1
    assert len(served.upstream.seen) == 1
    assert [line["seq"] for line in served.records()] == [1]


def test_an_actor_that_hangs_up_mid_stream_ends_its_request(tmp_path, tls):  # Review Focus 3
    s = make_served(tmp_path, tls, mode="sse")
    s.upstream.events, s.upstream.gap = 20, 0.2
    with socket.create_connection(("127.0.0.1", s.port), timeout=10) as sock:
        sock.sendall(raw_request(body=message()))
        received = b""
        while b"event: message" not in received:
            received += sock.recv(65536)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not s.records():
        time.sleep(0.1)
    s.server.close("close")
    assert s.records()[0]["ended"] == "actor-closed"
    assert not s.server._actors and not s.server._upstreams


def test_twenty_concurrent_requests_are_all_served(tmp_path, tls):  # Review Focus 4
    seen_in_flight = []

    class Spy:
        def admit(self, operation, model, request_bytes, in_flight):
            seen_in_flight.append(in_flight)
            time.sleep(0.05)
            return None

        def settle(self, seq, upstream_request_id, usage):
            return None

    s = make_served(tmp_path, tls, allowance=Spy())
    answers = []
    threads = [threading.Thread(target=lambda: answers.append(exchange(s.port, raw_request(body=message()))))
               for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    s.server.close("close")
    assert len(answers) == 20 and all(status_and_body(a)[0] == 200 for a in answers)
    seqs = sorted(line["seq"] for line in s.records() if "closed" not in line)
    assert seqs == list(range(1, 21))
    assert max(seen_in_flight) > 1


def test_an_allowance_refusal_is_answered_and_never_forwarded(tmp_path, tls):
    class Refuse:
        def admit(self, operation, model, request_bytes, in_flight):
            return "the run's allowance is spent"

        def settle(self, seq, upstream_request_id, usage):
            raise AssertionError("never settled")

    s = make_served(tmp_path, tls, allowance=Refuse())
    status, body = status_and_body(exchange(s.port, raw_request(body=message())))
    s.server.close("close")
    assert status == 403 and json.loads(body)["error"]["code"] == "allowance-refused"
    assert s.upstream.seen == []


class Holder:
    """Blocks request 1 at one stage until released, and says when it got there."""

    def __init__(self, stage: str) -> None:
        self.stage = stage
        self.reached = threading.Event()
        self.release = threading.Event()

    def __call__(self, stage: str, seq: int) -> None:
        if stage == self.stage and seq == 1:
            self.reached.set()
            assert self.release.wait(20)


def close_while_held(s, holder: Holder) -> bytes:
    answer = {}
    client = threading.Thread(target=lambda: answer.setdefault("raw", exchange(s.port, raw_request(body=message()))))
    client.start()
    assert holder.reached.wait(10)
    closer = threading.Thread(target=s.server.close, args=("close",))
    closer.start()
    deadline = time.monotonic() + 5
    while s.server.gate.is_open and time.monotonic() < deadline:
        time.sleep(0.01)
    holder.release.set()
    closer.join(10)
    client.join(10)
    return answer["raw"]


@pytest.mark.parametrize("stage", ["before-send", "connecting", "admit", "body-checked"])
def test_a_request_held_before_its_first_byte_never_goes_upstream(tmp_path, tls, stage):  # E22
    holder = Holder(stage)
    s = make_served(tmp_path, tls, hooks=Hooks(hold=holder))
    raw = close_while_held(s, holder)
    status, body = status_and_body(raw)
    assert status == 403 and json.loads(body)["error"]["code"] == "route-closed"
    assert s.upstream.seen == []
    held, closing = s.records()
    assert (held["seq"], held["refused"], held["forwarded"]) == (1, "route-closed", False)
    assert closing["closed"] == "close" and held["seq"] <= closing["last_seq"]


def test_a_check_only_at_acceptance_would_send_after_the_close(tmp_path, tls, monkeypatch):
    # Negative (E22): a gate whose write ignores the flag sends the held request, though
    # its seq still passes the last_seq check.
    monkeypatch.setattr(Gate, "attempt", lambda self, sock, data: sock.send(data))
    holder = Holder("before-send")
    s = make_served(tmp_path, tls, hooks=Hooks(hold=holder))
    close_while_held(s, holder)
    time.sleep(0.5)
    assert len(s.upstream.seen) == 1


def test_after_the_close_a_connect_is_refused(served):
    served.server.close("close")
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", served.port), timeout=2)


def test_a_stalled_upstream_never_delays_the_close(tmp_path, tls):  # E22, with the lease in Task 8
    s = make_served(tmp_path, tls, mode="stall")
    big = json.dumps(message(system="x" * 6_000_000)).encode()
    client = threading.Thread(target=lambda: exchange(s.port, raw_request(body=big), timeout=30), daemon=True)
    client.start()
    deadline = time.monotonic() + 10
    while not s.upstream.seen and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.5)  # the body fills the buffers; the send waits for room
    started = time.monotonic()
    assert s.server.close("lease")
    assert time.monotonic() - started < 1.0 + 2.0  # the transition at once; joins bounded by JOIN_TIMEOUT
    client.join(5)
    line = s.records()[0]
    assert (line["ended"], line["forwarded"]) == ("route-closed", True)
    assert s.upstream.stalled_bytes() < len(big)


def test_no_record_holds_the_credential(served):
    exchange(served.port, raw_request(body=message()))
    exchange(served.port, raw_request(body=message(model="other")))
    served.server.close("close")
    text = served.records_path.read_text()
    assert CANARY not in text
    assert json.loads(text.splitlines()[-1]).keys() == {"at", "closed", "last_seq"}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `just test-one tests/test_egress_server.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.egress.server'`.

- [ ] **Step 4: Implement**

In `python/src/autonomy/egress/upstream.py`, a stream cut by the close must never
look complete. In `_Reader._fill`, replace `if not chunk: return False` with:

```python
            if not chunk:
                if not self._gate.is_open:
                    raise RouteClosed()
                return False
```

Add a module helper that `server` uses to cut a socket without detaching a TLS
read in progress in another thread:

```python
def cut(sock: socket.socket, how: int = socket.SHUT_RDWR) -> None:
    """Shut a socket down at its descriptor. `SSLSocket.shutdown` would drop its TLS
    state under a read in another thread, which then reads raw bytes as plaintext:
    the base method leaves it, and that read fails or sees EOF."""
    try:
        socket.socket.shutdown(sock, how)
    except OSError:
        pass
```

`python/src/autonomy/egress/server.py`:

```python
"""The proxy's request handling (envelope design decision 13). Each actor connection
carries one request, checked in the spec's order, framed by the proxy, streamed back
and recorded. The close transition and every socket the server opened belong to the
server. The control loop that decides when to close is in `proxy`."""

from __future__ import annotations

import json
import socket
import ssl
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from autonomy.baseline import utc_now, write_all
from autonomy.egress.dialect import check_body, parse_body
from autonomy.egress.errors import Refused
from autonomy.egress.request import MAX_HEAD, forwarded_headers, frame, parse_head, refusal
from autonomy.egress.route import Operation, Route
from autonomy.egress.upstream import (
    Gate, RouteClosed, UpstreamError, connect, cut, read_response, response_head, send_all,
)

JOIN_TIMEOUT = 2.0


class Recorder:
    """`egress.jsonl`: one line per request, written when it ends, then the closing line.
    Nothing follows the closing line: a worker still running after the close's bounded
    join loses its line, and its request was cut at the transition."""

    def __init__(self, fd: int) -> None:
        self._fd = fd
        self._lock = threading.Lock()
        self._closed = False

    def line(self, record: Mapping[str, object]) -> None:
        data = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        with self._lock:
            if self._closed:
                return
            if "closed" in record:
                self._closed = True
            write_all(self._fd, data)


class Allowance(Protocol):
    """autonomy-9e8a43's join points (decision 13): `admit` before any byte goes
    upstream, `settle` when the response stream ends, however it ended."""

    def admit(self, operation: Operation, model: str, request_bytes: int, in_flight: int) -> str | None: ...

    def settle(self, seq: int, upstream_request_id: str | None, usage: Mapping[str, object] | None) -> None: ...


class NoAllowance:
    """Until an allowance exists, `admit` allows every request the route permits and
    `settle` does nothing beyond the record line."""

    def admit(self, operation: Operation, model: str, request_bytes: int, in_flight: int) -> str | None:
        return None

    def settle(self, seq: int, upstream_request_id: str | None, usage: Mapping[str, object] | None) -> None:
        return None


def _no_hold(stage: str, seq: int) -> None:
    return None


@dataclass(frozen=True)
class Hooks:
    """A test seam: `hold(stage, seq)` runs at each stage before a request's first byte
    goes upstream: `parsed`, `body-checked`, `admit`, `connecting`, `before-send`."""

    hold: Callable[[str, int], None] = _no_hold


class _ActorGone(Exception):
    pass


def _bad_gateway(message: str) -> bytes:
    body = json.dumps({"type": "error", "error": {"type": "egress_upstream", "message": message}}).encode()
    head = (
        "HTTP/1.1 502 Bad Gateway\r\ncontent-type: application/json\r\n"
        f"content-length: {len(body)}\r\nconnection: close\r\n\r\n"
    )
    return head.encode("ascii") + body


class ProxyServer:
    def __init__(
        self, route: Route, credential: str, recorder: Recorder, *, context: ssl.SSLContext,
        allowance: Allowance | None = None, hooks: Hooks = Hooks(),
    ) -> None:
        self.route = route
        self.recorder = recorder
        self.gate = Gate()
        self._credential = credential
        self._context = context
        self._allowance = allowance or NoAllowance()
        self._hooks = hooks
        self._listener: socket.socket | None = None
        self._actors: set[socket.socket] = set()
        self._upstreams: set[socket.socket] = set()
        self._threads: list[threading.Thread] = []
        self._shut = False
        self._in_flight = 0
        self._lock = threading.Lock()

    # -- lifecycle -----------------------------------------------------------------

    def serve(self, listener: socket.socket) -> None:
        self._listener = listener
        self._start(self._accept)

    def close(self, cause: str) -> bool:
        """The close transition, then: stop accepting, cut every upstream socket, shut
        each actor connection for reading (a worker waiting on the actor wakes, and a
        cancelled request can still be answered `route-closed`), join the workers for
        at most `JOIN_TIMEOUT`, and write the closing line. Nothing here waits on a
        peer."""
        if not self.gate.close(cause):
            return False
        with self._lock:
            self._shut = True
            actors = list(self._actors)
            upstreams = list(self._upstreams)
            threads = list(self._threads)
        if self._listener is not None:
            cut(self._listener)
            self._listener.close()
        for sock in upstreams:
            cut(sock)
        for sock in actors:
            cut(sock, socket.SHUT_RD)
        deadline = time.monotonic() + JOIN_TIMEOUT
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(max(0.0, deadline - time.monotonic()))
        self.recorder.line({"at": utc_now(), "closed": cause, "last_seq": self.gate.last_seq})
        return True

    def _start(self, target: Callable[..., None], *args: object) -> None:
        thread = threading.Thread(target=target, args=args, daemon=True)
        with self._lock:
            self._threads.append(thread)
        thread.start()

    def _track(self, sock: socket.socket, *, upstream: bool) -> bool:
        with self._lock:
            if self._shut:
                return False
            (self._upstreams if upstream else self._actors).add(sock)
            return True

    def _release(self, sock: socket.socket) -> None:
        with self._lock:
            self._actors.discard(sock)
            self._upstreams.discard(sock)
        cut(sock)
        sock.close()

    def _accept(self) -> None:
        assert self._listener is not None
        while True:
            try:
                conn, _ = self._listener.accept()
            except OSError:
                return
            if not self._track(conn, upstream=False):
                conn.close()
                return
            self._start(self._handle, conn)

    # -- the actor's side ------------------------------------------------------------

    @staticmethod
    def _recv(conn: socket.socket) -> bytes:
        try:
            return conn.recv(65536)
        except OSError as caught:
            raise _ActorGone() from caught

    @staticmethod
    def _to_actor(conn: socket.socket, data: bytes) -> None:
        try:
            conn.sendall(data)
        except OSError as caught:
            raise _ActorGone() from caught

    @staticmethod
    def _answer(conn: socket.socket, data: bytes) -> None:
        try:
            conn.sendall(data)
        except OSError:
            pass

    def _read_head(self, conn: socket.socket) -> tuple[bytes, bytes] | None:
        buffer = b""
        while (at := buffer.find(b"\r\n\r\n")) < 0:
            if len(buffer) > MAX_HEAD:
                raise Refused("request-malformed", f"a request head over {MAX_HEAD} bytes")
            chunk = self._recv(conn)
            if not chunk:
                if not buffer:
                    return None
                raise _ActorGone()
            buffer += chunk
        if at > MAX_HEAD:
            raise Refused("request-malformed", f"a request head over {MAX_HEAD} bytes")
        return buffer[:at], buffer[at + 4:]

    def _read_body(self, conn: socket.socket, rest: bytes, length: int) -> bytes:
        """Exactly `length` bytes. Anything after them (a pipelined request) is never
        parsed: the connection closes after this one response."""
        body = bytearray(rest[:length])
        while len(body) < length:
            chunk = self._recv(conn)
            if not chunk:
                raise _ActorGone()
            body += chunk[: length - len(body)]
        return bytes(body)

    # -- one request -----------------------------------------------------------------

    def _handle(self, conn: socket.socket) -> None:
        record: dict[str, object] = {
            "at": utc_now(), "seq": None, "method": None, "path": None, "query": None, "model": None,
            "status": None, "refused": None, "upstream_request_id": None, "request_bytes": 0,
            "response_bytes": 0, "forwarded": False, "ended": "complete",
        }
        upstream: socket.socket | None = None
        answered = False
        try:
            head = self._read_head(conn)
            if head is None:
                return  # closed before a request: nothing to record
            record["at"] = utc_now()
            seq = self.gate.next_seq()
            if seq is None:
                raise Refused("route-closed", "the route is closed")
            record["seq"] = seq
            request = parse_head(head[0])
            record.update(method=request.method, path=request.path, query=request.query)
            if request.content_length > self.route.max_request_bytes:
                raise Refused(
                    "request-too-large",
                    f"{request.content_length} bytes; the route allows {self.route.max_request_bytes}",
                )
            op = self.route.operation(request.method, request.path, request.query)
            if op is None:
                target = request.path + (f"?{request.query}" if request.query else "")
                raise Refused(
                    "operation-refused",
                    f"{request.method} {target} is not an operation of the route; it allows {self.route.describe()}",
                )
            headers = forwarded_headers(request, self.route)
            self._hooks.hold("parsed", seq)
            body = self._read_body(conn, head[1], request.content_length)
            record["request_bytes"] = len(body)
            parsed = parse_body(body)
            if isinstance(parsed.get("model"), str):
                record["model"] = parsed["model"]
            check_body(parsed, op)
            self._hooks.hold("body-checked", seq)
            with self._lock:
                self._in_flight += 1
                in_flight = self._in_flight
            try:
                verdict = self._allowance.admit(op, parsed["model"], len(body), in_flight)
                if verdict is not None:
                    raise Refused("allowance-refused", verdict)
                self._hooks.hold("admit", seq)
                if not self.gate.is_open:
                    raise Refused("route-closed", "the route is closed")
                self._hooks.hold("connecting", seq)
                upstream = connect(self.gate, self.route.host, self.route.port, self._context)
                if not self._track(upstream, upstream=True):
                    raise RouteClosed()
                payload = frame(request, self.route, headers, body, self._credential)
                self._hooks.hold("before-send", seq)
                send_all(self.gate, upstream, payload)
                record["forwarded"] = True
                response = read_response(self.gate, upstream)
                record.update(status=response.status, upstream_request_id=response.request_id)
                answered = True
                self._to_actor(conn, response_head(response))
                for piece in response.body:
                    self._to_actor(conn, piece)
                    record["response_bytes"] = int(record["response_bytes"]) + len(piece)
                self._allowance.settle(seq, response.request_id, None)
            finally:
                with self._lock:
                    self._in_flight -= 1
        except Refused as refused:
            record.update(refused=refused.code, status=403)
            self._answer(conn, refusal(refused.code, refused.message))
        except RouteClosed as closed:
            record["ended"] = "route-closed"
            if closed.sent:
                record["forwarded"] = True
            if not record["forwarded"]:
                record.update(refused="route-closed", status=403)
                self._answer(conn, refusal("route-closed", "the route closed before this request went upstream"))
        except _ActorGone:
            record["ended"] = "actor-closed" if self.gate.is_open else "route-closed"
        except (UpstreamError, OSError) as caught:
            if not self.gate.is_open:
                record["ended"] = "route-closed"
                if not record["forwarded"]:
                    record.update(refused="route-closed", status=403)
                    self._answer(conn, refusal("route-closed", "the route closed before this request went upstream"))
            else:
                record["ended"] = "upstream-error"
                if not answered:
                    record["status"] = 502
                    self._answer(conn, _bad_gateway(str(caught)))
        finally:
            if upstream is not None:
                self._release(upstream)
            self._release(conn)
            if record["seq"] is not None or record["refused"] is not None:
                self.recorder.line(record)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `just test-one tests/test_egress_server.py tests/test_egress_upstream.py`
Expected: PASS.

- [ ] **Step 6: Run the fast suite, then commit**

Run: `just test-fast`. Expected: PASS.

```bash
git add python/src/autonomy/egress/server.py python/src/autonomy/egress/upstream.py python/tests/egress_fixtures.py python/tests/test_egress_server.py
git commit -m "feat(egress): the proxy server: checked, framed, streamed and recorded requests"
```

---
### Task 8: The proxy process and its lease; the namespace helper

**Files:**
- Create: `python/src/autonomy/egress/proxy.py`
- Create: `python/src/autonomy/egress/helper.py`
- Test: `python/tests/test_egress_proxy.py`, `python/tests/test_egress_helper.py`

**Interfaces:**
- Consumes:
  - `ProxyServer`, `Recorder` and `Hooks` (Task 7);
  - `parse_route` (Task 2) and `tls_context` (Task 6);
  - `EgressUnproven` and `RouteRefused` (Task 2);
  - `launch(..., before_release=)` (Task 1).
- Produces, from `proxy`:
  - `BOOT`, the program text the proxy's sandbox runs;
  - `IN_SANDBOX_CREDENTIAL = Path("/run/va/credential")` and
    `IN_SANDBOX_CA = Path("/run/va/ca.pem")`;
  - `read_credential(path) -> str`, which raises
    `EgressUnproven("credential-invalid")`;
  - `send_message(control, message: dict, fds=()) -> None`, which never blocks and
    drops a reply it cannot send;
  - `receive_message(control) -> tuple[dict | None, list[int]]`, where `None` means
    EOF;
  - `control_loop(server, control, wake: int, lease: float, *, clock=time.monotonic)
    -> str`, which returns `close`, `lease`, `eof` or `term`;
  - `main(argv: list[str]) -> int`.
- Produces, from `helper`:
  - `MODEL_PORT = 4780` and `MODEL_URL = "http://127.0.0.1:4780"`;
  - `HELPER_TIMEOUT = 10.0` and `HELPER` (the source text);
  - `make_listener(child_pid: int, pidfd: int, *, port: int = MODEL_PORT, source: str
    = HELPER) -> socket.socket`, which raises `EgressUnproven("listener-failed")`.
- The control protocol, one JSON object per `SOCK_SEQPACKET` message:
  - orchestrator to proxy: `{"op": "route", "route": <base64 of the route's bytes>,
    "lease": <seconds>}`, then `{"op": "listener"}` carrying one descriptor over
    `SCM_RIGHTS`, then `{"op": "renew"}` and `{"op": "close"}`;
  - proxy to orchestrator: `{"op": "ready"}`, `{"op": "listening"}`, `{"op": "error",
    "code": …, "message": …}` and `{"op": "closed", "cause": …, "last_seq": …}`.

- [ ] **Step 1: Write the failing tests**

`python/tests/test_egress_proxy.py`:

```python
import base64
import json
import os
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

import autonomy
from egress_fixtures import (  # noqa: F401  (tls is a fixture)
    CANARY, FakeUpstream, exchange, message, pi_route, raw_request, status_and_body, tls, to_toml, write_credential,
)
from autonomy.egress.errors import EgressUnproven
from autonomy.egress.proxy import control_loop, read_credential, receive_message, send_message
from autonomy.egress.route import parse_route
from autonomy.egress.server import Hooks, ProxyServer, Recorder
from autonomy.egress.upstream import tls_context


@pytest.mark.parametrize("data", [b"sk-key\n", b"sk-key"])
def test_a_credential_of_one_line(tmp_path, data):  # Review Focus 5
    path = tmp_path / "credential"
    path.write_bytes(data)
    assert read_credential(path) == "sk-key"


@pytest.mark.parametrize("data", [b"sk-key\r\n", b"a\nb\n", b"", b"\n", b"sk key\n", "sk-kéy\n".encode()])
def test_a_credential_that_is_not_one_visible_line(tmp_path, data):  # Review Focus 5
    path = tmp_path / "credential"
    path.write_bytes(data)
    with pytest.raises(EgressUnproven) as caught:
        read_credential(path)
    assert caught.value.code == "credential-invalid"


def fresh(tmp_path, tls, *, mode="json", hooks=Hooks()):
    upstream = FakeUpstream(tls, mode=mode)
    route = parse_route(to_toml(pi_route(credential=tmp_path / "c", upstream=upstream.origin, ca_file=tls.cert)).encode())
    records = tmp_path / "egress.jsonl"
    fd = os.open(records, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    server = ProxyServer(route, CANARY, Recorder(fd), context=tls_context(tls.cert), hooks=hooks)
    return server, upstream, records


def pair():
    return socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)


def run_loop(server, control, wake, lease):
    outcome = {}
    thread = threading.Thread(
        target=lambda: outcome.update(cause=control_loop(server, control, wake, lease), at=time.monotonic()),
        daemon=True,
    )
    thread.start()
    return thread, outcome


def test_the_loop_hands_the_listener_to_the_server_and_says_so(tmp_path, tls):
    server, upstream, _ = fresh(tmp_path, tls)
    ours, theirs = pair()
    wake_read, wake_write = os.pipe()
    thread, outcome = run_loop(server, theirs, wake_read, 30)
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    send_message(ours, {"op": "listener"}, [listener.fileno()])
    listener.close()
    reply, _ = receive_message(ours)
    assert reply == {"op": "listening"}
    assert status_and_body(exchange(port, raw_request(body=message())))[0] == 200
    send_message(ours, {"op": "close"})
    thread.join(5)
    assert outcome["cause"] == "close"
    server.close("close")


@pytest.mark.parametrize("cause", ["eof", "term", "lease"])
def test_each_close_cause(tmp_path, tls, cause):
    server, _, _ = fresh(tmp_path, tls)
    ours, theirs = pair()
    wake_read, wake_write = os.pipe()
    started = time.monotonic()
    thread, outcome = run_loop(server, theirs, wake_read, 1.0 if cause == "lease" else 30)
    if cause == "eof":
        ours.close()
    if cause == "term":
        os.write(wake_write, b"\0")
    thread.join(5)
    assert outcome["cause"] == cause
    if cause == "lease":
        assert 0.9 < outcome["at"] - started < 1.5


def test_renewal_extends_the_lease(tmp_path, tls):
    server, _, _ = fresh(tmp_path, tls)
    ours, theirs = pair()
    wake_read, _ = os.pipe()
    started = time.monotonic()
    thread, outcome = run_loop(server, theirs, wake_read, 1.0)
    for _ in range(4):
        time.sleep(0.5)
        send_message(ours, {"op": "renew"})
    thread.join(5)
    assert outcome["cause"] == "lease" and outcome["at"] - started > 2.5


class Holder:
    def __init__(self, stage, seq):
        self.stage, self.seq = stage, seq
        self.reached, self.release = threading.Event(), threading.Event()

    def __call__(self, stage, seq):
        if (stage, seq) == (self.stage, self.seq):
            self.reached.set()
            assert self.release.wait(20)


def test_the_lease_closes_a_stalled_upstream_without_its_progress(tmp_path, tls):  # E22
    holder = Holder("before-send", 2)
    server, upstream, records = fresh(tmp_path, tls, mode="stall", hooks=Hooks(hold=holder))
    ours, theirs = pair()
    wake_read, _ = os.pipe()
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    started = time.monotonic()
    thread, outcome = run_loop(server, theirs, wake_read, 3.0)  # nobody renews: the orchestrator is stopped
    send_message(ours, {"op": "listener"}, [listener.fileno()])
    listener.close()
    assert receive_message(ours)[0] == {"op": "listening"}
    big = json.dumps(message(system="x" * 6_000_000)).encode()
    first = threading.Thread(target=lambda: exchange(port, raw_request(body=big), timeout=30), daemon=True)
    first.start()
    second = {}
    second_client = threading.Thread(
        target=lambda: second.setdefault("raw", exchange(port, raw_request(body=message()))), daemon=True,
    )
    second_client.start()
    assert holder.reached.wait(10)
    thread.join(5)
    assert outcome["cause"] == "lease"
    closer = threading.Thread(target=server.close, args=("lease",))
    closer.start()
    while server.gate.is_open:
        time.sleep(0.01)
    closed_at = time.monotonic()
    assert closed_at - started < 3.0 + 1.0
    holder.release.set()
    closer.join(5)
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", port), timeout=2)
    second_client.join(5)
    status, body = status_and_body(second["raw"])
    assert status == 403 and json.loads(body)["error"]["code"] == "route-closed"
    lines = [json.loads(line) for line in records.read_text().splitlines()]
    stalled = next(line for line in lines if line.get("seq") == 1)
    assert stalled["ended"] == "route-closed"
    assert lines[-1]["closed"] == "lease"
    assert upstream.stalled_bytes() < len(big)


def test_without_its_own_deadline_a_proxy_forwards_past_the_lease(tmp_path, tls):
    # Negative (E22): a loop with no deadline keeps serving for a stopped orchestrator.
    server, _, _ = fresh(tmp_path, tls)
    ours, theirs = pair()
    wake_read, _ = os.pipe()
    thread, outcome = run_loop(server, theirs, wake_read, float("inf"))
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    send_message(ours, {"op": "listener"}, [listener.fileno()])
    listener.close()
    receive_message(ours)
    time.sleep(2.0)
    assert "cause" not in outcome
    assert status_and_body(exchange(port, raw_request(body=message())))[0] == 200
    ours.close()
    thread.join(5)
    server.close("eof")


def spawn_proxy(tmp_path: Path, tls, credential_text: str):
    """The proxy's `main` as a process, unsandboxed: its fixed paths patched to files here."""
    credential = tmp_path / "credential"
    credential.write_text(credential_text)
    os.chmod(credential, 0o600)
    upstream = FakeUpstream(tls)
    route_bytes = to_toml(pi_route(credential=credential, upstream=upstream.origin, ca_file=tls.cert)).encode()
    records = tmp_path / "egress.jsonl"
    records_fd = os.open(records, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    ours, theirs = pair()
    package_parent = str(Path(autonomy.__file__).resolve().parent.parent)
    code = (
        "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
        "import autonomy.egress.proxy as p; "
        f"p.IN_SANDBOX_CREDENTIAL = Path({str(credential)!r}); p.IN_SANDBOX_CA = Path({str(tls.cert)!r}); "
        "raise SystemExit(p.main(sys.argv[2:]))"
    )
    process = subprocess.Popen(
        ["/usr/bin/python3", "-I", "-c", code, package_parent, str(theirs.fileno()), str(records_fd)],
        pass_fds=(theirs.fileno(), records_fd), stdin=subprocess.DEVNULL, start_new_session=True,
    )
    theirs.close()
    os.close(records_fd)
    send_message(ours, {"op": "route", "route": base64.b64encode(route_bytes).decode(), "lease": 30})
    return process, ours, records


def test_the_process_serves_and_closes_on_sigterm(tmp_path, tls):
    process, ours, records = spawn_proxy(tmp_path, tls, "sk-canary-proc\n")
    assert receive_message(ours)[0] == {"op": "ready"}
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    send_message(ours, {"op": "listener"}, [listener.fileno()])
    listener.close()
    assert receive_message(ours)[0] == {"op": "listening"}
    assert status_and_body(exchange(port, raw_request(body=message())))[0] == 200
    process.send_signal(signal.SIGTERM)
    assert receive_message(ours)[0] == {"op": "closed", "cause": "term", "last_seq": 1}
    assert process.wait(10) == 0
    assert json.loads(records.read_text().splitlines()[-1])["closed"] == "term"


def test_the_process_closes_on_eof(tmp_path, tls):
    process, ours, records = spawn_proxy(tmp_path, tls, "sk-canary-proc\n")
    assert receive_message(ours)[0] == {"op": "ready"}
    ours.close()
    assert process.wait(10) == 0
    assert json.loads(records.read_text().splitlines()[-1])["closed"] == "eof"


def test_a_two_line_credential_is_reported_and_never_served(tmp_path, tls):
    process, ours, _ = spawn_proxy(tmp_path, tls, "sk-one\nsk-two\n")
    reply, _ = receive_message(ours)
    assert (reply["op"], reply["code"]) == ("error", "credential-invalid")
    assert process.wait(10) == 3
```

`python/tests/test_egress_helper.py`:

```python
import os
import signal
import socket
import subprocess
import textwrap
import time

import pytest

from autonomy.egress.errors import EgressUnproven
from autonomy.egress import helper
from autonomy.egress.helper import HELPER, MODEL_PORT, make_listener
from autonomy.sandbox.bwrap import launch
from autonomy.sandbox.spec import SandboxSpec

pytestmark = pytest.mark.bwrap

CLIENT = textwrap.dedent(f"""
    import socket
    with socket.create_connection(("127.0.0.1", {MODEL_PORT}), timeout=10) as s:
        s.sendall(b"ping")
        print(s.recv(16).decode(), flush=True)
""")


def test_the_listener_lives_in_the_actors_network_namespace(tmp_path):
    held = {}

    def hook(child_pid, pidfd):
        held["listener"] = make_listener(child_pid, pidfd)

    out_read, out_write = os.pipe()
    null = os.open(os.devnull, os.O_RDWR)
    sandbox = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/python3", "-I", "-c", CLIENT],
                     stdin=null, stdout=out_write, stderr=null, before_release=hook)
    os.close(out_write)
    try:
        listener = held["listener"]
        listener.settimeout(10)
        conn, _ = listener.accept()
        assert conn.recv(16) == b"ping"
        conn.sendall(b"pong")
        conn.close()
        assert sandbox.wait(timeout=30) == 0
        assert os.read(out_read, 64).strip() == b"pong"
    finally:
        sandbox.close()
        os.close(out_read)
        os.close(null)
    with pytest.raises(ConnectionRefusedError):  # the host's own loopback has nothing there
        socket.create_connection(("127.0.0.1", MODEL_PORT), timeout=2)


def hold_and_try(tmp_path, attempt):
    """Launch a sleeper whose release hook runs `attempt(child_pid, pidfd)`."""
    null = os.open(os.devnull, os.O_RDWR)
    try:
        with pytest.raises(EgressUnproven) as caught:
            launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/sleep", "30"],
                   stdin=null, stdout=null, stderr=null, before_release=attempt)
    finally:
        os.close(null)
    return caught.value


def test_joining_the_inits_own_user_namespace_is_refused(tmp_path):
    # Negative: bwrap nests a user namespace inside the one that owns the network, so
    # joining the init's own gets EPERM at the network join (decision 13, NS_GET_USERNS).
    wrong = HELPER.replace("fcntl.ioctl(net, NS_GET_USERNS)", 'os.open(f"/proc/{pid}/ns/user", os.O_RDONLY)')
    assert wrong != HELPER
    error = hold_and_try(tmp_path, lambda child, pidfd: make_listener(child, pidfd, source=wrong))
    assert error.code == "listener-failed" and "Operation not permitted" in error.message


def test_a_dead_init_is_refused(tmp_path):
    def kill_first(child, pidfd):
        signal.pidfd_send_signal(pidfd, signal.SIGKILL)
        time.sleep(0.5)  # its namespaces are released when it exits
        make_listener(child, pidfd)

    assert hold_and_try(tmp_path, kill_first).code == "listener-failed"


def test_the_helper_gets_stdin_from_dev_null(monkeypatch):  # E20, the helper's arm
    seen = {}

    def spy(argv, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(argv, 0)

    monkeypatch.setattr(helper.subprocess, "run", spy)
    with pytest.raises(EgressUnproven):
        make_listener(1, 0)
    assert seen["stdin"] is subprocess.DEVNULL
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-one tests/test_egress_proxy.py tests/test_egress_helper.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.egress.proxy'`.

- [ ] **Step 3: Implement**

`python/src/autonomy/egress/proxy.py`:

```python
"""The model proxy's process (envelope design decision 13). `autonomy.egress.session`
starts it in its own bwrap as
`/usr/bin/python3 -I -c BOOT <package parent> <control fd> <records fd>`.

Its main thread is the control thread. It waits on the control socket, the SIGTERM
wake-up pipe and the lease's deadline. On the first of these it returns a cause, and
`main` takes the close transition, which waits on nothing but the gate's lock."""

from __future__ import annotations

import base64
import json
import os
import re
import select
import signal
import socket
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from autonomy.egress.errors import EgressUnproven, RouteRefused
from autonomy.egress.route import parse_route
from autonomy.egress.server import ProxyServer, Recorder
from autonomy.egress.upstream import tls_context

BOOT = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "from autonomy.egress.proxy import main; raise SystemExit(main(sys.argv[2:]))"
)
IN_SANDBOX_CREDENTIAL = Path("/run/va/credential")
IN_SANDBOX_CA = Path("/run/va/ca.pem")
MAX_MESSAGE = 1 << 20
_VISIBLE = re.compile(r"[\x21-\x7e]+")


def read_credential(path: Path) -> str:
    """One line of visible ASCII. One trailing newline is allowed, as `echo key > file`
    writes it; anything else could corrupt the upstream request's headers."""
    data = path.read_bytes()
    text = data[:-1] if data.endswith(b"\n") else data
    try:
        value = text.decode("ascii")
    except UnicodeDecodeError:
        raise EgressUnproven("credential-invalid", "the credential is not ASCII") from None
    if not _VISIBLE.fullmatch(value):
        raise EgressUnproven("credential-invalid", "the credential must be one line of visible ASCII")
    return value


def send_message(control: socket.socket, message: dict, fds: Iterable[int] = ()) -> None:
    """Never blocks: a reply the peer cannot take is dropped, and the peer's own wait
    bounds what it costs."""
    data = json.dumps(message).encode()
    fds = list(fds)
    try:
        if fds:
            socket.send_fds(control, [data], fds, socket.MSG_DONTWAIT)
        else:
            control.send(data, socket.MSG_DONTWAIT)
    except OSError:
        pass


def receive_message(control: socket.socket) -> tuple[dict | None, list[int]]:
    data, fds, _, _ = socket.recv_fds(control, MAX_MESSAGE, 1)
    if not data:
        for fd in fds:
            os.close(fd)
        return None, []
    return json.loads(data), fds


def control_loop(
    server: ProxyServer, control: socket.socket, wake: int, lease: float, *, clock: Callable[[], float] = time.monotonic,
) -> str:
    """Serve the control socket until a close cause: `close`, `lease`, `eof` or `term`.
    The lease is the proxy's own deadline, renewed only by `renew` (spec §8)."""
    deadline = clock() + lease
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            return "lease"
        ready, _, _ = select.select([control, wake], [], [], min(remaining, 3600.0))
        if wake in ready:
            return "term"
        if control not in ready:
            continue
        message, fds = receive_message(control)
        if message is None:
            return "eof"
        op = message.get("op")
        if op == "listener" and len(fds) == 1:
            server.serve(socket.socket(fileno=fds[0]))
            send_message(control, {"op": "listening"})
        elif op == "renew":
            deadline = clock() + lease
        elif op == "close":
            return "close"
        else:
            for fd in fds:
                os.close(fd)


def main(argv: list[str]) -> int:
    wake_read, wake_write = os.pipe()
    os.set_blocking(wake_write, False)
    signal.set_wakeup_fd(wake_write)
    signal.signal(signal.SIGTERM, lambda signum, frame: None)
    control = socket.socket(fileno=int(argv[0]))
    records = int(argv[1])
    message, _ = receive_message(control)
    if message is None or message.get("op") != "route":
        return 2
    try:
        route = parse_route(base64.b64decode(message["route"]))
        credential = read_credential(IN_SANDBOX_CREDENTIAL)
    except (RouteRefused, EgressUnproven) as caught:
        send_message(control, {"op": "error", "code": caught.code, "message": caught.message})
        return 3
    except OSError as caught:
        send_message(control, {"op": "error", "code": "credential-unreadable", "message": str(caught)})
        return 3
    try:
        context = tls_context(IN_SANDBOX_CA if route.ca_file is not None else None)
    except OSError as caught:
        send_message(control, {"op": "error", "code": "ca-unreadable", "message": str(caught)})
        return 3
    server = ProxyServer(route, credential, Recorder(records), context=context)
    send_message(control, {"op": "ready"})
    cause = control_loop(server, control, wake_read, float(message["lease"]))
    server.close(cause)
    send_message(control, {"op": "closed", "cause": cause, "last_seq": server.gate.last_seq})
    return 0
```

`python/src/autonomy/egress/helper.py`:

```python
"""The namespace helper (envelope design decision 13). Before the gate's release it
puts the proxy's listener on 127.0.0.1:4780 inside the actor's own network namespace,
where a loopback address is private to the actor. No process runs inside the sandbox
for it.

The helper is a separate, single-threaded `/usr/bin/python3 -I`, because joining a
user namespace needs a single-threaded process. It opens the actor's network namespace
through the init's pid and checks the init's pidfd is still alive after the open, so a
reused pid is never joined. bwrap nests a second user namespace inside the one that
owns the network namespace, so the helper joins the owner (`NS_GET_USERNS`), not the
init's own: that one gives `EPERM`. Then it joins the network namespace, binds, listens
and passes the socket back over `SCM_RIGHTS`."""

from __future__ import annotations

import socket
import subprocess

from autonomy.egress.errors import EgressUnproven

MODEL_PORT = 4780
MODEL_URL = f"http://127.0.0.1:{MODEL_PORT}"
HELPER_TIMEOUT = 10.0

HELPER = r"""
import fcntl, os, signal, socket, sys
NS_GET_USERNS = 0xB701
pid, pidfd, back, port = (int(arg) for arg in sys.argv[1:5])
if not hasattr(os, "setns"):
    sys.stderr.write("this python lacks os.setns (Python 3.12 or later is needed)\n")
    sys.exit(3)
net = os.open(f"/proc/{pid}/ns/net", os.O_RDONLY | os.O_CLOEXEC)
signal.pidfd_send_signal(pidfd, 0)
owner = fcntl.ioctl(net, NS_GET_USERNS)
os.setns(owner, os.CLONE_NEWUSER)
os.setns(net, os.CLONE_NEWNET)
listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.bind(("127.0.0.1", port))
listener.listen(64)
socket.send_fds(socket.socket(fileno=back), [b"L"], [listener.fileno()])
"""


def make_listener(child_pid: int, pidfd: int, *, port: int = MODEL_PORT, source: str = HELPER) -> socket.socket:
    here, back = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        try:
            result = subprocess.run(
                ["/usr/bin/python3", "-I", "-c", source, str(child_pid), str(pidfd), str(back.fileno()), str(port)],
                pass_fds=(pidfd, back.fileno()), stdin=subprocess.DEVNULL, capture_output=True,
                timeout=HELPER_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            raise EgressUnproven("listener-failed", f"the namespace helper did not finish in {HELPER_TIMEOUT:g} s") from None
        finally:
            back.close()
        if result.returncode != 0:
            lines = result.stderr.decode("utf-8", "replace").strip().splitlines()
            raise EgressUnproven("listener-failed", lines[-1] if lines else f"the helper exited {result.returncode}")
        here.settimeout(1.0)
        _, fds, _, _ = socket.recv_fds(here, 1, 1)
        if len(fds) != 1:
            raise EgressUnproven("listener-failed", "the helper passed back no listener")
        return socket.socket(fileno=fds[0])
    finally:
        here.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `just test-one tests/test_egress_proxy.py tests/test_egress_helper.py`
Expected: PASS.

- [ ] **Step 5: Run the fast suite, then commit**

Run: `just test-fast`. Expected: PASS.

```bash
git add python/src/autonomy/egress/proxy.py python/src/autonomy/egress/helper.py python/tests/test_egress_proxy.py python/tests/test_egress_helper.py
git commit -m "feat(egress): the proxy process with its lease, and the namespace helper"
```

---
### Task 9: The orchestrator's session, and E21 and E22 under real bwrap

**Files:**
- Create: `python/src/autonomy/egress/session.py`
- Modify: `python/src/autonomy/closing.py`
- Test: `python/tests/test_egress_session.py`, `python/tests/test_closing.py`

**Interfaces:**
- Consumes:
  - Tasks 1–8: `read_info`, `SYSTEM_SYMLINKS`, `check_sources`, `SandboxUnproven`,
    `launch`, `prove`, `SandboxSpec`, `LoadedRoute`, `Route`, `load_route`,
    `egress_denied`, `EgressUnproven`, `BOOT`, `IN_SANDBOX_CREDENTIAL`,
    `IN_SANDBOX_CA`, `send_message`, `receive_message`, `make_listener` and
    `MODEL_URL`;
  - from `autonomy.baseline`: `append_event` and `EVENTS`;
  - from `autonomy.membership`: `Finding`.
- Produces:
  - `PROXY_START_TIMEOUT = 10.0`, `LISTENING_TIMEOUT = 5.0` and
    `CLOSE_TIMEOUT = 5.0`;
  - `ProxyBinds(ro: tuple[tuple[Path, str], ...], exempt: tuple[Path, ...])`;
  - `proxy_binds(route, *, resolv=Path("/etc/resolv.conf")) -> ProxyBinds`;
  - `check_proxy(binds, denied) -> None`, which raises
    `EgressUnproven("proxy-bind-refused")`;
  - `proxy_argv(binds, *, control_fd, records_fd, info_fd) -> list[str]`;
  - `EgressSession.start(loaded, run_dir, *, lease, denied) -> EgressSession`;
  - `EgressSession`'s members `attach(child_pid, pidfd, *, make=make_listener)`
    (the `before_release` hook), `renew()`, `close(timeout=CLOSE_TIMEOUT) ->
    EgressClosed`, `kill()`, `exited() -> bool`, `pidfd`, `init_pid` and `process`;
  - `EgressClosed(cause: str | None, last_seq: int | None, timed_out: bool)`, with
    `.findings() -> tuple[Finding, ...]`;
  - `closing_line(path) -> dict | None`;
  - `kill_orphan(run_dir, timeout=CLOSE_TIMEOUT) -> EgressClosed | None`;
  - `unproven(error: EgressUnproven) -> Finding`, the `egress-unproven` finding;
  - `closing.SEVERITY` gains `egress-unproven: unwired`, `egress-lost: None` and
    `egress-close-timeout: None`.

- [ ] **Step 1: Write the failing tests**

In `python/tests/test_closing.py`, add the three codes wherever the test lists every
code in `SEVERITY`, and add:

```python
def test_egress_findings_are_reported_and_unproven_is_unwired():
    from autonomy.closing import SEVERITY

    assert SEVERITY["egress-unproven"] == "unwired"
    assert SEVERITY["egress-lost"] is None and SEVERITY["egress-close-timeout"] is None
```

`python/tests/test_egress_session.py`:

```python
import json
import os
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

import autonomy
from egress_fixtures import (  # noqa: F401  (tls is a fixture)
    CANARY, MODEL, FakeUpstream, Tls, message, pi_route, raw_request, tls, write_credential, write_route,
)
from autonomy.egress import session as session_module
from autonomy.egress.errors import EgressUnproven
from autonomy.egress.helper import MODEL_URL
from autonomy.egress.route import egress_denied, load_route
from autonomy.egress.session import (
    EgressSession, check_proxy, closing_line, kill_orphan, proxy_argv, proxy_binds,
)
from autonomy.sandbox.bwrap import build_argv, launch, prove
from autonomy.sandbox.spec import SandboxSpec

pytestmark = pytest.mark.bwrap


@dataclass
class World:
    config: Path
    credential: Path
    run_dir: Path
    scratch: Path
    upstream: FakeUpstream
    other: FakeUpstream
    canary: str

    def loaded(self):
        return load_route(self.config, "anthropic")

    def denied(self, loaded):
        return egress_denied(self.config, loaded)

    def start(self, *, lease: float = 30.0) -> EgressSession:
        loaded = self.loaded()
        return EgressSession.start(loaded, self.run_dir, lease=lease, denied=self.denied(loaded))

    def records(self) -> list[dict]:
        path = self.run_dir / "egress.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def events(self) -> list[str]:
        path = self.run_dir / "events.jsonl"
        return [json.loads(line)["event"] for line in path.read_text().splitlines()] if path.exists() else []


def make_world(root: Path, tls: Tls, *, canary: str = CANARY, mode: str = "sse", credential_text: str | None = None) -> World:
    config = root / "config"
    credential = write_credential(config / "credentials" / "anthropic", canary)
    if credential_text is not None:
        credential.write_text(credential_text)
    upstream, other = FakeUpstream(tls, mode=mode), FakeUpstream(tls)
    write_route(config, "anthropic", pi_route(credential=credential, upstream=upstream.origin, ca_file=tls.cert))
    run_dir, scratch = root / "run", root / "scratch"
    run_dir.mkdir()
    scratch.mkdir()
    return World(config, credential, run_dir, scratch, upstream, other, canary)


@pytest.fixture
def world(tmp_path, tls):
    return make_world(tmp_path, tls)


ACTOR = textwrap.dedent(r'''
    import errno, json, os, socket, sys, time
    port = int(os.environ["VERIFIABLY_MODEL_URL"].rsplit(":", 1)[1])
    task = json.loads(sys.argv[1])
    scratch = os.environ["SCRATCH"]
    report = {}
    received = []

    def ask(data, *, until_eof=True, mark=None):
        with socket.create_connection(("127.0.0.1", port), timeout=20) as s:
            s.sendall(data.encode("latin-1") if isinstance(data, str) else data)
            got, first = b"", None
            while True:
                try:
                    chunk = s.recv(65536)
                except OSError:
                    break
                if not chunk:
                    break
                got += chunk
                if first is None and b"event: message" in got:
                    first = time.monotonic()
                    if mark:
                        open(os.path.join(scratch, mark), "w").close()
        received.append(got)
        return got, first

    def attempt(family, address):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(3)
                s.connect(address)
            return "CONNECTED"
        except OSError as caught:
            return errno.errorcode.get(caught.errno) if caught.errno else type(caught).__name__

    def wait_for(name, seconds=30):
        deadline = time.monotonic() + seconds
        while not os.path.exists(os.path.join(scratch, name)) and time.monotonic() < deadline:
            time.sleep(0.05)

    for step in task:
        kind = step["kind"]
        if kind == "ask":
            got, first = ask(step["data"], mark=step.get("mark"))
            report[step["name"]] = {"first": first, "events": got.count(b"event: message"),
                                    "status": got.split(b" ", 2)[1].decode() if got.startswith(b"HTTP/1.1") else None,
                                    "body": got.partition(b"\r\n\r\n")[2].decode("utf-8", "replace")[:400]}
        elif kind == "connect":
            report[step["name"]] = attempt(socket.AF_INET6 if ":" in step["host"] else socket.AF_INET,
                                           (step["host"], step["port"]))
        elif kind == "resolve":
            try:
                socket.getaddrinfo(step["host"], 443)
                report[step["name"]] = "RESOLVED"
            except socket.gaierror as caught:
                report[step["name"]] = "gaierror"
        elif kind == "abstract":
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                try:
                    s.connect("\0" + step["name_"])
                    report[step["name"]] = "CONNECTED"
                except OSError as caught:
                    report[step["name"]] = errno.errorcode.get(caught.errno)
        elif kind == "wait":
            wait_for(step["file"])
        elif kind == "timed-connect":
            started = time.monotonic()
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=3) as s:
                    s.sendall(b"POST /v1/messages?beta=true HTTP/1.1\r\ncontent-length: 0\r\n\r\n")
                    s.settimeout(2)
                    outcome = "ANSWERED" if s.recv(16) else "EOF"
            except OSError as caught:
                outcome = errno.errorcode.get(caught.errno) if caught.errno else type(caught).__name__
            report[step["name"]] = {"outcome": outcome, "seconds": time.monotonic() - started}
        elif kind == "sweep":
            needle = step["needle"].encode()
            found = []
            for top, dirs, files in os.walk("/"):
                if top in ("/proc", "/sys", "/dev", "/usr"):
                    dirs[:] = []
                    continue
                for name in files:
                    path = os.path.join(top, name)
                    try:
                        with open(path, "rb") as f:
                            if needle in f.read(4 << 20):
                                found.append(path)
                    except OSError:
                        pass
            for pid in os.listdir("/proc"):
                if pid.isdigit():
                    for part in ("environ", "cmdline"):
                        try:
                            if needle in open(f"/proc/{pid}/{part}", "rb").read():
                                found.append(f"/proc/{pid}/{part}")
                        except OSError:
                            pass
            if any(needle in value.encode() for value in os.environ.values()):
                found.append("environ")
            if any(needle in got for got in received):
                found.append("proxy-replies")
            report[step["name"]] = found
    print(json.dumps(report), flush=True)
''')


def run_actor(world: World, session: EgressSession, task: list[dict], *, make=None) -> tuple[dict, int]:
    spec = SandboxSpec(scratch=world.scratch, env={"VERIFIABLY_MODEL_URL": MODEL_URL, "SCRATCH": str(world.scratch)})
    out = world.scratch.parent / "actor.out"
    with open(out, "wb") as stdout, open(os.devnull, "rb") as null:
        hook = session.attach if make is None else (lambda c, p: session.attach(c, p, make=make))
        actor = launch(spec, ["/usr/bin/python3", "-I", "-c", ACTOR, json.dumps(task)],
                       stdin=null.fileno(), stdout=stdout.fileno(), stderr=stdout.fileno(), before_release=hook)
        try:
            actor.wait(timeout=120)
        finally:
            actor.close()
    lines = out.read_bytes().decode().strip().splitlines()
    return json.loads(lines[-1]), actor.child_pid


def ask(name: str, body: dict | bytes | None = None, **kw) -> dict:
    data = raw_request(body=message() if body is None else body, **kw).decode("latin-1")
    return {"kind": "ask", "name": name, "data": data}


def proxy_pid(session: EgressSession) -> int:
    children = Path(f"/proc/{session.init_pid}/task/{session.init_pid}/children").read_text().split()
    return int(children[0])


# -- the proxy's sandbox ---------------------------------------------------------------

def test_the_proxys_argv(world):
    route = world.loaded().route
    binds = proxy_binds(route)
    argv = proxy_argv(binds, control_fd=5, records_fd=6, info_fd=7)
    assert argv[:6] == ["bwrap", "--unshare-all", "--share-net", "--new-session", "--clearenv", "--proc"]
    assert "--die-with-parent" not in argv
    at = argv.index(str(world.credential))
    assert argv[at - 1 : at + 2] == ["--ro-bind", str(world.credential), "/run/va/credential"]
    assert argv[argv.index("--info-fd") + 1] == "7"


def test_a_resolver_outside_etc_is_bound(world, tmp_path):
    stub = tmp_path / "stub-resolv.conf"
    stub.write_text("nameserver 127.0.0.53\n")
    link = tmp_path / "resolv.conf"
    link.symlink_to(stub)
    binds = proxy_binds(world.loaded().route, resolv=link)
    assert (stub, str(stub)) in binds.ro


def test_the_proxys_binds_are_checked_with_only_its_files_exempt(world):
    loaded = world.loaded()
    check_proxy(proxy_binds(loaded.route), world.denied(loaded))  # the credential sits under denied <config>
    package = Path(autonomy.__file__).resolve().parent
    with pytest.raises(EgressUnproven) as caught:
        check_proxy(proxy_binds(loaded.route), [*world.denied(loaded), package.parent])
    assert caught.value.code == "proxy-bind-refused"


def test_the_proxy_gets_stdin_from_dev_null(world, monkeypatch):  # E20, the proxy's arm
    seen = {}

    def spy(argv, **kwargs):
        seen.update(kwargs)
        raise OSError("stop here")

    monkeypatch.setattr(session_module.subprocess, "Popen", spy)
    with pytest.raises(EgressUnproven):
        world.start()
    assert seen["stdin"] is subprocess.DEVNULL and seen["start_new_session"] is True


# -- E21 -----------------------------------------------------------------------------

def test_e21_the_model_route_is_the_actors_only_way_out(world):
    abstract = f"va-test-{os.getpid()}"
    host_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    host_listener.bind("\0" + abstract)
    host_listener.listen(1)
    world.upstream.events, world.upstream.gap = 5, 0.3
    loaded = world.loaded()
    spec = SandboxSpec(scratch=world.scratch, env={"VERIFIABLY_MODEL_URL": MODEL_URL, "SCRATCH": str(world.scratch)})
    prove(spec, world.denied(loaded))
    session = world.start()
    proxy_cmdline = Path(f"/proc/{session.process.pid}/cmdline").read_bytes()
    task = [
        ask("stream", headers=[("x-api-key", "placeholder")]),
        ask("connect-tunnel", method="CONNECT", target="api.anthropic.com:443", body=b""),
        ask("url-source", body=message(messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "url", "url": world.other.origin + "/x.png"}}]}])),
        {"kind": "connect", "name": "upstream-direct", "host": "127.0.0.1", "port": world.upstream.port},
        {"kind": "connect", "name": "doc-v4", "host": "192.0.2.1", "port": 443},
        {"kind": "connect", "name": "loopback-v6", "host": "::1", "port": 443},
        {"kind": "resolve", "name": "dns", "host": "api.anthropic.com"},
        {"kind": "abstract", "name": "abstract", "name_": abstract},
        {"kind": "sweep", "name": "sweep", "needle": world.canary},
    ]
    report, _ = run_actor(world, session, task)
    closed = session.close()
    host_listener.close()
    assert report["stream"]["status"] == "200" and report["stream"]["events"] == 5
    assert report["stream"]["first"] < world.upstream.last_event_at
    assert json.loads(report["connect-tunnel"]["body"])["error"]["code"] == "target-refused"
    assert json.loads(report["url-source"]["body"])["error"]["code"] == "body-refused"
    assert all(report[name] != "CONNECTED" for name in ("upstream-direct", "doc-v4", "loopback-v6"))
    assert report["doc-v4"] == "ENETUNREACH"
    assert report["dns"] == "gaierror"
    assert report["abstract"] == "ECONNREFUSED"
    assert report["sweep"] == []
    (seen,) = world.upstream.seen
    assert seen.headers["x-api-key"] == [world.canary]
    assert world.other.connections == 0
    needle = world.canary.encode()
    assert needle not in proxy_cmdline
    assert world.canary not in " ".join(build_argv(spec, ["/usr/bin/python3"], info_fd=None))
    for root in (world.run_dir, world.scratch):
        for path in root.rglob("*"):
            if path.is_file():
                assert needle not in path.read_bytes(), path
    assert (closed.cause, closed.timed_out, closed.findings()) == ("close", False, ())


def test_e21_runs_are_isolated(tmp_path, tls):
    worlds = [make_world(tmp_path / name, tls, canary=f"sk-canary-{name}", mode="json") for name in ("a", "b")]
    sessions = [w.start() for w in worlds]
    for w, s in zip(worlds, sessions):
        report, _ = run_actor(w, s, [ask("one")])
        assert report["one"]["status"] == "200"
    for w, s in zip(worlds, sessions):
        s.close()
        assert [line["seq"] for line in w.records() if "seq" in line] == [1]
        (seen,) = w.upstream.seen
        assert seen.headers["x-api-key"] == [w.canary]


def test_e21_the_route_enforced_is_the_one_loaded(world):
    loaded = world.loaded()
    doc = pi_route(credential=world.credential, upstream=world.upstream.origin, ca_file=loaded.route.ca_file)
    doc["operations"][0]["models"] = ["claude-opus-5-5"]
    write_route(world.config, "anthropic", doc)  # edited after step 2
    session = EgressSession.start(loaded, world.run_dir, lease=30, denied=world.denied(loaded))
    report, _ = run_actor(world, session, [ask("haiku")])
    session.close()
    assert report["haiku"]["status"] == "200"  # the loaded bytes, not the edit
    assert load_route(world.config, "anthropic").digest != loaded.digest


# -- E22 -----------------------------------------------------------------------------

def test_e22_stop_cuts_the_stream_and_the_next_connect_is_refused(world):
    world.upstream.events, world.upstream.gap = 30, 0.3
    session = world.start()
    marker = world.scratch / "streaming"
    task = [
        {**ask("stream"), "mark": "streaming"},
        {"kind": "wait", "file": "go"},
        {"kind": "timed-connect", "name": "after"},
    ]
    outcome = {}
    actor = threading.Thread(target=lambda: outcome.update(report=run_actor(world, session, task)[0]))
    actor.start()
    deadline = time.monotonic() + 30
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    closed = session.close()
    (world.scratch / "go").touch()
    actor.join(60)
    report = outcome["report"]
    assert report["stream"]["events"] < 30
    assert report["after"]["outcome"] == "ECONNREFUSED"
    stream = next(line for line in world.records() if line.get("seq") == 1)
    assert stream["ended"] == "route-closed"
    assert closed.cause == "close" and world.records()[-1]["last_seq"] >= 1
    assert "egress-closed" in world.events()


ORCHESTRATOR = textwrap.dedent("""
    import json, sys, time
    sys.path.insert(0, sys.argv[1])
    from pathlib import Path
    from autonomy.egress.route import egress_denied, load_route
    from autonomy.egress.session import EgressSession
    config, run_dir, lease = Path(sys.argv[2]), Path(sys.argv[3]), float(sys.argv[4])
    loaded = load_route(config, "anthropic")
    session = EgressSession.start(loaded, run_dir, lease=lease, denied=egress_denied(config, loaded))
    print(json.dumps({"init": session.init_pid}), flush=True)
    while True:
        time.sleep(lease / 3)
        session.renew()
""")


def orchestrator(world: World, lease: float) -> tuple[subprocess.Popen, int]:
    package_parent = str(Path(autonomy.__file__).resolve().parent.parent)
    process = subprocess.Popen(
        [sys.executable, "-c", ORCHESTRATOR, package_parent, str(world.config), str(world.run_dir), str(lease)],
        stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
    )
    init = json.loads(process.stdout.readline())["init"]
    return process, init


def wait_closed(world: World, seconds: float) -> dict | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        line = closing_line(world.run_dir / "egress.jsonl")
        if line is not None:
            return line
        time.sleep(0.05)
    return None


def test_e22_a_stopped_orchestrator_loses_the_route_at_the_lease(world):
    process, _ = orchestrator(world, lease=3.0)
    try:
        time.sleep(1.5)  # renewing
        assert closing_line(world.run_dir / "egress.jsonl") is None
        process.send_signal(signal.SIGSTOP)
        line = wait_closed(world, 6.0)
        assert line is not None and line["closed"] == "lease"
    finally:
        process.send_signal(signal.SIGCONT)
        process.kill()
        process.wait()


def test_e22_a_dead_orchestrator_closes_the_route_by_eof(world):
    process, init = orchestrator(world, lease=30.0)
    process.kill()
    process.wait()
    line = wait_closed(world, 5.0)
    assert line is not None and line["closed"] == "eof"
    closed = kill_orphan(world.run_dir)
    assert (closed.cause, closed.timed_out) == ("eof", False)
    assert not Path(f"/proc/{init}").exists()


def test_e22_run_close_kills_a_wedged_orphan_proxy(world):
    process, init = orchestrator(world, lease=30.0)
    children = Path(f"/proc/{init}/task/{init}/children").read_text().split()
    os.kill(int(children[0]), signal.SIGSTOP)
    process.kill()
    process.wait()
    started = time.monotonic()
    closed = kill_orphan(world.run_dir)
    assert 4.5 < time.monotonic() - started < 8
    assert closed.timed_out and [f.code for f in closed.findings()] == ["egress-close-timeout"]
    time.sleep(0.5)
    assert not Path(f"/proc/{init}").exists()


def test_e22_sigterm_to_the_proxy_closes_it(world):
    session = world.start()
    os.kill(proxy_pid(session), signal.SIGTERM)
    line = wait_closed(world, 5.0)
    assert line is not None and line["closed"] == "term"
    assert session.close().cause == "term"


def test_e22_a_dead_proxy_leaves_nothing_listening(world):
    session = world.start()
    task = [{"kind": "wait", "file": "go"}, {"kind": "timed-connect", "name": "after"}]
    outcome = {}
    actor = threading.Thread(target=lambda: outcome.update(report=run_actor(world, session, task)[0]))
    actor.start()
    time.sleep(1.0)
    signal.pidfd_send_signal(session.pidfd, signal.SIGKILL)
    time.sleep(0.5)
    (world.scratch / "go").touch()
    actor.join(60)
    after = outcome["report"]["after"]
    assert after["outcome"] == "ECONNREFUSED" and after["seconds"] < 1
    closed = session.close()
    assert [f.code for f in closed.findings()] == ["egress-lost"]


def test_e22_a_listener_copy_kept_by_the_orchestrator_would_leave_the_actor_hanging(world):
    # Negative (E22): a copy outlives the proxy, so the kernel queues the connect in
    # the backlog and nobody answers, instead of refusing it.
    session = world.start()
    kept = []

    def keeping(child, pidfd):
        listener = session_module.make_listener(child, pidfd)
        kept.append(listener.dup())
        return listener

    task = [{"kind": "wait", "file": "go"}, {"kind": "timed-connect", "name": "after"}]
    outcome = {}
    actor = threading.Thread(target=lambda: outcome.update(report=run_actor(world, session, task, make=keeping)[0]))
    actor.start()
    time.sleep(1.0)
    signal.pidfd_send_signal(session.pidfd, signal.SIGKILL)
    time.sleep(0.5)
    (world.scratch / "go").touch()
    actor.join(60)
    assert outcome["report"]["after"]["outcome"] in ("TimeoutError", "timeout")
    kept[0].close()
    session.close()


def test_e22_a_proxy_that_ignores_close_is_killed_after_5_s(world):
    session = world.start()
    os.kill(proxy_pid(session), signal.SIGSTOP)
    started = time.monotonic()
    closed = session.close()
    assert 4.5 < time.monotonic() - started < 8
    assert closed.timed_out and [f.code for f in closed.findings()] == ["egress-close-timeout"]
    assert "egress-close-timeout" in world.events()


def test_e22_a_credential_removed_before_the_start_is_unproven(world):
    loaded = world.loaded()
    world.credential.unlink()
    with pytest.raises(EgressUnproven) as caught:
        EgressSession.start(loaded, world.run_dir, lease=30, denied=world.denied(loaded))
    assert caught.value.code == "proxy-bind-refused"  # its bind source is gone: the static check stops it


def test_e22_a_two_line_credential_is_unproven(tmp_path, tls):
    world = make_world(tmp_path, tls, credential_text="sk-one\nsk-two\n")
    with pytest.raises(EgressUnproven) as caught:
        world.start()
    assert caught.value.code == "proxy-unready" and "credential-invalid" in caught.value.message


def test_e22_a_failed_helper_never_releases_the_actor(world):
    session = world.start()

    def refused(child, pidfd):
        raise EgressUnproven("listener-failed", "setns: Operation not permitted")

    with pytest.raises(EgressUnproven):
        run_actor(world, session, [{"kind": "sweep", "name": "ran", "needle": "x"}], make=refused)
    assert not (world.scratch.parent / "actor.out").read_bytes()
    session.kill()


def test_e22_a_proxy_that_never_listens_is_unproven(world):
    session = world.start()
    os.kill(proxy_pid(session), signal.SIGSTOP)
    started = time.monotonic()
    with pytest.raises(EgressUnproven) as caught:
        run_actor(world, session, [{"kind": "sweep", "name": "ran", "needle": "x"}])
    assert caught.value.code == "proxy-unlistening" and 4.5 < time.monotonic() - started < 8
    assert not (world.scratch.parent / "actor.out").read_bytes()
    session.kill()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-one tests/test_egress_session.py tests/test_closing.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.egress.session'`
and a `KeyError` for `egress-unproven`.

- [ ] **Step 3: Implement**

In `python/src/autonomy/closing.py`, add to `SEVERITY`, after `"orchestrator-lost"`:

```python
        "egress-unproven": "unwired",
        "egress-lost": None,
        "egress-close-timeout": None,
```

`python/src/autonomy/egress/session.py`:

```python
"""The orchestrator's side of the model proxy (envelope design decision 13): the
proxy's own sandbox, its start, the listener's hand-off before the gate's release,
renewal, and the close. B2 calls `check_proxy` and `start` at §3 step 7, passes
`attach` to `launch` at step 9, sends `close` with the seal at close step 0, and calls
`kill_orphan` from `run close`."""

from __future__ import annotations

import base64
import json
import os
import select
import signal
import socket
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import autonomy
from autonomy.baseline import EVENTS, append_event
from autonomy.egress.errors import EgressUnproven
from autonomy.egress.helper import make_listener
from autonomy.egress.proxy import BOOT, IN_SANDBOX_CA, IN_SANDBOX_CREDENTIAL, receive_message, send_message
from autonomy.egress.route import LoadedRoute, Route
from autonomy.membership import Finding
from autonomy.sandbox.bwrap import read_info
from autonomy.sandbox.spec import SYSTEM_SYMLINKS
from autonomy.sandbox.static import SandboxUnproven, check_sources

PROXY_START_TIMEOUT = 10.0
LISTENING_TIMEOUT = 5.0
CLOSE_TIMEOUT = 5.0
EGRESS_RECORDS = "egress.jsonl"
PROXY_LOG = "proxy.log"


@dataclass(frozen=True)
class ProxyBinds:
    ro: tuple[tuple[Path, str], ...]
    exempt: tuple[Path, ...]


def _package() -> Path:
    return Path(autonomy.__file__).resolve().parent


def proxy_binds(route: Route, *, resolv: Path = Path("/etc/resolv.conf")) -> ProxyBinds:
    """`/usr`, `/etc`, the package, the credential and the `ca_file`, and the resolver
    configuration's real path when it lies outside `/etc` (systemd-resolved's stub)."""
    package = _package()
    ro: list[tuple[Path, str]] = [(Path("/usr"), "/usr"), (Path("/etc"), "/etc"), (package, str(package))]
    real = resolv.resolve()
    if real.exists() and not real.is_relative_to("/etc"):
        ro.append((real, str(real)))
    ro.append((route.credential_file, str(IN_SANDBOX_CREDENTIAL)))
    exempt = [route.credential_file]
    if route.ca_file is not None:
        ro.append((route.ca_file, str(IN_SANDBOX_CA)))
        exempt.append(route.ca_file)
    return ProxyBinds(tuple(ro), tuple(exempt))


def check_proxy(binds: ProxyBinds, denied: Iterable[Path]) -> None:
    """§3 step 7, the proxy's half: the denied set, with only its own files exempt."""
    try:
        check_sources([source for source, _ in binds.ro], denied, exempt=binds.exempt)
    except SandboxUnproven as caught:
        raise EgressUnproven("proxy-bind-refused", str(caught)) from None


def proxy_argv(binds: ProxyBinds, *, control_fd: int, records_fd: int, info_fd: int) -> list[str]:
    """No `--die-with-parent`, deliberately: a proxy that died with the orchestrator
    would write no closing line. It sees EOF on its control socket and closes."""
    args = ["bwrap", "--unshare-all", "--share-net", "--new-session", "--clearenv",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/run/va"]
    for source, destination in binds.ro:
        args += ["--ro-bind", str(source), destination]
    for target, link in SYSTEM_SYMLINKS:
        args += ["--symlink", target, link]
    args += ["--setenv", "PATH", "/usr/bin", "--info-fd", str(info_fd), "--",
             "/usr/bin/python3", "-I", "-c", BOOT, str(_package().parent), str(control_fd), str(records_fd)]
    return args


def _start_time(pid: int) -> int:
    stat = Path(f"/proc/{pid}/stat").read_bytes()
    return int(stat.rsplit(b")", 1)[1].split()[19])


def closing_line(path: Path) -> dict | None:
    """The proxy's closing line, when `egress.jsonl` ends with one."""
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return None
    if not lines:
        return None
    try:
        last = json.loads(lines[-1])
    except ValueError:
        return None
    return last if "closed" in last else None


@dataclass(frozen=True)
class EgressClosed:
    cause: str | None
    last_seq: int | None
    timed_out: bool

    def findings(self) -> tuple[Finding, ...]:
        if self.timed_out:
            return (Finding("egress-close-timeout", "proxy", "the proxy did not exit within 5 s and was killed"),)
        if self.cause is None:
            return (Finding("egress-lost", "proxy", "the proxy exited without its closing line"),)
        return ()


def unproven(error: EgressUnproven) -> Finding:
    return Finding("egress-unproven", error.code, error.message)


def _settle(run_dir: Path, timed_out: bool) -> EgressClosed:
    line = closing_line(run_dir / EGRESS_RECORDS)
    result = EgressClosed(None if line is None else line["closed"], None if line is None else line["last_seq"], timed_out)
    if timed_out:
        append_event(run_dir, "egress-close-timeout")
    elif line is None:
        append_event(run_dir, "egress-lost")
    else:
        append_event(run_dir, "egress-closed", cause=result.cause, last_seq=result.last_seq)
    return result


class EgressSession:
    def __init__(self, process: subprocess.Popen, init_pid: int, pidfd: int, control: socket.socket, run_dir: Path) -> None:
        self.process = process
        self.init_pid = init_pid
        self.pidfd = pidfd
        self.run_dir = run_dir
        self._control = control

    @classmethod
    def start(cls, loaded: LoadedRoute, run_dir: Path, *, lease: float, denied: Iterable[Path]) -> EgressSession:
        binds = proxy_binds(loaded.route)
        check_proxy(binds, denied)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC
        records = os.open(run_dir / EGRESS_RECORDS, flags, 0o600)
        log = os.open(run_dir / PROXY_LOG, flags, 0o600)
        ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        info_read, info_write = os.pipe()
        try:
            process = subprocess.Popen(
                proxy_argv(binds, control_fd=theirs.fileno(), records_fd=records, info_fd=info_write),
                pass_fds=(theirs.fileno(), records, info_write), stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, start_new_session=True,
            )
        except OSError as caught:
            ours.close()
            os.close(info_read)
            raise EgressUnproven("proxy-unstarted", f"cannot run bwrap: {caught}") from None
        finally:
            theirs.close()
            os.close(records)
            os.close(log)
            os.close(info_write)
        try:
            info = read_info(info_read, process)
        finally:
            os.close(info_read)
        child = None if info is None else info.get("child-pid")
        pidfd = -1
        if type(child) is int:
            try:
                pidfd = os.pidfd_open(child)
            except OSError:
                pidfd = -1
        if pidfd < 0:
            process.kill()
            process.wait()
            ours.close()
            raise EgressUnproven("proxy-unstarted", f"bwrap reported no proxy namespace (exit {process.returncode})")
        session = cls(process, child, pidfd, ours, run_dir)
        append_event(run_dir, "egress-proxy", pid=child, start_time=_start_time(child))
        send_message(ours, {"op": "route", "route": base64.b64encode(loaded.data).decode("ascii"), "lease": lease})
        reply = session._receive(PROXY_START_TIMEOUT)
        if reply is None or reply.get("op") != "ready":
            session.kill()
            raise EgressUnproven("proxy-unready", _why(reply, PROXY_START_TIMEOUT))
        append_event(run_dir, "egress-ready")
        return session

    def _receive(self, timeout: float) -> dict | None:
        if not select.select([self._control], [], [], timeout)[0]:
            return None
        message, fds = receive_message(self._control)
        for fd in fds:
            os.close(fd)
        return message

    def attach(self, child_pid: int, pidfd: int, *, make: Callable[[int, int], socket.socket] = make_listener) -> None:
        """`launch`'s `before_release` hook (§3 step 9). The orchestrator keeps no copy
        of the listener, so it lives only as long as the proxy does."""
        listener = make(child_pid, pidfd)
        try:
            send_message(self._control, {"op": "listener"}, [listener.fileno()])
        finally:
            listener.close()
        reply = self._receive(LISTENING_TIMEOUT)
        if reply is None or reply.get("op") != "listening":
            raise EgressUnproven("proxy-unlistening", _why(reply, LISTENING_TIMEOUT))
        append_event(self.run_dir, "egress-listening")

    def renew(self) -> None:
        send_message(self._control, {"op": "renew"})

    def exited(self) -> bool:
        return bool(select.select([self.pidfd], [], [], 0)[0])

    def close(self, timeout: float = CLOSE_TIMEOUT) -> EgressClosed:
        """Close step 0. B2 sends it together with the seal and waits on both."""
        send_message(self._control, {"op": "close"})
        exited = bool(select.select([self.pidfd], [], [], timeout)[0])
        if not exited:
            self._kill_namespace()
        self._release()
        return _settle(self.run_dir, timed_out=not exited)

    def kill(self) -> None:
        """For a start or hand-off that failed: no closing line is expected."""
        self._kill_namespace()
        self._release()

    def _kill_namespace(self) -> None:
        try:
            signal.pidfd_send_signal(self.pidfd, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _release(self) -> None:
        self.process.wait()
        self._control.close()
        if self.pidfd >= 0:
            os.close(self.pidfd)
            self.pidfd = -1


def _why(reply: dict | None, timeout: float) -> str:
    if reply is None:
        return f"no answer within {timeout:g} s"
    if reply.get("op") == "error":
        return f"{reply.get('code')}: {reply.get('message')}"
    return f"an unexpected answer: {reply}"


def kill_orphan(run_dir: Path, timeout: float = CLOSE_TIMEOUT) -> EgressClosed | None:
    """*Orphans* (spec §3): the proxy of a run whose orchestrator died has seen EOF and
    closed, or it is wedged. Wait up to `timeout` for its exit, then kill it. Returns
    None when the run started no proxy."""
    events_path = run_dir / EVENTS
    events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
    started = next((event for event in reversed(events) if event["event"] == "egress-proxy"), None)
    if started is None:
        return None
    timed_out = False
    try:
        pidfd = os.pidfd_open(started["pid"])
    except ProcessLookupError:
        pidfd = -1
    if pidfd >= 0:
        try:
            try:
                same = _start_time(started["pid"]) == started["start_time"]
            except FileNotFoundError:
                same = False
            if same and not select.select([pidfd], [], [], timeout)[0]:
                signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                timed_out = True
        finally:
            os.close(pidfd)
    return _settle(run_dir, timed_out)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `just test-one tests/test_egress_session.py tests/test_closing.py`
Expected: PASS. The session tests take about a minute: three of them wait out a 5 s
bound.

- [ ] **Step 5: Run the fast suite, then commit**

Run: `just test-fast`. Expected: PASS.

```bash
git add python/src/autonomy/egress/session.py python/src/autonomy/closing.py python/tests/test_egress_session.py python/tests/test_closing.py
git commit -m "feat(egress): the orchestrator's proxy session, with E21 and E22 under real bwrap"
```

---
### Task 10: The live pi recipe, the README, and the spec's status

**Files:**
- Create: `python/scripts/egress_live.py`
- Modify: `justfile` (the `live-egress` recipe)
- Modify: `README.md` (the model route section)
- Modify: `docs/specs/2026-10-12-envelope-design.md` (the status line for item 5)

**Interfaces:**
- Consumes: `places` (Task 3); `load_route` and `egress_denied` (Task 2);
  `EgressSession` (Task 9); `MODEL_URL` (Task 8); `launch` and `prove` (Task 1).
- Produces: `just live-egress <route> [model]`, E21's live arm. It never runs in the
  suite. It costs one short prompt and needs a model route whose credential is a real
  key.

- [ ] **Step 1: Write the recipe's script**

`python/scripts/egress_live.py`:

```python
"""E21's live arm, run by `just live-egress <route> [model]` and never in the suite: pi
in RPC mode, launched through B1's launch path with its proxy to the real API, and
configured only by a `models.json` base URL and a placeholder key (decision 13).

It needs:
- a model route at <config>/routes/<route>.toml whose credential file holds a real key;
- pi (PI_DIR, default ~/.local/share/pi/1.1.0) and node (NODE_DIR, default the prefix
  of the `node` on PATH).

It sends one prompt, about US$0.001 on a small model, and prints each `egress.jsonl`
line. It exits 0 when a request streamed to completion and none was refused. A refused
request's line and the actor's stderr name what the route lacks, such as a beta token
pi now sends."""

from __future__ import annotations

import json
import os
import select
import shutil
import sys
import tempfile
import time
from pathlib import Path

from autonomy.egress.helper import MODEL_URL
from autonomy.egress.route import egress_denied, load_route
from autonomy.egress.session import EgressSession
from autonomy.run import places
from autonomy.sandbox.bwrap import launch, prove
from autonomy.sandbox.spec import SandboxSpec


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: egress_live.py <route> [model]", file=sys.stderr)
        return 2
    model = argv[1] if len(argv) > 1 else "claude-haiku-5-5"
    where = places(os.environ)
    loaded = load_route(where.config, argv[0])
    node = shutil.which("node")
    if node is None and "NODE_DIR" not in os.environ:
        print("node is not on PATH; set NODE_DIR", file=sys.stderr)
        return 2
    node_dir = Path(os.environ.get("NODE_DIR") or Path(node).resolve().parent.parent)
    pi_dir = Path(os.environ.get("PI_DIR") or Path.home() / ".local/share/pi/1.1.0")
    where.cache.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="egress-live-", dir=where.cache))
    run_dir, scratch = root / "run", root / "scratch"
    agent, home = scratch / "agent", scratch / "home"
    for path in (run_dir, agent, home, scratch / "sessions"):
        path.mkdir(parents=True)
    (agent / "models.json").write_text(json.dumps(
        {"providers": {"anthropic": {"baseUrl": MODEL_URL, "apiKey": "placeholder"}}}
    ))
    env = {
        "PATH": f"{node_dir}/bin:/usr/bin", "HOME": str(home), "PI_CODING_AGENT_DIR": str(agent),
        "PI_OFFLINE": "1", "PI_TELEMETRY": "0", "LANG": "C.UTF-8", "VERIFIABLY_MODEL_URL": MODEL_URL,
    }
    spec = SandboxSpec(scratch=scratch, ro_binds=(node_dir, pi_dir), env=env)
    denied = egress_denied(where.config, loaded)
    prove(spec, denied)
    session = EgressSession.start(loaded, run_dir, lease=120, denied=denied)
    pi = [
        str(pi_dir / "node_modules/.bin/pi"), "--mode", "rpc", "--provider", "anthropic", "--model", model,
        "--thinking", "off", "--session-dir", str(scratch / "sessions"),
        "--no-approve", "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-mcp",
    ]
    to_pi_read, to_pi = os.pipe()
    from_pi, from_pi_write = os.pipe()
    with open(root / "pi.stderr", "wb") as stderr:
        actor = launch(spec, pi, stdin=to_pi_read, stdout=from_pi_write, stderr=stderr.fileno(),
                       before_release=session.attach)
    os.close(to_pi_read)
    os.close(from_pi_write)
    os.write(to_pi, json.dumps({"id": "p1", "type": "prompt", "message": "Reply with the single word: ok"}).encode() + b"\n")
    buffer, settled, renewed = b"", None, time.monotonic()
    deadline = time.monotonic() + 240
    while settled is None and time.monotonic() < deadline:
        if time.monotonic() - renewed > 30:
            session.renew()
            renewed = time.monotonic()
        if not select.select([from_pi], [], [], 5)[0]:
            continue
        chunk = os.read(from_pi, 65536)
        if not chunk:
            break
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            if line.strip() and json.loads(line).get("type") == "agent_settled":
                settled = json.loads(line)
    os.close(to_pi)
    try:
        actor.wait(timeout=30)
    finally:
        actor.close()
        os.close(from_pi)
    closed = session.close()
    lines = [json.loads(line) for line in (run_dir / "egress.jsonl").read_text().splitlines()]
    for line in lines:
        print(json.dumps(line))
    print(f"settled: {settled is not None}; route closed: {closed.cause}; findings: {[f.code for f in closed.findings()]}")
    print(f"records: {root}")
    served = [line for line in lines if line.get("status") == 200 and line.get("ended") == "complete"]
    refused = [line for line in lines if line.get("refused")]
    return 0 if served and not refused and settled is not None else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 2: Add the recipe**

In `justfile`, after the `test` recipe:

```just
# E21's live arm: pi through the model proxy to the real API. It costs one short prompt
# and never runs in the suite. Needs a model route whose credential is a real key.
live-egress route model="claude-haiku-5-5":
    {{tt}} live-egress -- sh -c 'cd python && uv run python scripts/egress_live.py "$0" "$1"' {{route}} {{model}}
```

- [ ] **Step 3: Document the model route**

In `README.md`, extend the usage block's first line with `[--model-route NAME]` and add
this section before `## Documentation`:

````markdown
### The model route

An actor has no network of its own. `--model-route NAME` gives it one path out: a
proxy on `VERIFIABLY_MODEL_URL` (`http://127.0.0.1:4780`) that forwards only the
route's operations to its one upstream and adds the provider credential there. The
actor never holds the credential. Point the harness at that URL with a placeholder
key. For pi, that is a provider `baseUrl` in its `models.json`:

```json
{"providers": {"anthropic": {"baseUrl": "http://127.0.0.1:4780", "apiKey": "placeholder"}}}
```

That configuration only directs pi. The proxy enforces the route whatever the actor
does to it (decision 13). The route is a TOML file at
`$XDG_CONFIG_HOME/verifiably-autonomy/routes/NAME.toml`:

```toml
api = "anthropic-messages"
upstream = "https://api.anthropic.com"
max_request_bytes = 8000000
forward_headers = ["anthropic-version", "anthropic-beta", "content-type", "accept", "user-agent"]

[header_tokens]
anthropic-version = ["2023-06-01"]
anthropic-beta = ["fine-grained-tool-streaming-2025-05-14", "interleaved-thinking-2025-05-14"]

[credential]
file = "/home/you/.config/verifiably-autonomy/credentials/anthropic"  # 0600, yours, one link
header = "x-api-key"

[[operations]]
method = "POST"
path = "/v1/messages"
queries = ["beta=true"]
models = ["claude-haiku-5-5"]
fields = ["model", "messages", "system", "max_tokens", "stream", "tools", "tool_choice",
          "thinking", "temperature", "metadata", "stop_sequences", "top_p", "top_k"]
block_types = ["text", "image", "tool_use", "tool_result", "thinking", "redacted_thinking"]
source_types = ["base64"]
```

What the route leaves out, the proxy refuses with a `403` that names the code, for
example `body-refused` for an MCP server or a URL image source. `just live-egress
NAME` runs pi through the proxy to the real API once and prints what the proxy
recorded, including any beta token pi sends that the route does not list.
````

- [ ] **Step 4: Record item 5's status in the spec**

In `docs/specs/2026-10-12-envelope-design.md`'s header, change "Item 5, the egress plan
(autonomy-e4c0b5), is open." to "Item 5, the egress plan (autonomy-e4c0b5,
`docs/plans/2026-10-17-envelope-plan-egress.md`), implemented on <date> on its launch
arms; its full-run arms join B2." Use the date the branch lands.

- [ ] **Step 5: Check, then commit**

Run: `just check` and `just test-fast`. Expected: PASS.

```bash
git add python/scripts/egress_live.py justfile README.md docs/specs/2026-10-12-envelope-design.md
git commit -m "docs(egress): the model route in the README, the live pi recipe, and item 5's status"
```

- [ ] **Step 6: Run the live recipe, after asking**

The recipe spends money and needs a real key in a route file, so the executor asks
the user before running it, and names the route and the model. With the user's go:
`just live-egress <route>`. Expected: exit 0, one `egress.jsonl` line with status
`200` and `ended: complete`, and the route closed `close` with no findings. A
`header-refused` line names a beta token pi sends that the route lacks. Report it, and
the route file is the user's to change.
