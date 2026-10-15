# Envelope Plan B1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** approved 2026-10-15 (human review round 2), after round 1 found 1 P1 and 4 P2,
all addressed. Round 2 left one P3, corrected during Task 4: `write_disposition`'s
contract and docstring promise "absent before publication, complete after
publication". An interruption after the link (at the directory fsync) leaves a
complete `disposition.json`, and a retry then raises `FileExistsError`.
Execution: superpowers:subagent-driven-development, Tasks 1–5 in order.

**Goal:** Build the launch side of `autonomy run`, which needs nothing from the
`beliefs` or `science` slices:

- the gate's own release fd under `python3`, with the actor's three descriptors
  passed explicitly;
- `/dev/null` as stdin for the preflight and the probe;
- step 2's `stdio-refused` check of fds 0–2 and the report fd;
- the non-blocking line channel for the report fd and stderr;
- the run frame: steps 1 and 2, `disposition.json`, the report fd's two lines, the
  exit code;
- the `autonomy run` CLI, with E1's CLI arm.

**Architecture:** Three new leaf modules (`stdio`, `channel`, `baseline`'s event log)
and two that compose them (`run`, `cli`), plus a change to the existing
`sandbox/bwrap.py`. The run frame takes steps 3 to 9 as a callable. This plan wires in
`endpoint_side_unbuilt`, which closes every run `unwired` with `baseline-unavailable`
before any chain is read or the actor starts. Plan B2 (autonomy-f6efe8) replaces it
with the endpoint side once the slices land.

**Tech Stack:** Python ≥ 3.11 (stdlib only at runtime, `ctypes` included), pytest,
pytest-testmon, bubblewrap ≥ 0.13, Linux.

**Spec:** `docs/specs/2026-10-12-envelope-design.md`: decision 12, §3 steps 1, 2 and 9
and *Close* step 4, §6, §7 (*The gate*), and rows E1 and E20. Plan A is
`docs/plans/2026-10-12-envelope-plan-a.md`; this plan changes its `launch`.

## Scope: B1 and B2

Spec §13 item 4 is Plan B. Both of its dependencies, beliefs-7a56ef and sci-a1d45f,
were unstarted on 2026-10-15, so Plan B is split:

- **B1 (this plan, autonomy-641123):**
  - E1's CLI arm;
  - E20's launch arm, as listed below;
  - §3 steps 1 and 2, except the two refusals that need the world;
  - *Close* step 4 (`disposition.json`, the closing line, the exit code).
- **B2 (autonomy-f6efe8):**
  - `science_reads`, `baseline.json`, `seal.json` and `endpoint`;
  - steps 3 to 9 and *Close* steps 1 to 3;
  - `run stop`, `run close` and `run show`;
  - step 2's two world refusals: the write corpus among the world's roots, and
    `orphaned-run`;
  - the wall-clock bound, whose value the spec leaves open;
  - rows E7 to E12 and E20's full-run arm.

E20's launch-arm items and where they land:

| E20 item | here |
|---|---|
| fds 3–16 held, gate fd above 9, echo actor over pipes and a socketpair, a line before and after the release, EOF exits 0 | Task 1 |
| the actor lists `/proc/self/fd` and sees 0–3 | Task 1 (Plan A's test, kept) |
| step 2: `/dev/null` and a socketpair pass; thirteen refusals exit 2 `stdio-refused`, no run directory, empty stdout, nothing on the report fd | Task 2 (classification), Task 5 (exit 2 through the CLI) |
| the preflight and the probe get stdin from `/dev/null` | Task 1 |
| each `science` read and the endpoint get stdin from `/dev/null` | **B2** |
| a run that closes `unwired` still writes the closing line after `disposition.json` | Task 4, at the step this build closes at (3, not 4) |
| the report pipe shrunk to one page, never read: exit 4 within bounds, `report-unwritten` | Tasks 4 and 5 |
| stderr a filled one-page pipe: a step-2 refusal still exits 2 | Task 5 |
| a competing writer between poll and write, on the report pipe, a stderr pipe and a socketpair report fd: `EAGAIN`, dropped, within bounds, the caller's descriptors still blocking | Task 3 (channel), Task 5 (CLI) |
| the terminal recipe returns 4 under bash and zsh | Task 5 |
| the negatives for each of the above | the same task |

## Global Constraints

- No kernel import: the package depends on neither `verifiably-beliefs` nor
  `verifiably-science` (AGENTS.md *Rules*; spec decision 1).
- Runtime is the stdlib only. `requires-python = ">=3.11"`.
- Tests run through the front door: `just test-one <pytest args>` while working (paths
  relative to `python/`), then `just test-fast` before each commit. Never call
  `pytest` directly.
- Tests that need `bwrap` carry `@pytest.mark.bwrap`.
- `autonomy run` never reads fd 0 and never writes fd 1, help and refusals included
  (decision 12).
- Every line to a caller's descriptor is one write of at most `PIPE_BUF` (4096) bytes,
  newline included, after at most 1 s of polling. It never blocks, and it never
  changes the caller's file status flags (decision 12, *No write can hang the run*).
  Only three kinds are ever written: a pipe (through a private non-blocking
  reopen), a socket (`MSG_DONTWAIT`) and `/dev/null` (skipped). Any other kind,
  such as a regular file, a terminal or a device, is never written: a reopen of a
  file loses `O_APPEND` and the offset, a file write can block on the filesystem, and
  a terminal write from a background process group can stop the process (SIGTTOU).
- No descriptor of `autonomy run`'s own is opened before step 2 has checked fds 0–2:
  a private descriptor opened while fd 0 is closed takes number 0 and passes the
  check.
- `disposition.json` is published atomically and never replaced: a temporary file in
  the run directory, written and fsynced, then hard-linked to the final name (`link`
  fails rather than replace), then the directory fsynced.
- Report lines, verbatim shapes: `{"run": "<run id>", "run_dir": "<path>", "scratch":
  "<path>"}` once step 2 passes, and `{"run": "<run id>", "disposition":
  "<clean|quarantined|unwired>", "exit": <code>}` after `disposition.json` is durable.
  Then the report fd is closed.
- Exit codes: 2 refused at configuration (no run directory), 0 `clean`, 3
  `quarantined`, 4 `unwired`.
- The lease floor is 10 s and the default is 60 s (§8).
- `<state>` = `$XDG_STATE_HOME/verifiably-autonomy`, `<cache>` =
  `$XDG_CACHE_HOME/verifiably-autonomy`. The run directory is
  `<state>/runs/<run-id>/`, scratch is `<cache>/scratch/<run-id>/`, and the socket
  directory is `$XDG_RUNTIME_DIR/va/<run-id[:12]>/`. The run id is 128-bit hex.
- The gate runs under `/usr/bin/python3 -I`. It takes its release on its own fd, never
  on stdin, closes that fd before exec, and exits 125 on EOF (§7).
- The actor is launched only from the main thread (§8).
- Paths in docs and commit messages are repository-relative.

## Review Focus

1. **Signal dispositions through the gate.** CPython ignores SIGPIPE and SIGXFSZ at
   startup, and an ignored disposition survives `exec`. A Python gate would hand the
   actor both ignored, so `yes | head` and an oversized write would behave unlike
   under a shell. The actor's `SigIgn` must have neither bit (Task 1).
2. **`autonomy run --help` and argparse usage errors.** argparse writes help to stdout
   and errors to a blocking stderr. Help must leave stdout empty, and a usage error with
   stderr a filled pipe must still exit 2 within bounds (Task 5).
3. **A report fd that is the read end of a pipe.** It is an anonymous pipe, so a check
   by kind alone passes it, and every report line is then silently dropped. Step 2
   refuses it `stdio-refused` (Task 2).
4. **A line longer than `PIPE_BUF`.** Long but valid XDG paths make the report fd's
   first line exceed 4096 bytes. That line is dropped whole, never truncated (a
   truncated JSON line would be a lie), and recorded `report-unwritten`, and the run
   closes normally with its disposition and exit code. A diagnostic is truncated to
   one write instead, because it is for a person (Task 3 drops an overlong line;
   Task 4 tests the long-path run; Task 5 truncates diagnostics).
5. **XDG variables.** A relative or empty `XDG_STATE_HOME` or `XDG_CACHE_HOME` is
   ignored, as the XDG spec requires, and the default applies. An unset
   `XDG_RUNTIME_DIR` is refused `runtime-dir-unset` with exit 2 and no run directory
   (Tasks 4 and 5).

---

## File structure

| path | responsibility |
|---|---|
| `python/src/autonomy/sandbox/bwrap.py` | modify: the Python gate on its own fd, explicit actor fds, bwrap in its own process group, `/dev/null` stdin for the preflight and the probe |
| `python/src/autonomy/stdio.py` | `StdioKind`, `StdioRefused`, `classify`, `check_stdio`, `check_report_fd` |
| `python/src/autonomy/channel.py` | `LineChannel`, `POLL_WAIT`, the `_before_write` test hook |
| `python/src/autonomy/baseline.py` | `utc_now`, `write_all`, `fsync_dir`, `append_event` (B2 adds `baseline.json` and `seal.json`) |
| `python/src/autonomy/run.py` | `RunRequest`, `RunRefused`, `Places`, `places`, `RunDirs`, `allocate`, `refuse`, `Opened`, `write_disposition`, `execute`, `endpoint_side_unbuilt` |
| `python/src/autonomy/cli.py` | `main`: the `autonomy run` parser and its diagnostics |
| `python/src/autonomy/__main__.py` | `python -m autonomy` |
| `python/pyproject.toml` | the `autonomy` console script |
| `python/tests/channels.py` | test helpers: `one_page_pipe`, `fill`, `blocking`, `read_all`, `drain` |
| `python/tests/test_sandbox_launch.py`, `test_sandbox_probe.py` | modify: explicit stdio, the gate and stdin tests |
| `python/tests/test_stdio.py`, `test_channel.py`, `test_run.py`, `test_cli.py` | one test module per new source module |
| `docs/specs/2026-10-12-envelope-design.md` | status line and §13 item 4: the split |
| `README.md` | the *Documentation* section names docs/specs and docs/plans |

---

### Task 1: The gate on its own fd, explicit actor stdio, and `/dev/null` for the preflight and probe (E20 launch arm)

**Files:**
- Modify: `python/src/autonomy/sandbox/bwrap.py` (`_GATE`, `launch`, `preflight`, `probe`)
- Modify: `python/tests/test_sandbox_launch.py`, `python/tests/test_sandbox_probe.py`

**Interfaces:**
- Consumes: Plan A's `SandboxSpec`, `build_argv`, `Sandboxed`, `SandboxUnproven`, `RELEASE`.
- Produces:
  - `launch(spec: SandboxSpec, argv: Iterable[str], *, stdin: int, stdout: int, stderr: int) -> Sandboxed`.
    Raises `ValueError` naming the stream when one of the three is not open.
  - The gate is `["/usr/bin/python3", "-I", "-c", _GATE, str(gate_fd), *argv]`.
    Tests read the gate's fd number from `argv[4]` of what `build_argv` receives.
  - bwrap runs in a process group of its own (`process_group=0`).

- [ ] **Step 1: Give the existing launch tests explicit stdio**

In `python/tests/test_sandbox_launch.py`, add this fixture after the imports and pass
`**stdio` to every existing `launch(...)` call. Each test that calls `launch` gains
the `stdio` parameter. In `test_the_actor_dies_with_its_orchestrator`, the
orchestrator script opens its own:

```python
@pytest.fixture
def stdio():
    """The actor's three descriptors, each on /dev/null."""
    fds = {name: os.open(os.devnull, os.O_RDWR) for name in ("stdin", "stdout", "stderr")}
    yield fds
    for fd in fds.values():
        os.close(fd)
```

```python
    orchestrator = textwrap.dedent(f"""
        import os, sys, time
        from pathlib import Path
        from autonomy.sandbox.bwrap import launch
        from autonomy.sandbox.spec import SandboxSpec
        null = os.open(os.devnull, os.O_RDWR)
        launch(SandboxSpec(scratch=Path({str(tmp_path)!r})), {actor(mark)!r}, stdin=null, stdout=null, stderr=null)
        print("ready", flush=True)
        time.sleep(300)
    """)
```

`test_an_interpreter_without_pidfds_is_refused_before_anything_starts` and
`test_launch_refuses_any_thread_but_the_main_one` take `stdio` too. The thread test
passes `**stdio` inside `body`.

- [ ] **Step 2: Write the failing gate tests**

Append to `python/tests/test_sandbox_launch.py` (add `import fcntl`, `import select`
and `import socket` to the imports):

```python
def read_all(fd: int, timeout: float = 10.0) -> bytes:
    data = b""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        assert remaining > 0, f"no EOF on fd {fd} within {timeout} s"
        if not select.select([fd], [], [], remaining)[0]:
            continue
        chunk = os.read(fd, 65536)
        if not chunk:
            return data
        data += chunk


@pytest.fixture
def gate_fds(monkeypatch):
    """The gate's release fd, as launch hands it to bwrap."""
    import autonomy.sandbox.bwrap as bwrap

    seen: list[int] = []
    real = bwrap.build_argv

    def spy(spec, argv, *, info_fd):
        seen.append(int(argv[4]))  # ["/usr/bin/python3", "-I", "-c", _GATE, <fd>, *actor]
        return real(spec, argv, info_fd=info_fd)

    monkeypatch.setattr(bwrap, "build_argv", spy)
    return seen


def channel_pair(kind: str) -> tuple[int, int, int, int]:
    """(actor's stdin, caller's writer, caller's reader, actor's stdout)."""
    if kind == "pipe":
        in_read, in_write = os.pipe()
        out_read, out_write = os.pipe()
        return in_read, in_write, out_read, out_write
    a, b = socket.socketpair()
    c, d = socket.socketpair()
    return a.detach(), b.detach(), c.detach(), d.detach()


@pytest.mark.parametrize("kind", ["pipe", "socket"])
def test_bytes_reach_the_actor_across_the_gate(tmp_path, gate_fds, kind):
    held = [os.open(os.devnull, os.O_RDONLY) for _ in range(14)]  # fds 3–16: the gate's pipe lands above 9
    actor_in, caller_in, caller_out, actor_out = channel_pair(kind)
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        os.write(caller_in, b"before\n")
        sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/cat"], stdin=actor_in, stdout=actor_out, stderr=null)
        os.close(actor_in)
        os.close(actor_out)
        try:
            os.write(caller_in, b"after\n")
            os.close(caller_in)
            assert read_all(caller_out) == b"before\nafter\n"
            assert sandboxed.wait(timeout=10) == 0
        finally:
            sandboxed.close()
    finally:
        for fd in (*held, null, caller_out):
            os.close(fd)
    assert gate_fds and gate_fds[0] > 9


SIGPIPE_BIT = 1 << (signal.SIGPIPE - 1)
SIGXFSZ_BIT = 1 << (signal.SIGXFSZ - 1)


def ignored_signals(tmp_path, stdio) -> int:
    sandboxed = launch(
        SandboxSpec(scratch=tmp_path), ["/usr/bin/sh", "-c", "grep SigIgn /proc/self/status > sigign"], **stdio
    )
    try:
        assert sandboxed.wait(timeout=10) == 0
    finally:
        sandboxed.close()
    return int((tmp_path / "sigign").read_text().split()[1], 16)


def test_the_actor_inherits_no_ignored_sigpipe_or_sigxfsz(tmp_path, stdio):  # Review Focus 1
    assert ignored_signals(tmp_path, stdio) & (SIGPIPE_BIT | SIGXFSZ_BIT) == 0


def test_a_gate_that_keeps_pythons_dispositions_ignores_sigpipe(tmp_path, stdio, monkeypatch):
    import autonomy.sandbox.bwrap as bwrap

    kept = "\n".join(line for line in bwrap._GATE.splitlines() if "SIG_DFL" not in line)
    monkeypatch.setattr(bwrap, "_GATE", kept)
    assert ignored_signals(tmp_path, stdio) & SIGPIPE_BIT


def test_a_gate_that_keeps_its_fd_shows_a_fifth_descriptor(tmp_path, stdio, monkeypatch):
    import autonomy.sandbox.bwrap as bwrap

    monkeypatch.setattr(bwrap, "_GATE", bwrap._GATE.replace("os.close(gate)\n", ""))
    sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/sh", "-c", "ls /proc/self/fd > fds"], **stdio)
    try:
        assert sandboxed.wait(timeout=10) == 0
    finally:
        sandboxed.close()
    assert len((tmp_path / "fds").read_text().split()) == 5


def test_run_on_stdin_never_releases_the_actor(tmp_path, monkeypatch):
    import autonomy.sandbox.bwrap as bwrap

    real_write = os.write
    monkeypatch.setattr(os, "write", lambda fd, data: len(data) if data == bwrap.RELEASE else real_write(fd, data))
    in_read, in_write = os.pipe()
    real_write(in_write, b"run\n")
    os.close(in_write)
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        sandboxed = launch(
            SandboxSpec(scratch=tmp_path), ["/usr/bin/sh", "-c", "echo ran > ran"], stdin=in_read, stdout=null, stderr=null
        )
        try:
            assert sandboxed.wait(timeout=10) == 125
        finally:
            sandboxed.close()
    finally:
        os.close(in_read)
        os.close(null)
    assert not (tmp_path / "ran").exists()


def test_a_report_fd_never_reaches_the_actor(tmp_path, stdio, monkeypatch):
    report_read, report_write = os.pipe()
    os.set_inheritable(report_write, True)  # even an inheritable one
    try:
        sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/sh", "-c", "ls /proc/self/fd > fds"], **stdio)
        try:
            assert sandboxed.wait(timeout=10) == 0
        finally:
            sandboxed.close()
        assert sorted((tmp_path / "fds").read_text().split()) == ["0", "1", "2", "3"]

        real = subprocess.Popen

        class Passing(real):
            def __init__(self, *args, **kwargs):
                kwargs["pass_fds"] = (*kwargs.get("pass_fds", ()), report_write)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(subprocess, "Popen", Passing)
        (tmp_path / "fds").unlink()
        sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/sh", "-c", "ls /proc/self/fd > fds"], **stdio)
        try:
            assert sandboxed.wait(timeout=10) == 0
        finally:
            sandboxed.close()
        assert len((tmp_path / "fds").read_text().split()) == 5  # a launch that passes it shows a fifth
    finally:
        os.close(report_read)
        os.close(report_write)


def test_bwrap_runs_in_a_process_group_of_its_own(tmp_path, stdio):
    sandboxed = launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/sleep", "5"], **stdio)
    try:
        assert os.getpgid(sandboxed.process.pid) == sandboxed.process.pid != os.getpgid(0)
    finally:
        sandboxed.close()


def test_a_closed_actor_descriptor_is_refused_before_anything_starts(tmp_path, stdio, monkeypatch):
    started: list[object] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a))
    closed = os.open(os.devnull, os.O_RDONLY)
    os.close(closed)
    with pytest.raises(ValueError, match="stdout"):
        launch(SandboxSpec(scratch=tmp_path), ["/usr/bin/true"], **{**stdio, "stdout": closed})
    assert started == []
```

The negatives that need no sandbox document why the gate is not a shell and never
reads stdin. Append them too:

```python
@pytest.mark.skipif(not Path("/usr/bin/dash").exists(), reason="needs /usr/bin/dash")
def test_a_shell_gate_under_dash_fails_on_an_fd_above_9():
    gate_read, gate_write = os.pipe()
    # a fresh descriptor above 9, never one another fixture or pytest already holds
    high = fcntl.fcntl(gate_read, fcntl.F_DUPFD_CLOEXEC, 10)
    os.close(gate_read)
    try:
        os.write(gate_write, b"run\n")
        result = subprocess.run(
            ["/usr/bin/dash", "-c", f"read -r go <&{high}"], pass_fds=(high,), capture_output=True, text=True,
            stdin=subprocess.DEVNULL,
        )
    finally:
        os.close(high)
        os.close(gate_write)
    assert high > 9
    assert result.returncode != 0 and "Bad fd number" in result.stderr


def test_a_release_read_on_stdin_eats_the_callers_first_line():
    in_read, in_write = os.pipe()
    os.write(in_write, b"before\nafter\n")
    os.close(in_write)
    try:
        result = subprocess.run(
            ["/usr/bin/sh", "-c", 'read -r go; [ "$go" = run ] || exit 125; exec cat'], stdin=in_read, capture_output=True
        )
    finally:
        os.close(in_read)
    assert result.returncode == 125 and result.stdout == b""


def test_a_gate_that_reopens_stdin_gives_the_actor_immediate_eof():
    in_read, in_write = os.pipe()
    os.write(in_write, b"before\n")
    os.close(in_write)
    try:
        result = subprocess.run(["/usr/bin/sh", "-c", "exec </dev/null; exec cat"], stdin=in_read, capture_output=True)
    finally:
        os.close(in_read)
    assert result.returncode == 0 and result.stdout == b""
```

In `python/tests/test_sandbox_probe.py`, append (add `import os` to the imports):

```python
@pytest.mark.bwrap
def test_the_preflight_and_the_probe_never_inherit_stdin(layout, monkeypatch):
    calls: list[dict] = []
    real = subprocess.run

    def recording(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording)
    prove(SandboxSpec(scratch=layout["scratch"]), (layout["corpus"],))
    assert len(calls) == 2
    assert all(call.get("stdin") is subprocess.DEVNULL for call in calls)


def test_a_child_that_inherits_stdin_consumes_the_callers_bytes():
    for stdin, left in ((None, b""), (subprocess.DEVNULL, b"early\n")):
        read_end, write_end = os.pipe()
        os.write(write_end, b"early\n")
        os.close(write_end)
        try:
            subprocess.run(["/usr/bin/head", "-c", "6"], stdin=read_end if stdin is None else stdin, stdout=subprocess.DEVNULL)
            assert os.read(read_end, 64) == left
        finally:
            os.close(read_end)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `just test-one tests/test_sandbox_launch.py tests/test_sandbox_probe.py`
Expected: FAIL. `launch()` rejects the `stdin`/`stdout`/`stderr` keywords (TypeError),
and the stdin test sees `stdin` unset on the preflight and probe calls.

- [ ] **Step 4: Implement the gate and the launch**

In `python/src/autonomy/sandbox/bwrap.py`, add `stdin=subprocess.DEVNULL` to the
`subprocess.run` call in `preflight` and to the one in `probe`. Replace `_GATE`, its
docstring, and `launch` with:

```python
_GATE = r"""
import os, signal, sys
gate = int(sys.argv[1])
line = b""
while len(line) < 4 and not line.endswith(b"\n"):
    chunk = os.read(gate, 1)
    if not chunk:
        break
    line += chunk
os.close(gate)
if line != b"run\n":
    os._exit(125)
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
try:
    os.execvp(sys.argv[2], sys.argv[2:])
except OSError as caught:
    os.write(2, f"va-gate: {sys.argv[2]}: {caught.strerror}\n".encode("utf-8", "replace"))
    os._exit(127)
"""
"""The program bwrap runs in front of the actor, under `/usr/bin/python3 -I` (spec §7).
It reads one line from its own pipe, named by number in its argv, closes that pipe,
and execs the actor only on `run`. EOF exits 125 without running the actor. It never
touches stdin, so the release cannot come from the caller and the caller's bytes reach
the actor intact. Not a shell: the pipe's number is often above 9, which dash rejects
(`Bad fd number`). CPython ignores SIGPIPE and SIGXFSZ at startup, and an ignored
disposition survives exec, so the gate restores both before it execs."""


def _require_open(**streams: int) -> None:
    for name, fd in streams.items():
        try:
            os.fstat(fd)
        except OSError as caught:
            raise ValueError(f"the actor's {name}, fd {fd}, is not open: {caught.strerror}") from caught


def launch(spec: SandboxSpec, argv: Iterable[str], *, stdin: int, stdout: int, stderr: int) -> Sandboxed:
    """Start the actor so that its handle exists before it can run.

    bwrap runs the gate (`_GATE`) holding the read end of a dedicated pipe. bwrap
    reports the namespace's init on --info-fd, the pidfd is opened while the gate still
    waits, and only then is `RELEASE` written. Every failure before that aborts through
    the pidfd or by killing bwrap, and the gate, seeing EOF, never runs the actor.

    The actor's fds 0, 1 and 2 are `stdin`, `stdout` and `stderr`, and it holds no
    other descriptor (decision 12). A closed one is refused, so a library caller never
    passes a stray descriptor. bwrap starts in a process group of its own, so a signal
    to the caller's group cannot kill the actor before the seal (§3 step 9)."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError(
            "launch the sandbox from the main thread: --die-with-parent is PR_SET_PDEATHSIG, "
            "which fires when the spawning thread exits"
        )
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise SandboxUnproven(
            "pidfd-unavailable",
            "python",
            "this interpreter lacks os.pidfd_open or signal.pidfd_send_signal; the actor cannot be "
            "held by a handle that survives pid reuse",
        )
    _require_open(stdin=stdin, stdout=stdout, stderr=stderr)
    info_read, info_write = os.pipe()
    gate_read, gate_write = os.pipe()
    gated = ["/usr/bin/python3", "-I", "-c", _GATE, str(gate_read), *argv]
    try:
        process = subprocess.Popen(
            build_argv(spec, gated, info_fd=info_write),
            pass_fds=(info_write, gate_read),
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            process_group=0,
        )
    except BaseException:
        os.close(info_read)
        os.close(gate_write)
        raise
    finally:
        os.close(info_write)
        os.close(gate_read)
```

The rest of `launch`, from `pidfd = -1` to `return Sandboxed(process, child, pidfd)`,
is unchanged. Update `_abort`'s docstring: "The gate's write end closes after this,
and EOF makes the gate exit 125 without running the actor even if something survived."

- [ ] **Step 5: Run the tests to verify they pass**

Run: `just test-one tests/test_sandbox_launch.py tests/test_sandbox_probe.py`
Expected: PASS, including every Plan A launch test.

- [ ] **Step 6: Commit**

```bash
just test-fast
git add python/src/autonomy/sandbox/bwrap.py python/tests/test_sandbox_launch.py python/tests/test_sandbox_probe.py
git commit -m "feat(sandbox): release the gate on its own fd and pass the actor's stdio explicitly"
```

---

### Task 2: What the actor's stdio and the report fd may be (E20 step 2)

**Files:**
- Create: `python/src/autonomy/stdio.py`, `python/tests/test_stdio.py`

**Interfaces:**
- Consumes: Task 1's `launch` (one bwrap test only).
- Produces:
  - `StdioKind = Literal["pipe", "socket", "null"]`, `ACTOR_FDS = (0, 1, 2)`.
  - `StdioRefused(fd: int, what: str)`, an `Exception` with `.code == "stdio-refused"`,
    `.fd`, `.what`, and `.message == f"fd {fd} is {what}"`.
  - `classify(fd: int) -> StdioKind`, which raises `StdioRefused`.
  - `check_stdio(fds: tuple[int, int, int] = ACTOR_FDS) -> tuple[StdioKind, StdioKind, StdioKind]`.
  - `check_report_fd(fd: int, actor_fds: tuple[int, int, int] = ACTOR_FDS) -> Literal["pipe", "socket"]`.

- [ ] **Step 1: Write the failing tests**

`python/tests/test_stdio.py`:

```python
import os
import socket
import stat
import secrets

import pytest

from autonomy.stdio import StdioRefused, check_report_fd, check_stdio, classify


@pytest.fixture
def opened(tmp_path):
    """make(kind) -> an fd of that kind, closed at teardown."""
    held: list = []

    def keep(*items):
        held.extend(items)

    def make(kind: str) -> int:
        if kind in ("pipe-read", "pipe-write"):
            read_end, write_end = os.pipe()
            keep(read_end, write_end)
            return read_end if kind == "pipe-read" else write_end
        if kind == "socketpair":
            a, b = socket.socketpair()
            keep(a, b)
            return a.fileno()
        if kind == "unix-seqpacket":
            a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            keep(a, b)
            return a.fileno()
        if kind == "terminal":
            master, slave = os.openpty()
            keep(master, slave)
            return slave
        if kind == "fifo":
            os.mkfifo(tmp_path / "fifo")
            fd = os.open(tmp_path / "fifo", os.O_RDWR)
        elif kind == "null":
            fd = os.open(os.devnull, os.O_RDWR)
        elif kind == "zero":
            fd = os.open("/dev/zero", os.O_RDONLY)
        elif kind == "regular":
            fd = os.open(tmp_path / "file", os.O_RDWR | os.O_CREAT, 0o600)
        elif kind == "directory":
            fd = os.open(tmp_path, os.O_RDONLY)
        elif kind == "closed":
            fd = os.open(os.devnull, os.O_RDONLY)
            os.close(fd)
            return fd
        elif kind == "udp":
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            keep(sock)
            return sock.fileno()
        elif kind == "unix-unconnected":
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            keep(sock)
            return sock.fileno()
        elif kind == "unix-listening":
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(f"\0va-test-{secrets.token_hex(8)}")  # abstract: no path-length limit
            sock.listen()
            keep(sock)
            return sock.fileno()
        elif kind == "inet-connected":
            server = socket.create_server(("127.0.0.1", 0))
            client = socket.create_connection(server.getsockname())
            keep(server, client)
            return client.fileno()
        else:
            raise AssertionError(kind)
        keep(fd)
        return fd

    yield make
    for item in held:
        if isinstance(item, socket.socket):
            item.close()
        else:
            try:
                os.close(item)
            except OSError:
                pass


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("pipe-read", "pipe"), ("pipe-write", "pipe"), ("socketpair", "socket"), ("null", "null")],
)
def test_the_three_kinds_pass(opened, kind, expected):
    assert classify(opened(kind)) == expected


@pytest.mark.parametrize(
    ("kind", "what"),
    [
        ("terminal", "a terminal"),
        ("regular", "a regular file"),
        ("directory", "a directory"),
        ("zero", "a character device (1:5)"),
        ("fifo", "a named FIFO"),
        ("udp", "a socket (AF_INET, datagram)"),
        ("unix-unconnected", "an unconnected AF_UNIX stream socket"),
        ("unix-listening", "a listening AF_UNIX stream socket"),
        ("unix-seqpacket", "a socket (AF_UNIX, seqpacket)"),
        ("inet-connected", "a socket (AF_INET, stream)"),
        ("closed", "closed"),
    ],
)
def test_everything_else_is_refused_naming_the_fd_and_what_it_is(opened, kind, what):
    fd = opened(kind)
    with pytest.raises(StdioRefused) as caught:
        classify(fd)
    assert (caught.value.code, caught.value.fd, caught.value.what) == ("stdio-refused", fd, what)
    assert caught.value.message == f"fd {fd} is {what}"


def test_inspecting_a_socket_leaves_its_flags_alone(opened):
    fd = opened("socketpair")
    before = os.get_blocking(fd)
    classify(fd)
    assert os.get_blocking(fd) == before and os.get_inheritable(fd) is False


def test_check_stdio_reports_each_kind(opened):
    fds = (opened("null"), opened("socketpair"), opened("pipe-write"))
    assert check_stdio(fds) == ("null", "socket", "pipe")


def test_check_stdio_names_the_first_refused_fd(opened):
    fds = (opened("null"), opened("terminal"), opened("regular"))
    with pytest.raises(StdioRefused) as caught:
        check_stdio(fds)
    assert caught.value.fd == fds[1]


@pytest.mark.parametrize("kind", ["pipe-write", "socketpair"])
def test_a_report_fd_may_be_a_pipe_or_a_connected_stream(opened, kind):
    actor = (opened("null"), opened("pipe-write"), opened("pipe-write"))
    assert check_report_fd(opened(kind), actor) in ("pipe", "socket")


def test_a_report_fd_that_is_an_actor_fd_is_refused(opened):
    actor = (opened("null"), opened("pipe-write"), opened("pipe-write"))
    with pytest.raises(StdioRefused) as caught:
        check_report_fd(actor[1], actor)
    assert "the actor's" in caught.value.what


def test_a_report_fd_duplicated_from_an_actor_fd_is_refused(opened):
    actor = (opened("null"), opened("pipe-write"), opened("pipe-write"))
    duplicate = os.dup(actor[2])  # `3>&2`
    try:
        with pytest.raises(StdioRefused) as caught:
            check_report_fd(duplicate, actor)
    finally:
        os.close(duplicate)
    assert caught.value.what == f"the same file as fd {actor[2]}"


@pytest.mark.parametrize("kind", ["null", "terminal", "regular", "closed"])
def test_a_report_fd_of_another_kind_is_refused(opened, kind):
    actor = (opened("null"), opened("pipe-write"), opened("pipe-write"))
    with pytest.raises(StdioRefused):
        check_report_fd(opened(kind), actor)


def test_a_report_fd_that_is_a_read_end_is_refused(opened):  # Review Focus 3
    actor = (opened("null"), opened("pipe-write"), opened("pipe-write"))
    with pytest.raises(StdioRefused) as caught:
        check_report_fd(opened("pipe-read"), actor)
    assert "read-only" in caught.value.what


# Negatives: each weaker check passes something step 2 must refuse.

def test_any_character_device_but_a_tty_would_pass_dev_zero(opened):
    zero = opened("zero")
    assert stat.S_ISCHR(os.fstat(zero).st_mode) and not os.isatty(zero)


def test_s_issock_alone_would_pass_a_udp_socket(opened):
    assert stat.S_ISSOCK(os.fstat(opened("udp")).st_mode)


def test_so_peercred_alone_would_pass_an_unconnected_unix_socket(opened):
    probe = socket.socket(fileno=os.dup(opened("unix-unconnected")))
    try:
        probe.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)  # raises nothing
    finally:
        probe.close()


def test_a_report_check_by_number_alone_would_pass_a_duplicate_of_fd_2(opened):
    actor = (opened("null"), opened("pipe-write"), opened("pipe-write"))
    duplicate = os.dup(actor[2])
    try:
        assert duplicate not in actor
    finally:
        os.close(duplicate)


@pytest.mark.bwrap
def test_a_udp_socket_on_stdio_reaches_the_host_under_network_none(tmp_path, opened):
    from autonomy.sandbox.bwrap import launch
    from autonomy.sandbox.spec import SandboxSpec

    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    listener.settimeout(10)
    port = listener.getsockname()[1]
    udp, null = opened("udp"), opened("null")
    try:
        sandboxed = launch(
            SandboxSpec(scratch=tmp_path, network="none"),
            ["/usr/bin/python3", "-I", "-c", f"import socket; socket.socket(fileno=1).sendto(b'out', ('127.0.0.1', {port}))"],
            stdin=null, stdout=udp, stderr=null,
        )
        try:
            assert sandboxed.wait(timeout=10) == 0
        finally:
            sandboxed.close()
        assert listener.recvfrom(16)[0] == b"out"
    finally:
        listener.close()
    with pytest.raises(StdioRefused):
        classify(udp)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-one tests/test_stdio.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.stdio'`.

- [ ] **Step 3: Implement**

`python/src/autonomy/stdio.py`:

```python
"""What the actor's stdio and the report fd may be (envelope design decision 12, §3
step 2).

Each of fds 0, 1 and 2 must be an anonymous pipe, a connected AF_UNIX stream socket,
or /dev/null. Anything else hands the actor a host object by descriptor, past the
static check and the probe: a terminal's keystrokes, a file it can reopen read-write
through /proc/self/fd, a socket into the host's network namespace. The report fd must
be a writable pipe or connected stream that is none of the actor's three."""

from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import socket
import stat
from typing import Literal

StdioKind = Literal["pipe", "socket", "null"]
ACTOR_FDS: tuple[int, int, int] = (0, 1, 2)
PIPEFS_MAGIC = 0x50495045
_NULL_RDEV = os.makedev(1, 3)
_FAMILIES = {socket.AF_UNIX: "AF_UNIX", socket.AF_INET: "AF_INET", socket.AF_INET6: "AF_INET6"}
_TYPES = {socket.SOCK_STREAM: "stream", socket.SOCK_DGRAM: "datagram", socket.SOCK_SEQPACKET: "seqpacket"}

_libc = ctypes.CDLL(None, use_errno=True)
_libc.fstatfs.argtypes = (ctypes.c_int, ctypes.c_void_p)


class StdioRefused(Exception):
    """A descriptor step 2 refuses: the run exits 2 `stdio-refused`."""

    code = "stdio-refused"

    def __init__(self, fd: int, what: str) -> None:
        self.fd = fd
        self.what = what
        self.message = f"fd {fd} is {what}"
        super().__init__(f"{self.code}: {self.message}")


def _fs_type(fd: int) -> int:
    """fstatfs(2)'s f_type: the first field of struct statfs, a long on 64-bit Linux."""
    buffer = ctypes.create_string_buffer(256)  # struct statfs is 120 bytes
    if _libc.fstatfs(fd, buffer) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return ctypes.c_long.from_buffer(buffer).value


def _socket_kind(fd: int) -> StdioKind:
    probe = socket.socket(fileno=os.dup(fd))  # a private duplicate; its close leaves `fd` open
    try:
        family = probe.getsockopt(socket.SOL_SOCKET, socket.SO_DOMAIN)
        kind = probe.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
        if family != socket.AF_UNIX or kind != socket.SOCK_STREAM:
            name = f"{_FAMILIES.get(family, f'family {family}')}, {_TYPES.get(kind, f'type {kind}')}"
            raise StdioRefused(fd, f"a socket ({name})")
        if probe.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN):
            raise StdioRefused(fd, "a listening AF_UNIX stream socket")
        try:
            probe.getpeername()
        except OSError as caught:
            if caught.errno != errno.ENOTCONN:
                raise
            raise StdioRefused(fd, "an unconnected AF_UNIX stream socket") from None
        return "socket"
    finally:
        probe.close()


def classify(fd: int) -> StdioKind:
    try:
        info = os.fstat(fd)
    except OSError as caught:
        if caught.errno == errno.EBADF:
            raise StdioRefused(fd, "closed") from None
        raise
    mode = info.st_mode
    if stat.S_ISFIFO(mode):
        if _fs_type(fd) == PIPEFS_MAGIC:
            return "pipe"
        raise StdioRefused(fd, "a named FIFO")
    if stat.S_ISSOCK(mode):
        return _socket_kind(fd)
    if stat.S_ISCHR(mode):
        if info.st_rdev == _NULL_RDEV:
            return "null"
        if os.isatty(fd):
            raise StdioRefused(fd, "a terminal")
        raise StdioRefused(fd, f"a character device ({os.major(info.st_rdev)}:{os.minor(info.st_rdev)})")
    if stat.S_ISREG(mode):
        raise StdioRefused(fd, "a regular file")
    if stat.S_ISDIR(mode):
        raise StdioRefused(fd, "a directory")
    raise StdioRefused(fd, f"a file of mode {stat.filemode(mode)}")


def check_stdio(fds: tuple[int, int, int] = ACTOR_FDS) -> tuple[StdioKind, StdioKind, StdioKind]:
    first, second, third = (classify(fd) for fd in fds)
    return first, second, third


def _identity(fd: int) -> tuple[int, int]:
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def check_report_fd(fd: int, actor_fds: tuple[int, int, int] = ACTOR_FDS) -> Literal["pipe", "socket"]:
    """Call after `check_stdio(actor_fds)` has passed, so every actor fd is open."""
    if fd in actor_fds:
        raise StdioRefused(fd, f"the actor's fd {actor_fds.index(fd)}; the report fd must be another descriptor")
    kind = classify(fd)
    if kind == "null":
        raise StdioRefused(fd, "/dev/null; the report fd must be an anonymous pipe or a connected AF_UNIX stream socket")
    if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY:
        raise StdioRefused(fd, "opened read-only, such as a pipe's read end")
    identity = _identity(fd)
    for actor_fd in actor_fds:
        if _identity(actor_fd) == identity:
            raise StdioRefused(fd, f"the same file as fd {actor_fd}")
    return kind
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `just test-one tests/test_stdio.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
just test-fast
git add python/src/autonomy/stdio.py python/tests/test_stdio.py
git commit -m "feat(stdio): classify the actor's stdio and the report fd for step 2"
```

---

### Task 3: The non-blocking line channel (E20 report fd and stderr writes)

**Files:**
- Create: `python/src/autonomy/channel.py`, `python/tests/channels.py`, `python/tests/test_channel.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `LineChannel(fd: int)`, with `.fd`, `.dropped: bool`,
    `.write_line(line: str) -> bool` (False when dropped, including a line longer
    than `PIPE_BUF` with its newline, which is dropped whole and drops the channel;
    `ValueError` only for a line holding a newline, a caller's bug), and `.close()`,
    which releases the private path, leaves `fd` open and drops every later line.
  - A descriptor that is not a pipe, a socket or `/dev/null` is dropped at
    construction and never written: no reopen, no write.
  - Constructing a channel may open a descriptor (the private reopen, or a socket's
    dup), so callers construct it only after step 2 has checked fds 0–2.
  - `POLL_WAIT = 1.0`. The test hook `_before_write: Callable[[int], None] | None`
    is called with `.fd` between the poll and the write.
  - Test helpers in `python/tests/channels.py`: `one_page_pipe() -> tuple[int, int]`,
    `fill(fd: int) -> None`, `blocking(fd: int) -> bool`,
    `read_all(fd: int, timeout: float = 10.0) -> bytes`, `drain(fd: int) -> bytes`.

- [ ] **Step 1: Write the helpers and the failing tests**

`python/tests/channels.py`:

```python
"""Helpers for tests that drive a caller's descriptors: pipes shrunk to one page,
channels filled to the last byte, and reads that fail rather than hang."""

import fcntl
import os
import select
import socket
import stat
import time


def one_page_pipe() -> tuple[int, int]:
    read_end, write_end = os.pipe()
    fcntl.fcntl(write_end, fcntl.F_SETPIPE_SZ, 4096)
    return read_end, write_end


def fill(fd: int) -> None:
    """Fill a pipe or stream socket to its last byte through a private non-blocking
    path, leaving `fd`'s own flags alone."""
    if stat.S_ISSOCK(os.fstat(fd).st_mode):
        sock = socket.socket(fileno=os.dup(fd))
        try:
            for size in (4096, 1):
                try:
                    while True:
                        sock.send(b"x" * size, socket.MSG_DONTWAIT)
                except BlockingIOError:
                    pass
        finally:
            sock.close()
        return
    private = os.open(f"/proc/self/fd/{fd}", os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        for size in (4096, 1):
            try:
                while True:
                    os.write(private, b"x" * size)
            except BlockingIOError:
                pass
    finally:
        os.close(private)


def blocking(fd: int) -> bool:
    return not fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_NONBLOCK


def read_all(fd: int, timeout: float = 10.0) -> bytes:
    """Everything up to EOF; fails the test rather than hang."""
    data = b""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        assert remaining > 0, f"no EOF on fd {fd} within {timeout} s"
        if not select.select([fd], [], [], remaining)[0]:
            continue
        chunk = os.read(fd, 65536)
        if not chunk:
            return data
        data += chunk


def drain(fd: int) -> bytes:
    """What is readable now, without waiting for EOF. Sets `fd` non-blocking: check
    `blocking` first."""
    os.set_blocking(fd, False)
    data = b""
    try:
        while chunk := os.read(fd, 65536):
            data += chunk
    except BlockingIOError:
        pass
    return data
```

`python/tests/test_channel.py`:

```python
import os
import socket
import subprocess
import sys
import textwrap
import time

import pytest

import autonomy.channel as channel
from autonomy.channel import LineChannel
from channels import blocking, drain, fill, one_page_pipe


@pytest.fixture(autouse=True)
def short_poll(monkeypatch):
    monkeypatch.setattr(channel, "POLL_WAIT", 0.2)


def test_a_line_reaches_a_pipe_and_the_callers_flags_are_untouched():
    read_end, write_end = os.pipe()
    try:
        line = LineChannel(write_end)
        assert line.write_line('{"run": "x"}') is True
        assert drain(read_end) == b'{"run": "x"}\n'
        assert blocking(write_end)
        line.close()
        os.fstat(write_end)  # still open
    finally:
        os.close(read_end)
        os.close(write_end)


def test_a_line_reaches_a_socket_and_the_callers_flags_are_untouched():
    mine, theirs = socket.socketpair()
    with mine, theirs:
        line = LineChannel(mine.fileno())
        assert line.write_line("hello") is True
        assert theirs.recv(64) == b"hello\n"
        assert blocking(mine.fileno())
        line.close()


def test_dev_null_is_skipped():
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        assert LineChannel(null).write_line("nothing") is True
    finally:
        os.close(null)


def test_a_closed_descriptor_drops_every_line():
    closed = os.open(os.devnull, os.O_RDONLY)
    os.close(closed)
    line = LineChannel(closed)
    assert line.write_line("lost") is False and line.dropped


def test_an_appended_log_is_never_written(tmp_path):  # a reopen would lose O_APPEND and the offset
    log = tmp_path / "existing.log"
    log.write_bytes(b"earlier lines\n")
    fd = os.open(log, os.O_WRONLY | os.O_APPEND)  # `2>>existing.log`
    try:
        line = LineChannel(fd)
        assert line.write_line("autonomy: refused: stdio-refused: fd 2 is a regular file") is False
        assert line.dropped and line._private == -1
    finally:
        os.close(fd)
    assert log.read_bytes() == b"earlier lines\n"


@pytest.mark.parametrize("kind", ["terminal", "zero"])
def test_a_terminal_or_a_device_is_never_written(kind):
    # a terminal write from a background process group can stop the process (SIGTTOU)
    if kind == "terminal":
        master, fd = os.openpty()
    else:
        master, fd = None, os.open("/dev/zero", os.O_WRONLY)
    try:
        line = LineChannel(fd)
        assert line.write_line("never") is False and line._private == -1
        if master is not None:
            os.set_blocking(master, False)
            with pytest.raises(BlockingIOError):
                os.read(master, 64)  # nothing reached the terminal (read while its slave is open)
    finally:
        os.close(fd)
        if master is not None:
            os.close(master)


def test_a_full_pipe_drops_the_line_within_the_poll_wait_and_nothing_follows():
    read_end, write_end = one_page_pipe()
    try:
        fill(write_end)
        line = LineChannel(write_end)
        started = time.monotonic()
        assert line.write_line("first") is False
        assert time.monotonic() - started < 2
        drain(read_end)
        assert line.write_line("second") is False  # after a drop, nothing more
        assert drain(read_end) == b""
        assert blocking(write_end)
    finally:
        os.close(read_end)
        os.close(write_end)


@pytest.mark.parametrize("kind", ["pipe", "socket"])
def test_a_competing_writer_after_the_poll_gives_a_drop(monkeypatch, kind):
    if kind == "pipe":
        read_end, write_end = one_page_pipe()
        ends = (read_end, write_end)
    else:
        a, b = socket.socketpair()
        read_end, write_end = b.fileno(), a.fileno()
        ends = (a, b)
    second = os.dup(write_end)  # the second writer the caller holds
    monkeypatch.setattr(channel, "_before_write", lambda fd: fill(second) if fd == write_end else None)
    try:
        line = LineChannel(write_end)
        assert line.write_line('{"run": "x"}') is False
        assert line.dropped
        assert blocking(write_end) and blocking(second)
    finally:
        os.close(second)
        for end in ends:
            end.close() if isinstance(end, socket.socket) else os.close(end)


def test_a_pipe_with_no_reader_drops_the_line():
    read_end, write_end = os.pipe()
    os.close(read_end)
    try:
        assert LineChannel(write_end).write_line("lost") is False
    finally:
        os.close(write_end)


def test_a_line_longer_than_pipe_buf_is_dropped_whole():  # Review Focus 4
    read_end, write_end = os.pipe()
    try:
        line = LineChannel(write_end)
        assert line.write_line("x" * 4095) is True  # 4096 bytes with its newline: one write
        assert line.write_line("x" * 4096) is False  # 4097: dropped, never truncated or split
        assert line.dropped
        assert line.write_line("short") is False  # after a drop, nothing more
        assert drain(read_end) == b"x" * 4095 + b"\n"
    finally:
        os.close(read_end)
        os.close(write_end)


def test_a_line_holding_a_newline_is_a_callers_bug():
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        with pytest.raises(ValueError):
            LineChannel(null).write_line("two\nlines")
    finally:
        os.close(null)


def test_the_private_descriptor_is_not_inheritable():
    read_end, write_end = os.pipe()
    try:
        line = LineChannel(write_end)
        assert os.get_inheritable(line._private) is False
        line.close()
    finally:
        os.close(read_end)
        os.close(write_end)


# Negatives: why the channel reopens instead of setting flags, and never blocks.

def test_a_nonblocking_dup_leaves_the_original_description_nonblocking():
    read_end, write_end = os.pipe()
    duplicate = os.dup(write_end)
    try:
        os.set_blocking(duplicate, False)
        assert not blocking(write_end)
    finally:
        for fd in (read_end, write_end, duplicate):
            os.close(fd)


HANGS = {
    "a blocking write to a full pipe": """
        import os, fcntl
        r, w = os.pipe(); fcntl.fcntl(w, fcntl.F_SETPIPE_SZ, 4096)
        os.write(w, b"x" * 4096)
        os.write(w, b"line\\n")
    """,
    "a poll followed by a blocking write": """
        import os, fcntl, select
        r, w = os.pipe(); fcntl.fcntl(w, fcntl.F_SETPIPE_SZ, 4096)
        p = select.poll(); p.register(w, select.POLLOUT)
        assert p.poll(1000)
        os.write(w, b"x" * 4096)  # the competing writer fills it
        os.write(w, b"line\\n")
    """,
}


@pytest.mark.parametrize("name", sorted(HANGS))
def test_a_blocking_write_hangs(name):
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run([sys.executable, "-c", textwrap.dedent(HANGS[name])], timeout=2, stdin=subprocess.DEVNULL)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-one tests/test_channel.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.channel'`.

- [ ] **Step 3: Implement**

`python/src/autonomy/channel.py`:

```python
"""Lines to a caller's descriptor that can never hang the run (envelope design
decision 12): the report fd's two lines, and diagnostics on stderr before the actor
starts.

The caller's open file description is never changed. A pipe is written through a
private descriptor opened on /proc/self/fd/<n> with O_NONBLOCK: a new description of
the same pipe, whereas a dup would share, and change, the caller's flags. A socket is
written with MSG_DONTWAIT on each send. /dev/null is skipped. Nothing else is ever
written: a reopened regular file loses O_APPEND and its offset and would overwrite the
caller's log, a file write can block on the filesystem, and a terminal write from a
background process group can stop the process with SIGTTOU.

Each line is one write of at most PIPE_BUF bytes, after waiting at most POLL_WAIT for
the descriptor to poll writable. A line whose write fails, would block or is short is
dropped, and so is a line too long for one write, whole. After a drop nothing more is
written on that descriptor, so a short line is never followed by another.

Constructing a channel may open a descriptor, so a caller constructs it only after
step 2 has checked fds 0-2: opened while fd 0 is closed, it would take number 0."""

from __future__ import annotations

import os
import select
import socket
import stat
from collections.abc import Callable

POLL_WAIT = 1.0
"""Seconds a line may wait for its descriptor to poll writable."""

_NULL_RDEV = os.makedev(1, 3)

_before_write: Callable[[int], None] | None = None
"""Test hook (spec row E20): called with the caller's descriptor between the poll and
the write, where a competing writer can fill the channel."""


class LineChannel:
    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.dropped = False
        self._skip = False
        self._socket: socket.socket | None = None
        self._private = -1
        try:
            info = os.fstat(fd)
        except OSError:
            self.dropped = True
            return
        if stat.S_ISSOCK(info.st_mode):
            self._socket = socket.socket(fileno=os.dup(fd))
        elif stat.S_ISCHR(info.st_mode) and info.st_rdev == _NULL_RDEV:
            self._skip = True
        elif stat.S_ISFIFO(info.st_mode):
            try:
                self._private = os.open(f"/proc/self/fd/{fd}", os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            except OSError:
                self.dropped = True
        else:
            self.dropped = True  # a file, a terminal, a device: never written

    def write_line(self, line: str) -> bool:
        """Write `line` and a newline in one write; False when the line was dropped."""
        data = line.encode("utf-8") + b"\n"
        if b"\n" in data[:-1]:
            raise ValueError("a line holds no newline")
        if self.dropped:
            return False
        if len(data) > select.PIPE_BUF:
            self.close()  # dropped whole: a truncated line would say something false
            return False
        if self._skip:
            return True
        target = self._socket.fileno() if self._socket is not None else self._private
        poller = select.poll()
        poller.register(target, select.POLLOUT)
        poller.poll(POLL_WAIT * 1000)
        if _before_write is not None:
            _before_write(self.fd)
        try:
            if self._socket is not None:
                written = self._socket.send(data, socket.MSG_DONTWAIT | socket.MSG_NOSIGNAL)
            else:
                written = os.write(self._private, data)
        except OSError:
            written = -1
        if written != len(data):
            self.close()
            return False
        return True

    def close(self) -> None:
        """Release the private path and drop every later line; `fd` itself stays open."""
        self.dropped = True
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._private >= 0:
            os.close(self._private)
            self._private = -1
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `just test-one tests/test_channel.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
just test-fast
git add python/src/autonomy/channel.py python/tests/channels.py python/tests/test_channel.py
git commit -m "feat(channel): write report and diagnostic lines that never block the run"
```

---

### Task 4: The run frame: steps 1 and 2, the event log, `disposition.json` and the report lines

**Files:**
- Create: `python/src/autonomy/baseline.py`, `python/src/autonomy/run.py`, `python/tests/test_run.py`

**Interfaces:**
- Consumes: Task 2's `check_stdio`, `check_report_fd`, `StdioRefused`, `StdioKind`,
  `ACTOR_FDS`; Task 3's `LineChannel`; Plan A's `Tier`, `REPORT_ONLY`, `Finding`
  (`autonomy.membership`) and `disposition_of`, `Disposition` (`autonomy.closing`).
- Produces:
  - `baseline.utc_now() -> str`, `baseline.write_all(fd: int, data: bytes) -> None`,
    `baseline.fsync_dir(path: Path) -> None`, and
    `baseline.append_event(run_dir: Path, event: str, **fields: object) -> None`,
    which writes one sorted-key JSON line `{"at", "event", ...}` per call, fsynced.
  - `run.LEASE_FLOOR = 10.0`, `run.LEASE_DEFAULT = 60.0`, `run.EXIT_REFUSED = 2`,
    `run.EXIT_CODES: Mapping[Disposition, int]`.
  - `RunRefused(code: str, message: str)`, an `Exception` with `.code` and `.message`.
  - `RunRequest(tier: Tier, lease: float, report_fd: int | None, actor_argv: tuple[str, ...])`.
  - `Places(state: Path, cache: Path, runtime: Path)` and
    `places(env: Mapping[str, str]) -> Places`, which raises
    `RunRefused("runtime-dir-unset")`.
  - `RunDirs(run_id: str, run_dir: Path, scratch: Path, socket_dir: Path)` and
    `allocate(where: Places) -> RunDirs`.
  - `refuse(request: RunRequest, *, actor_fds=ACTOR_FDS) -> tuple[StdioKind, StdioKind, StdioKind]`.
  - `Opened(request: RunRequest, dirs: RunDirs, stdio: tuple[StdioKind, StdioKind, StdioKind])`.
  - `Steps = Callable[[Opened], Sequence[Finding]]`.
  - `write_disposition(run_dir: Path, run_id: str, disposition: Disposition, findings: Sequence[Finding]) -> None`:
    published atomically under its final name, never replacing one (`FileExistsError`);
    an interrupted call leaves no `disposition.json`, and a retry succeeds.
  - `execute(request, env, steps, *, diag: Callable[[str], None], actor_fds=ACTOR_FDS) -> int`.
  - `endpoint_side_unbuilt(opened: Opened) -> tuple[Finding, ...]`.

Two choices this task makes, both bounded by the spec:

- **Order of steps 1 and 2.** Step 2's checks run before step 1's directories are
  created, so a refusal never creates a run directory, rather than creating and then
  removing one ("no run directory kept"). The report fd's first line follows
  allocation, as §3 requires ("once these pass").
- **`disposition.json` for a run closed before step 3 completes.** Such a run has no
  baseline and no intervals. Its record is `members: {}` and `closing_heads: null`
  alongside §9's `{version, run, disposition, findings[], closed_at}`. B2 fills both for
  runs that reach a seal.

- [ ] **Step 1: Write the failing tests**

`python/tests/test_run.py`:

```python
import json
import os
import stat
from pathlib import Path

import pytest

import autonomy.channel as channel
from autonomy.baseline import append_event
from autonomy.membership import Finding
from autonomy.run import (
    RunRefused, RunRequest, allocate, endpoint_side_unbuilt, execute, places, write_disposition,
)
from autonomy.tiers import REPORT_ONLY
from channels import drain, fill, one_page_pipe, read_all


@pytest.fixture(autouse=True)
def short_poll(monkeypatch):
    monkeypatch.setattr(channel, "POLL_WAIT", 0.2)


@pytest.fixture
def env(tmp_path):
    for name in ("state", "cache", "runtime", "home"):
        (tmp_path / name).mkdir()
    return {
        "HOME": str(tmp_path / "home"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_RUNTIME_DIR": str(tmp_path / "runtime"),
    }


@pytest.fixture
def actor():
    fds = tuple(os.open(os.devnull, os.O_RDWR) for _ in range(3))
    yield fds
    for fd in fds:
        os.close(fd)


def request(report_fd=None, lease=60.0) -> RunRequest:
    return RunRequest(REPORT_ONLY, lease, report_fd, ("/usr/bin/true",))


def runs(tmp_path) -> list[Path]:
    root = tmp_path / "state" / "verifiably-autonomy" / "runs"
    return sorted(root.iterdir()) if root.exists() else []


def events(run_dir: Path) -> list[dict]:
    path = run_dir / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_a_run_closes_with_its_disposition_and_both_report_lines(tmp_path, env, actor):
    read_end, write_end = os.pipe()
    said: list[str] = []
    try:
        code = execute(request(write_end), env, endpoint_side_unbuilt, diag=said.append, actor_fds=actor)
        lines = read_all(read_end).decode().splitlines()  # EOF: execute closed the report fd
    finally:
        os.close(read_end)
    assert code == 4
    first, closing = (json.loads(line) for line in lines)
    run_dir = Path(first["run_dir"])
    assert run_dir == tmp_path / "state" / "verifiably-autonomy" / "runs" / first["run"]
    assert Path(first["scratch"]) == (tmp_path / "cache" / "verifiably-autonomy" / "scratch" / first["run"]).resolve()
    assert closing == {"run": first["run"], "disposition": "unwired", "exit": 4}
    record = json.loads((run_dir / "disposition.json").read_text())
    assert record["version"] == 1 and record["run"] == first["run"] and record["disposition"] == "unwired"
    assert [finding["code"] for finding in record["findings"]] == ["baseline-unavailable"]
    assert record["members"] == {} and record["closing_heads"] is None
    assert events(run_dir) == []
    assert any(first["run"] in line for line in said)


def test_the_closing_line_follows_a_durable_disposition(tmp_path, env, actor, monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr(
        channel, "_before_write",
        lambda fd: seen.append([p.name for p in tmp_path.glob("state/verifiably-autonomy/runs/*/disposition.json")]),
    )
    read_end, write_end = os.pipe()
    try:
        execute(request(write_end), env, endpoint_side_unbuilt, diag=lambda _: None, actor_fds=actor)
    finally:
        os.close(read_end)
    assert seen == [[], ["disposition.json"]]


def test_without_a_report_fd_only_the_exit_code_tells(tmp_path, env, actor):
    assert execute(request(), env, endpoint_side_unbuilt, diag=lambda _: None, actor_fds=actor) == 4
    assert len(runs(tmp_path)) == 1


def test_a_full_report_pipe_never_holds_the_run(tmp_path, env, actor):
    read_end, write_end = one_page_pipe()
    fill(write_end)  # never read
    try:
        code = execute(request(write_end), env, endpoint_side_unbuilt, diag=lambda _: None, actor_fds=actor)
    finally:
        os.close(read_end)
    assert code == 4
    (run_dir,) = runs(tmp_path)
    assert (run_dir / "disposition.json").exists()
    assert [(e["event"], e["line"]) for e in events(run_dir)] == [("report-unwritten", "run"), ("report-unwritten", "closing")]


def test_a_lease_below_the_floor_is_refused_before_anything_exists(tmp_path, env, actor):
    with pytest.raises(RunRefused) as caught:
        execute(request(lease=5.0), env, endpoint_side_unbuilt, diag=lambda _: None, actor_fds=actor)
    assert caught.value.code == "lease-below-floor"
    assert not (tmp_path / "state" / "verifiably-autonomy").exists()


def test_refused_stdio_allocates_nothing_and_writes_nothing_on_the_report_fd(tmp_path, env, actor):
    regular = os.open(tmp_path / "file", os.O_WRONLY | os.O_CREAT, 0o600)
    read_end, write_end = os.pipe()
    try:
        with pytest.raises(RunRefused) as caught:
            execute(request(write_end), env, endpoint_side_unbuilt, diag=lambda _: None,
                    actor_fds=(actor[0], actor[1], regular))
        assert drain(read_end) == b""
    finally:
        for fd in (regular, read_end, write_end):
            os.close(fd)
    assert (caught.value.code, caught.value.message) == ("stdio-refused", f"fd {regular} is a regular file")
    assert runs(tmp_path) == []


def test_a_report_fd_on_the_actors_channel_is_refused(tmp_path, env, actor):
    read_end, write_end = os.pipe()
    duplicate = os.dup(write_end)
    try:
        with pytest.raises(RunRefused) as caught:
            execute(request(duplicate), env, endpoint_side_unbuilt, diag=lambda _: None,
                    actor_fds=(actor[0], write_end, actor[2]))
    finally:
        for fd in (read_end, write_end, duplicate):
            os.close(fd)
    assert caught.value.code == "stdio-refused"


def test_an_unset_runtime_dir_is_refused(tmp_path, env, actor):  # Review Focus 5
    del env["XDG_RUNTIME_DIR"]
    with pytest.raises(RunRefused) as caught:
        execute(request(), env, endpoint_side_unbuilt, diag=lambda _: None, actor_fds=actor)
    assert caught.value.code == "runtime-dir-unset"
    assert runs(tmp_path) == []


@pytest.mark.parametrize("value", ["", "relative/state"])
def test_an_empty_or_relative_xdg_directory_is_ignored(tmp_path, env, value):  # Review Focus 5
    env["XDG_STATE_HOME"] = value
    env["XDG_CACHE_HOME"] = value
    where = places(env)
    assert where.state == tmp_path / "home" / ".local" / "state" / "verifiably-autonomy"
    assert where.cache == tmp_path / "home" / ".cache" / "verifiably-autonomy"


def test_allocate_makes_three_private_directories(tmp_path, env):
    dirs = allocate(places(env))
    assert len(dirs.run_id) == 32 and int(dirs.run_id, 16) >= 0
    assert dirs.socket_dir == tmp_path / "runtime" / "va" / dirs.run_id[:12]
    for path in (dirs.run_dir, dirs.scratch, dirs.socket_dir):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert dirs.scratch == dirs.scratch.resolve()
    assert allocate(places(env)).run_id != dirs.run_id


FINDING = Finding("baseline-unavailable", "science", "unavailable")


def test_disposition_json_is_published_once_and_never_replaced(tmp_path):
    write_disposition(tmp_path, "r1", "unwired", [FINDING])
    first = (tmp_path / "disposition.json").read_bytes()
    with pytest.raises(FileExistsError):
        write_disposition(tmp_path, "r1", "clean", [])
    assert (tmp_path / "disposition.json").read_bytes() == first
    assert stat.S_IMODE((tmp_path / "disposition.json").stat().st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["disposition.json"]  # no temporary left


def _half_then_interrupted(fd, data):
    os.write(fd, data[: len(data) // 2])
    raise KeyboardInterrupt  # an interruption mid-record, not an error


def _interrupted(*args, **kwargs):
    raise KeyboardInterrupt


@pytest.mark.parametrize(
    ("module", "name", "replacement"),
    [("autonomy.run", "write_all", _half_then_interrupted), ("os", "fsync", _interrupted), ("os", "link", _interrupted)],
)
def test_an_interrupted_disposition_publishes_nothing_and_a_retry_succeeds(tmp_path, monkeypatch, module, name, replacement):
    with monkeypatch.context() as patch:
        patch.setattr(f"{module}.{name}", replacement)
        with pytest.raises(KeyboardInterrupt):
            write_disposition(tmp_path, "r1", "unwired", [FINDING])
    assert not (tmp_path / "disposition.json").exists()
    write_disposition(tmp_path, "r1", "unwired", [FINDING])
    assert json.loads((tmp_path / "disposition.json").read_text())["disposition"] == "unwired"


def test_a_temporary_left_by_a_killed_writer_does_not_block_the_retry(tmp_path):
    (tmp_path / ".disposition.json.0123456789abcdef.tmp").write_text('{"version": 1, "run"')  # torn
    write_disposition(tmp_path, "r1", "unwired", [FINDING])
    assert json.loads((tmp_path / "disposition.json").read_text())["run"] == "r1"


def long_dir(root: Path, name: str) -> Path:
    """A valid directory path of about 2,300 bytes: nine 250-byte components."""
    path = root / name
    for digit in range(9):
        path = path / (str(digit) * 250)
    path.mkdir(parents=True)
    return path


def test_a_report_line_too_long_for_one_write_is_unwritten_and_the_run_closes(tmp_path, env, actor):  # Review Focus 4
    env["XDG_STATE_HOME"] = str(long_dir(tmp_path, "state-long"))
    env["XDG_CACHE_HOME"] = str(long_dir(tmp_path, "cache-long"))
    read_end, write_end = os.pipe()
    try:
        code = execute(request(write_end), env, endpoint_side_unbuilt, diag=lambda _: None, actor_fds=actor)
        assert read_all(read_end) == b""  # dropped whole, nothing after it, and the fd closed
    finally:
        os.close(read_end)
    assert code == 4
    (run_dir,) = (Path(env["XDG_STATE_HOME"]) / "verifiably-autonomy" / "runs").iterdir()
    assert json.loads((run_dir / "disposition.json").read_text())["disposition"] == "unwired"
    assert [(e["event"], e["line"]) for e in events(run_dir)] == [("report-unwritten", "run"), ("report-unwritten", "closing")]


def test_events_are_appended_one_line_each(tmp_path):
    append_event(tmp_path, "report-unwritten", line="run")
    append_event(tmp_path, "report-unwritten", line="closing")
    recorded = events(tmp_path)
    assert [e["line"] for e in recorded] == ["run", "closing"]
    assert all(e["at"].endswith("Z") for e in recorded)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-one tests/test_run.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.baseline'`.

- [ ] **Step 3: Implement the event log**

`python/src/autonomy/baseline.py`:

```python
"""The run directory's records (envelope design §6). This module holds `events.jsonl`
and the durable-write helpers; `baseline.json` and `seal.json` join it with the
endpoint."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

EVENTS = "events.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def append_event(run_dir: Path, event: str, **fields: object) -> None:
    """Append one line and fsync it. The file is created on first use, and its
    directory fsynced then."""
    path = run_dir / EVENTS
    created = not path.exists()
    record = {**fields, "event": event, "at": utc_now()}
    line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        write_all(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    if created:
        fsync_dir(run_dir)
```

- [ ] **Step 4: Implement the run frame**

`python/src/autonomy/run.py`:

```python
"""The run supervisor (envelope design §3): steps 1 and 2, and the close's records
(`disposition.json`, the report fd's two lines, the exit code). Steps 3 to 9 are a
`Steps` callable; until science's run endpoint exists, `endpoint_side_unbuilt` closes
every run `unwired` before any chain is read or the actor starts."""

from __future__ import annotations

import json
import os
import pwd
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from autonomy.baseline import append_event, fsync_dir, utc_now, write_all
from autonomy.channel import LineChannel
from autonomy.closing import Disposition, disposition_of
from autonomy.membership import Finding
from autonomy.stdio import ACTOR_FDS, StdioKind, StdioRefused, check_report_fd, check_stdio
from autonomy.tiers import Tier

LEASE_FLOOR = 10.0
LEASE_DEFAULT = 60.0
EXIT_REFUSED = 2
EXIT_CODES: Mapping[Disposition, int] = MappingProxyType({"clean": 0, "quarantined": 3, "unwired": 4})
DISPOSITION = "disposition.json"

Diag = Callable[[str], None]


class RunRefused(Exception):
    """A configuration refusal at step 2: exit 2, and no run directory."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RunRequest:
    tier: Tier
    lease: float
    report_fd: int | None
    actor_argv: tuple[str, ...]


@dataclass(frozen=True)
class Places:
    state: Path
    cache: Path
    runtime: Path


def _xdg(env: Mapping[str, str], name: str, fallback: Path) -> Path:
    """The XDG base directory spec: a relative or empty value is invalid and ignored."""
    value = env.get(name, "")
    return Path(value) if value and Path(value).is_absolute() else fallback


def places(env: Mapping[str, str]) -> Places:
    runtime = env.get("XDG_RUNTIME_DIR", "")
    if not runtime or not Path(runtime).is_absolute():
        raise RunRefused(
            "runtime-dir-unset", "XDG_RUNTIME_DIR must name an absolute directory: the endpoint's socket lives there"
        )
    home = Path(env.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir)
    return Places(
        state=_xdg(env, "XDG_STATE_HOME", home / ".local" / "state") / "verifiably-autonomy",
        cache=_xdg(env, "XDG_CACHE_HOME", home / ".cache") / "verifiably-autonomy",
        runtime=Path(runtime),
    )


@dataclass(frozen=True)
class RunDirs:
    run_id: str
    run_dir: Path
    scratch: Path
    socket_dir: Path


def allocate(where: Places) -> RunDirs:
    """Step 1. The socket directory's name is the run id's first 12 hex digits, short
    because of the 107-byte AF_UNIX path limit. Each directory is new: a collision
    fails rather than sharing one."""
    run_id = secrets.token_hex(16)
    run_dir = where.state / "runs" / run_id
    scratch = where.cache / "scratch" / run_id
    socket_dir = where.runtime / "va" / run_id[:12]
    for path in (run_dir, scratch, socket_dir):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.mkdir(mode=0o700)
    return RunDirs(run_id, run_dir, scratch.resolve(), socket_dir)


def refuse(request: RunRequest, *, actor_fds: tuple[int, int, int] = ACTOR_FDS) -> tuple[StdioKind, StdioKind, StdioKind]:
    """Step 2's checks that need no world. The tier is refused when it is built; the
    write-corpus and orphaned-run checks need science's reads."""
    if request.lease < LEASE_FLOOR:
        raise RunRefused("lease-below-floor", f"the lease is {request.lease:g} s; the floor is {LEASE_FLOOR:g} s")
    try:
        kinds = check_stdio(actor_fds)
        if request.report_fd is not None:
            check_report_fd(request.report_fd, actor_fds)
    except StdioRefused as caught:
        raise RunRefused(caught.code, caught.message) from None
    return kinds


@dataclass(frozen=True)
class Opened:
    request: RunRequest
    dirs: RunDirs
    stdio: tuple[StdioKind, StdioKind, StdioKind]


Steps = Callable[[Opened], Sequence[Finding]]
"""Steps 3 to 9 and the close's seal and check: everything between the report fd's
first line and `disposition.json`. Returns the run's findings."""


def endpoint_side_unbuilt(opened: Opened) -> tuple[Finding, ...]:
    """This build has no science reads and no endpoint, so step 3 cannot capture a
    baseline. The run closes `unwired` before any chain is read or the actor starts."""
    return (
        Finding(
            "baseline-unavailable",
            "science",
            "this build has no science reads or run endpoint yet; the baseline cannot be captured "
            "and the actor never starts",
        ),
    )


def write_disposition(run_dir: Path, run_id: str, disposition: Disposition, findings: Sequence[Finding]) -> None:
    """Published once and atomically, before the closing line. The record is written
    and fsynced under a temporary name in the run directory, then hard-linked to its
    final name: `link` refuses a name that exists, so a disposition is never replaced,
    and an interruption at any point leaves no `disposition.json` and lets a retry
    succeed. A writer killed outright leaves only its temporary behind. The directory
    is fsynced last."""
    record = {
        "version": 1,
        "run": run_id,
        "disposition": disposition,
        "findings": [{"code": f.code, "ref": f.ref, "message": f.message} for f in findings],
        "closed_at": utc_now(),
        "members": {},
        "closing_heads": None,
    }
    temporary = run_dir / f".{DISPOSITION}.{secrets.token_hex(8)}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        try:
            write_all(fd, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.link(temporary, run_dir / DISPOSITION)
    finally:
        temporary.unlink()
    fsync_dir(run_dir)


def _line(value: Mapping[str, object]) -> str:
    return json.dumps(value, separators=(",", ":"))


def execute(
    request: RunRequest,
    env: Mapping[str, str],
    steps: Steps,
    *,
    diag: Diag,
    actor_fds: tuple[int, int, int] = ACTOR_FDS,
) -> int:
    """Refuse (raising `RunRefused` before anything exists), allocate, report the run,
    run `steps`, then close: `disposition.json`, the closing line, the exit code. The
    report fd is closed on the way out."""
    stdio = refuse(request, actor_fds=actor_fds)
    where = places(env)
    report = None if request.report_fd is None else LineChannel(request.report_fd)
    try:
        dirs = allocate(where)
        diag(f"run {dirs.run_id} in {dirs.run_dir}")
        if report is not None and not report.write_line(
            _line({"run": dirs.run_id, "run_dir": str(dirs.run_dir), "scratch": str(dirs.scratch)})
        ):
            append_event(dirs.run_dir, "report-unwritten", line="run")
        findings = tuple(steps(Opened(request, dirs, stdio)))
        disposition = disposition_of(findings)
        code = EXIT_CODES[disposition]
        write_disposition(dirs.run_dir, dirs.run_id, disposition, findings)
        if report is not None and not report.write_line(
            _line({"run": dirs.run_id, "disposition": disposition, "exit": code})
        ):
            append_event(dirs.run_dir, "report-unwritten", line="closing")
        diag(f"run {dirs.run_id} closed {disposition}: {', '.join(f.code for f in findings) or 'no findings'}")
        return code
    finally:
        if report is not None:
            report.close()
            os.close(report.fd)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `just test-one tests/test_run.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
just test-fast
git add python/src/autonomy/baseline.py python/src/autonomy/run.py python/tests/test_run.py
git commit -m "feat(run): open and close a run: step 2 refusals, run directory, disposition and report lines"
```

---

### Task 5: The `autonomy run` CLI (E1 CLI arm, E20 through the CLI) and the docs

**Files:**
- Create: `python/src/autonomy/cli.py`, `python/src/autonomy/__main__.py`, `python/tests/test_cli.py`
- Modify: `python/pyproject.toml` (`[project.scripts]`), `docs/specs/2026-10-12-envelope-design.md` (status line, §13 item 4), `README.md` (*Documentation*)

**Interfaces:**
- Consumes: Task 4's `execute`, `RunRequest`, `RunRefused`, `EXIT_REFUSED`,
  `LEASE_DEFAULT`, `endpoint_side_unbuilt`; Task 3's `LineChannel`; Plan A's `tier`,
  `TierRefused`.
- Produces: `main(argv: Sequence[str] | None = None) -> int`; the console script
  `autonomy`; `python -m autonomy`. The surface is
  `autonomy run --tier NAME [--route KIND=FAMILY]... [--lease SECONDS] [--report-fd N] -- ACTOR...`.
  B2 adds the write corpus, network and binds.

- [ ] **Step 1: Write the failing tests**

`python/tests/test_cli.py`:

```python
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from channels import blocking, drain, fill, one_page_pipe

TESTS = Path(__file__).parent


def environment(tmp_path) -> dict[str, str]:
    for name in ("state", "cache", "runtime", "home"):
        (tmp_path / name).mkdir(exist_ok=True)
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_RUNTIME_DIR": str(tmp_path / "runtime"),
    }


def runs(tmp_path, state: Path | None = None) -> list[Path]:
    root = (state or tmp_path / "state") / "verifiably-autonomy" / "runs"
    return sorted(root.iterdir()) if root.exists() else []


def events(run_dir: Path) -> list[dict]:
    path = run_dir / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@dataclass
class Stdio:
    stdin: int
    stdout: int
    stderr: int
    pass_fds: tuple[int, ...] = ()
    prelude: str = ""
    env: dict[str, str] | None = None


def autonomy(tmp_path, args: list[str], io: Stdio, timeout: float = 30) -> tuple[int, float]:
    """Run `autonomy` in a child whose fds 0–2 are `io`'s; return its status and seconds."""
    code = "\n".join([
        "import sys",
        f"sys.path.insert(0, {str(TESTS)!r})",
        io.prelude,
        "from autonomy.cli import main",
        "raise SystemExit(main(sys.argv[1:]))",
    ])
    started = time.monotonic()
    child = subprocess.Popen(
        [sys.executable, "-c", code, *args], stdin=io.stdin, stdout=io.stdout, stderr=io.stderr,
        pass_fds=io.pass_fds, env=io.env or environment(tmp_path),
    )
    return child.wait(timeout=timeout), time.monotonic() - started


RUN = ["run", "--tier", "report-only"]
ACTOR = ["--", "/usr/bin/true"]


@pytest.fixture
def held():
    items: list = []
    yield items
    for item in items:
        if isinstance(item, socket.socket):
            item.close()
        else:
            try:
                os.close(item)
            except OSError:
                pass


@pytest.fixture
def pipes(held):
    """(stdin, stdout and stderr pipes, report pipe), each read end kept for the test."""
    null = os.open(os.devnull, os.O_RDONLY)
    out_read, out_write = os.pipe()
    err_read, err_write = os.pipe()
    report_read, report_write = os.pipe()
    held.extend([null, out_read, out_write, err_read, err_write, report_read, report_write])
    return {
        "io": Stdio(null, out_write, err_write, pass_fds=(report_write,)),
        "out": out_read, "out_write": out_write, "err": err_read,
        "report": report_read, "report_write": report_write,
    }


def test_publishes_exits_2_with_no_run_directory(tmp_path, pipes):  # E1, CLI arm
    status, _ = autonomy(tmp_path, ["run", "--tier", "publishes", *ACTOR], pipes["io"])
    assert status == 2
    assert runs(tmp_path) == []
    assert b"publishes-unattended" in drain(pipes["err"])
    assert drain(pipes["out"]) == b""


def test_a_run_closes_unwired_and_reports_it(tmp_path, pipes):
    report = pipes["report_write"]
    status, _ = autonomy(tmp_path, [*RUN, "--report-fd", str(report), *ACTOR], pipes["io"])
    assert status == 4
    first, closing = (json.loads(line) for line in drain(pipes["report"]).decode().splitlines())
    (run_dir,) = runs(tmp_path)
    assert first["run_dir"] == str(run_dir) and closing == {"run": first["run"], "disposition": "unwired", "exit": 4}
    assert json.loads((run_dir / "disposition.json").read_text())["disposition"] == "unwired"
    assert drain(pipes["out"]) == b""  # never writes stdout


def test_dev_null_and_a_socketpair_pass_step_2(tmp_path, pipes, held):
    actor_end, caller_end = socket.socketpair()
    held.extend([actor_end, caller_end])
    io = pipes["io"]
    io.stdout = actor_end.fileno()
    status, _ = autonomy(tmp_path, [*RUN, "--report-fd", str(pipes["report_write"]), *ACTOR], io)
    assert status == 4  # past step 2: this build closes at step 3
    assert drain(caller_end.fileno()) == b""


def refusal(name: str, tmp_path: Path, pipes: dict, held: list) -> tuple[Stdio, list[str], int | None, int | None]:
    """The E20 step-2 cases: (stdio, extra args, report read end to check, stderr read
    end to check). A None read end means that channel is not the test's to read."""
    io = pipes["io"]
    report = ["--report-fd", str(pipes["report_write"])]
    err = pipes["err"]
    if name == "a pty on fd 1":
        master, slave = os.openpty()
        held.extend([master, slave])
        io.stdout = slave
    elif name == "an appended log on fd 2":
        (tmp_path / "existing.log").write_bytes(b"earlier lines\n")
        io.stderr = os.open(tmp_path / "existing.log", os.O_WRONLY | os.O_APPEND)  # `2>>existing.log`
        held.append(io.stderr)
        err = None
    elif name == "/dev/zero on fd 0":
        io.stdin = os.open("/dev/zero", os.O_RDONLY)
        held.append(io.stdin)
    elif name == "a named FIFO on fd 0":
        os.mkfifo(tmp_path / "fifo")
        io.stdin = os.open(tmp_path / "fifo", os.O_RDWR)
        held.append(io.stdin)
    elif name == "an unconnected UDP socket on fd 1":
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        held.append(sock)
        io.stdout = sock.fileno()
    elif name == "an unconnected AF_UNIX stream socket on fd 0":
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        held.append(sock)
        io.stdin = sock.fileno()
    elif name == "a listening AF_UNIX socket on fd 0":
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(f"\0va-test-{os.getpid()}-{time.monotonic_ns()}")
        sock.listen()
        held.append(sock)
        io.stdin = sock.fileno()
    elif name == "a connected AF_INET socket on fd 1":
        server = socket.create_server(("127.0.0.1", 0))
        client = socket.create_connection(server.getsockname())
        held.extend([server, client])
        io.stdout = client.fileno()
    elif name == "a closed fd 0":
        io.prelude = "import os; os.close(0)"
    elif name == "a closed fd 0, with a socket on fd 2":
        # the socket path dups: a channel opened before step 2 would take fd 0
        mine, theirs = socket.socketpair()
        held.extend([mine, theirs])
        io.stderr = mine.fileno()
        err = theirs.fileno()
        io.prelude = "import os; os.close(0)"
    elif name == "--report-fd 1":
        return io, ["--report-fd", "1"], None, err
    elif name == "--report-fd 3 duplicated from fd 2":
        io.prelude = "import os; os.dup2(2, 3)"
        return io, ["--report-fd", "3"], None, err
    elif name in ("a report fd that is a tty", "a report fd that is a regular file", "a report fd that is a read end"):
        if name.endswith("tty"):
            master, fd = os.openpty()
            held.extend([master, fd])
        elif name.endswith("regular file"):
            fd = os.open(tmp_path / "report", os.O_WRONLY | os.O_CREAT, 0o600)
            held.append(fd)
        else:
            fd = pipes["report"]
        io.pass_fds = (fd,)
        return io, ["--report-fd", str(fd)], None, err
    else:
        raise AssertionError(name)
    return io, report, pipes["report"], err


REFUSALS = [
    "a pty on fd 1", "an appended log on fd 2", "/dev/zero on fd 0", "a named FIFO on fd 0",
    "an unconnected UDP socket on fd 1", "an unconnected AF_UNIX stream socket on fd 0",
    "a listening AF_UNIX socket on fd 0", "a connected AF_INET socket on fd 1",
    "a closed fd 0", "a closed fd 0, with a socket on fd 2",
    "--report-fd 1", "--report-fd 3 duplicated from fd 2", "a report fd that is a tty",
    "a report fd that is a regular file",
    "a report fd that is a read end",  # Review Focus 3
]


@pytest.mark.parametrize("name", REFUSALS)
def test_step_2_refuses_stdio_it_cannot_vouch_for(tmp_path, pipes, held, name):
    io, extra, report_read, err_read = refusal(name, tmp_path, pipes, held)
    status, _ = autonomy(tmp_path, [*RUN, *extra, *ACTOR], io)
    assert status == 2
    assert runs(tmp_path) == []
    if io.stdout == pipes["out_write"]:  # fd 1 is still the test's pipe
        assert drain(pipes["out"]) == b""
    if report_read is not None:
        assert drain(report_read) == b""
    if err_read is not None:
        assert b"stdio-refused" in drain(err_read)
    if name == "an appended log on fd 2":
        assert (tmp_path / "existing.log").read_bytes() == b"earlier lines\n"  # never overwritten, never appended


def test_a_filled_stderr_never_holds_a_refusal(tmp_path, pipes, held):
    err_read, err_write = one_page_pipe()
    held.extend([err_read, err_write])
    fill(err_write)  # never read
    io = pipes["io"]
    io.stderr = err_write
    status, seconds = autonomy(tmp_path, [*RUN, "--lease", "5", *ACTOR], io)
    assert status == 2 and seconds < 10


def test_a_full_report_pipe_never_holds_the_run(tmp_path, pipes, held):
    report_read, report_write = one_page_pipe()
    held.extend([report_read, report_write])
    fill(report_write)  # never read
    io = pipes["io"]
    io.pass_fds = (report_write,)
    status, seconds = autonomy(tmp_path, [*RUN, "--report-fd", str(report_write), *ACTOR], io)
    assert status == 4 and seconds < 10
    (run_dir,) = runs(tmp_path)
    assert [e["line"] for e in events(run_dir) if e["event"] == "report-unwritten"] == ["run", "closing"]


COMPETING = """
import autonomy.channel as channel
from channels import fill
channel._before_write = lambda fd: fill({second}) if fd == {target} else None
"""


@pytest.mark.parametrize("where", ["report pipe", "report socketpair", "stderr pipe"])
def test_a_competing_writer_after_the_poll_never_holds_the_run(tmp_path, pipes, held, where):
    io = pipes["io"]
    if where == "report socketpair":
        mine, theirs = socket.socketpair()
        held.extend([mine, theirs])
        target = mine.fileno()
    else:
        target = pipes["report_write"] if where == "report pipe" else pipes["io"].stderr
    second = os.dup(target)  # the second writer the caller holds
    held.append(second)
    io.pass_fds = (target, second) if where != "stderr pipe" else (pipes["report_write"], second)
    report = target if where != "stderr pipe" else pipes["report_write"]
    io.prelude = COMPETING.format(second=second, target=2 if where == "stderr pipe" else target)
    status, seconds = autonomy(tmp_path, [*RUN, "--report-fd", str(report), *ACTOR], io)
    assert status == 4 and seconds < 10
    assert blocking(target) and blocking(second)
    if where != "stderr pipe":
        (run_dir,) = runs(tmp_path)
        assert [e["line"] for e in events(run_dir) if e["event"] == "report-unwritten"] == ["run", "closing"]


@pytest.mark.parametrize("shell", ["bash", "zsh"])
@pytest.mark.parametrize(("pipefail", "expected"), [(True, 4), (False, 0)])
def test_the_terminal_recipe(tmp_path, shell, pipefail, expected):
    if shutil.which(shell) is None:
        pytest.skip(f"needs {shell}")
    command = shlex.join([sys.executable, "-m", "autonomy", *RUN, *ACTOR])
    recipe = f"({'set -o pipefail; ' if pipefail else ''}{command} </dev/null 2>&1 | cat -v)"
    result = subprocess.run(
        [shell, "-c", recipe], env=environment(tmp_path), stdin=subprocess.DEVNULL, capture_output=True, timeout=60
    )
    assert result.returncode == expected
    assert b"closed unwired" in result.stdout


def test_help_never_writes_stdout(tmp_path, pipes):  # Review Focus 2
    status, _ = autonomy(tmp_path, ["run", "--help"], pipes["io"])
    assert status == 0
    assert drain(pipes["out"]) == b""
    assert b"--report-fd" in drain(pipes["err"])


def test_a_usage_error_with_a_filled_stderr_still_exits_2(tmp_path, pipes, held):  # Review Focus 2
    err_read, err_write = one_page_pipe()
    held.extend([err_read, err_write])
    fill(err_write)
    io = pipes["io"]
    io.stderr = err_write
    status, seconds = autonomy(tmp_path, ["run"], io)
    assert status == 2 and seconds < 10


@pytest.mark.parametrize("lease", ["nan", "inf", "-1", "0", "soon"])
def test_a_lease_that_is_not_a_positive_number_is_a_usage_error(tmp_path, pipes, lease):
    status, _ = autonomy(tmp_path, [*RUN, "--lease", lease, *ACTOR], pipes["io"])
    assert status == 2 and runs(tmp_path) == []


def test_routes_name_a_mints_tier(tmp_path, pipes):
    status, _ = autonomy(tmp_path, ["run", "--tier", "mints", "--route", "proposition=corpus-write", *ACTOR], pipes["io"])
    assert status == 4
    status, _ = autonomy(tmp_path, ["run", "--tier", "mints", *ACTOR], pipes["io"])
    assert status == 2 and b"mints-empty" in drain(pipes["err"])


def test_an_unset_runtime_dir_exits_2(tmp_path, pipes):  # Review Focus 5
    env = environment(tmp_path)
    del env["XDG_RUNTIME_DIR"]
    io = pipes["io"]
    io.env = env
    status, _ = autonomy(tmp_path, [*RUN, *ACTOR], io)
    assert status == 2 and runs(tmp_path) == []
    assert b"runtime-dir-unset" in drain(pipes["err"])


def test_a_relative_state_home_falls_back_to_the_default(tmp_path, pipes):  # Review Focus 5
    env = environment(tmp_path)
    env["XDG_STATE_HOME"] = "relative"
    io = pipes["io"]
    io.env = env
    status, _ = autonomy(tmp_path, [*RUN, *ACTOR], io)
    assert status == 4
    assert len(runs(tmp_path, state=tmp_path / "home" / ".local" / "state")) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-one tests/test_cli.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomy.cli'` in each child.
Every status is 1, not the expected code.

- [ ] **Step 3: Implement the CLI**

`python/src/autonomy/cli.py`:

```python
"""The `autonomy` command (envelope design §3, decision 12).

`autonomy run` never reads fd 0 and never writes fd 1, help and refusals included:
both belong to the actor. Diagnostics go to fd 2 through a non-blocking channel,
truncated to one write each, and are for a person only. The record is the exit code,
the run directory and the report fd."""

from __future__ import annotations

import argparse
import functools
import math
import os
import select
from collections.abc import Callable, Sequence

from autonomy.channel import LineChannel
from autonomy.run import EXIT_REFUSED, LEASE_DEFAULT, LEASE_FLOOR, RunRefused, RunRequest, endpoint_side_unbuilt, execute
from autonomy.tiers import TierRefused, tier

Diag = Callable[[str], None]
_PREFIX = "autonomy: "


def _diagnostics() -> Diag:
    """Diagnostics on fd 2. The channel is opened at the first diagnostic, never
    before: it may open a descriptor, and one opened while fd 0 is closed would take
    number 0 and pass step 2's check. Every diagnostic a run that goes on emits
    follows step 2; one emitted earlier (a usage error, a refused tier) ends the
    process."""
    limit = select.PIPE_BUF - 1  # room for the newline
    channel: LineChannel | None = None

    def diag(message: str) -> None:
        nonlocal channel
        if channel is None:
            channel = LineChannel(2)
        for line in message.splitlines():
            data = (_PREFIX + line).encode("utf-8", "replace")[:limit]
            channel.write_line(data.decode("utf-8", "ignore"))  # a dropped diagnostic is ignored

    return diag


class _Stop(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


class _Parser(argparse.ArgumentParser):
    """argparse with every message on the diagnostic channel, help included, and no
    sys.exit."""

    def __init__(self, *args, diag: Diag, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._diag = diag

    def _print_message(self, message: str, file=None) -> None:
        if message:
            self._diag(message)

    def exit(self, status: int = 0, message: str | None = None):
        if message:
            self._diag(message)
        raise _Stop(status)


def _seconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of seconds") from None
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not a positive number of seconds")
    return value


def _fd(text: str) -> int:
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"{text!r} is not a descriptor number")
    return int(text)


def _route(text: str) -> tuple[str, str]:
    kind, sep, family = text.partition("=")
    if not sep or not kind or not family:
        raise argparse.ArgumentTypeError(f"{text!r} is not KIND=FAMILY")
    return kind, family


def _parser(diag: Diag) -> _Parser:
    parser = _Parser(prog="autonomy", description="The envelope of verifiably: what may run unattended.", diag=diag)
    commands = parser.add_subparsers(
        dest="command", required=True, parser_class=functools.partial(_Parser, diag=diag)
    )
    run = commands.add_parser(
        "run",
        help="run one actor under the envelope",
        description="Run one actor under the envelope. Exit 0 clean, 3 quarantined, 4 unwired, 2 refused.",
    )
    run.add_argument("--tier", required=True, help="report-only, coordination or mints; publishes is refused")
    run.add_argument(
        "--route", action="append", default=[], type=_route, metavar="KIND=FAMILY",
        help="a kind a mints tier may mint, and its route; repeat for each kind",
    )
    run.add_argument(
        "--lease", type=_seconds, default=LEASE_DEFAULT, metavar="SECONDS",
        help=f"the endpoint's lease (default {LEASE_DEFAULT:g}, floor {LEASE_FLOOR:g})",
    )
    run.add_argument(
        "--report-fd", type=_fd, metavar="N",
        help="an anonymous pipe or connected AF_UNIX stream socket, not fd 0-2, for the run and closing lines",
    )
    run.add_argument("actor", nargs="+", metavar="ACTOR", help="the actor's argv, after --")
    return parser


def _run(args: argparse.Namespace, diag: Diag) -> int:
    try:
        routes = dict(args.route)
        if len(routes) != len(args.route):
            raise RunRefused("route-repeated", "each kind takes one --route")
        try:
            chosen = tier(args.tier, routes or None)
        except TierRefused as caught:
            raise RunRefused(caught.code, str(caught).removeprefix(f"{caught.code}: ")) from None
        request = RunRequest(chosen, args.lease, args.report_fd, tuple(args.actor))
        return execute(request, os.environ, endpoint_side_unbuilt, diag=diag)
    except RunRefused as caught:
        diag(f"refused: {caught.code}: {caught.message}")
        return EXIT_REFUSED


def main(argv: Sequence[str] | None = None) -> int:
    diag = _diagnostics()
    try:
        args = _parser(diag).parse_args(argv)
    except _Stop as stop:
        return stop.status
    return _run(args, diag)
```

`python/src/autonomy/__main__.py`:

```python
from autonomy.cli import main

raise SystemExit(main())
```

In `python/pyproject.toml`, after `dependencies = []`:

```toml
[project.scripts]
autonomy = "autonomy.cli:main"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `just setup && just test-one tests/test_cli.py`
Expected: PASS. The bash and zsh recipe cases skip where the shell is absent.

- [ ] **Step 5: Record the split and the CLI in the docs**

In `docs/specs/2026-10-12-envelope-design.md`:

- Status line: after "Items 2–4 are open: beliefs-7a56ef, sci-a1d45f, autonomy-641123.",
  replace the item-4 id with the split: "Item 4 is split: Plan B1, the launch side that
  needs neither slice (autonomy-641123, `docs/plans/2026-10-15-envelope-plan-b1.md`),
  implemented on <the date this task lands, as YYYY-MM-DD>, and Plan B2, the endpoint
  side (autonomy-f6efe8)."
- §13 item 4: append "It is split in two. B1 needs neither slice: the gate's release
  fd, the stdio check, the non-blocking writes, `/dev/null` stdin for the preflight
  and the probe, steps 1 and 2 without the world checks, the close's records, and the
  CLI; E1's CLI arm and E20's launch arm. B2 follows 2 and 3 with the rest."

In `README.md`, replace the bullet "This repository's own designs and plans will live
under docs/ (specs and plans) once written; nothing is there today." with "This
repository's own designs and plans are under [docs/specs](docs/specs) and
[docs/plans](docs/plans); the envelope's design is
`docs/specs/2026-10-12-envelope-design.md`."

Run: `just check`
Expected: no output, exit 0.

- [ ] **Step 6: Commit**

```bash
just test-fast
git add python/src/autonomy/cli.py python/src/autonomy/__main__.py python/pyproject.toml python/tests/test_cli.py docs/specs/2026-10-12-envelope-design.md README.md
git commit -m "feat(cli): autonomy run, refusing at step 2 and closing with its disposition"
```

---

## After the last task

Run `just test` once: the full suite, including every `bwrap` test. Then hand the
branch to the final whole-branch review that the chosen execution skill prescribes.
