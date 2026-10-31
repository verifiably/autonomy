# Analyst Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `autonomy analyst` starts a fresh pi 1.1.0 analyst under the envelope's sandbox with only caller-declared read-only inputs and one output directory, enforced denial of caller-declared paths across every pi tool, and a zero-cost scripted-upstream check that proves it (envelope design decision 14, rows E23 and E24).

**Architecture:** A new package `autonomy.analyst` composes the existing pieces: `sandbox.launch` (B1), `EgressSession` (the egress plan) and pi run from hq's pinned install. Three new modules carry the new checks: `walk` (aliases of denied paths inside admitted trees), `release` (outputs leave scratch without following links) and `toolchain` (pi pin, node, the epoch record). `launch` runs decision 14's six steps and `cli` exposes it. The test fixture `FakeUpstream` gains a `script` mode that answers `/v1/messages` with scripted `tool_use` turns, which is what makes row E24 cost nothing.

**Tech Stack:** Python 3.11+ standard library only (no new dependency), bubblewrap, pytest with the existing `bwrap` marker and a new `pi` marker.

**Spec:** `docs/specs/2026-10-12-envelope-design.md`, decision 14 (from the heading `14. **A caller may declare`), the `**The walk**` paragraph in §7, rows E23 and E24 in §12, §13 item 6 and the last four §14 bullets. Approved at `5c5c423b09c58b0751c3ca87ad3cac6364933eac`. The pinned contract and the check recipe it adopts are in hq's `docs/notes/2026-10-15-headless-workers-brief.md` at hq `fd1468b`, section *Analyst launch qualification*; where the plan and the brief differ (the grep glob), the spec's text wins.

## Global Constraints

- No kernel import; this layer never imports `beliefs` (AGENTS.md).
- Standard library only: no `ctypes` syscalls for `statx` or `openat2` (decision 14: `mountinfo` plus `st_dev`; per-component `O_NOFOLLOW` opens).
- `PI_VERSION = "1.1.0"`; `ANALYST_TOOLS = ("read", "bash", "grep", "find", "ls", "write")`, a constant, never a flag.
- pi's fixed argv: `<pi>/node_modules/.bin/pi --mode rpc --provider anthropic --model MODEL --thinking off --session-dir <scratch>/sessions --no-approve --no-extensions --no-skills --no-prompt-templates --no-mcp --no-context-files --tools read,bash,grep,find,ls,write`.
- The actor's environment: `PATH=<node>/bin:/usr/bin`, `HOME=<scratch>/home`, `PI_CODING_AGENT_DIR=<scratch>/agent`, `PI_OFFLINE=1`, `PI_TELEMETRY=0`, `LANG=C.UTF-8`, `VERIFIABLY_MODEL_URL=http://127.0.0.1:4780`.
- `agent/models.json` is `{"providers": {"anthropic": {"baseUrl": "http://127.0.0.1:4780", "apiKey": "placeholder"}}}`.
- Denied set = caller's `--deny` real paths + `egress_denied(config, route)` + `<state>` + the release directory's real path.
- Run directory `<state>/analyst/<run-id>/`; scratch `<cache>/analyst/<run-id>/scratch/` with `agent/`, `agent/bin/`, `home/`, `sessions/`, `outputs/`; `<state>`, `<cache>`, `<config>` resolve as `run.places` does, but `$XDG_RUNTIME_DIR` is not required.
- Exit codes: 0 clean; 2 refused at step 1 (nothing kept); 3 `released-with-findings` (pi exited non-zero, the route closed other than `close` with no finding, or a release refusal); 4 the actor never started (step 3 or 4 failed; run directory kept).
- Order before launch: preflight, static check, walk, probe. Nothing is cached.
- Hard-link rule applies to inputs, node and pi only; mount and inode rules apply to every tree, `/usr` and `/etc` included.
- The E24 grep glob is `!{proc,etc,usr,dev}`; the fixture sits under no directory named `proc`, `etc`, `usr` or `dev`; no sentinel appears literally in any tool input (pattern `abcd[e]fgh` for `abcdefgh`).
- Every test that starts a subprocess builds its environment key by key (`PATH`, a temporary `HOME`, `XDG_*` under `tmp_path`); never `os.environ` or a copy.
- Test routes live under a temporary `XDG_CONFIG_HOME`, never the user's; credentials are placeholders written with `write_credential`.
- Tests run through `just test-one <path>`; the hooks run hygiene. The project's `.tt.toml` turns the broad suites off, so each task's evidence is its focused run.

## Review Focus

Inputs the spec implies but no acceptance row names, most likely to bite first:

1. **An input or denied path given with a trailing slash, as a relative path, or through `..`.** A caller passes `./bundle/` or `../data`. Resolution must give the same real path as `bundle`; a relative `--deny` must resolve against the launcher's cwd, never be compared as text. Test added to Task 5 (`test_relative_and_trailing_slash_paths_resolve`).
2. **A denied path that is a file, not a directory** (the key file itself). Inode collection must take the file's own `(st_dev, st_ino)` and not try to list it. Test added to Task 2 (`test_a_denied_file_contributes_its_own_inode`).
3. **An output name that collides with a release-directory entry created mid-release, or a huge outputs tree.** The release directory is empty at step 1; nothing else writes it; `O_EXCL` on each created file turns a collision into a refusal, not an overwrite. Test added to Task 3 (`test_a_release_never_overwrites`).
4. **The caller closes fd 0 before pi has started, or pi exits before the proxy's `listening`.** The launch must not hang and must still close the route and release. Test added to Task 5 (`test_an_actor_that_exits_at_once_still_closes_and_releases`).
5. **`/proc/self/mountinfo` with spaces or newlines in a mount point** (a Dropbox or removable path with a space). Unescaping is `\040`, `\011`, `\012`, `\134`; a path with a space under the input root must still be seen. Test added to Task 2 (`test_mountinfo_unescapes_octal_sequences`).

---

### Task 1: Toolchain checks and the epoch record

**Files:**
- Create: `python/src/autonomy/analyst/__init__.py` (empty)
- Create: `python/src/autonomy/analyst/toolchain.py`
- Test: `python/tests/test_analyst_toolchain.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `PI_VERSION: str = "1.1.0"`, `ANALYST_TOOLS: tuple[str, ...] = ("read", "bash", "grep", "find", "ls", "write")`, `TOOLS_SHADOWED: tuple[str, ...] = ("rg", "fd")`.
  - `class AnalystRefused(Exception)` with `code: str`, `message: str` (constructor `(code, message)`, `str()` is `f"{code}: {message}"`), the step-1 refusal type every later task raises.
  - `@dataclass(frozen=True) class PiInstall: dir: Path; version: str; lock_sha256: str; executable: Path` where `executable = dir / "node_modules/.bin/pi"`.
  - `check_pi(pi_dir: Path) -> PiInstall`: refuses `pi-mismatch` when `node_modules/.bin/pi` is missing or not executable, when `package-lock.json` is missing or unparsable, or when its `packages["node_modules/@earendil-works/pi-coding-agent"]["version"]` is not `PI_VERSION`.
  - `check_node(node_dir: Path) -> Path`: returns `node_dir.resolve()`; refuses `node-missing` when `bin/node` is absent or not executable, and `toolchain-shadowed` when `bin/` holds any entry named in `TOOLS_SHADOWED` (by name, `lstat`, link or file alike).
  - `default_pi_dir(env: Mapping[str, str], home: Path) -> Path`: `PI_DIR` when absolute, else `home / ".local/share/pi" / PI_VERSION`.
  - `default_node_dir(env: Mapping[str, str], which=shutil.which) -> Path | None`: `NODE_DIR` when absolute, else the prefix (two parents) of the resolved `node` on PATH, else None.
  - `epoch_record(pi: PiInstall, node_dir: Path, *, run=subprocess.run) -> dict`: `{"pi": {"version", "lock_sha256"}, "node": "<node --version>", "bwrap": "<bwrap --version>", "rg": "<rg --version first line>", "fd": "<fd --version>"}`; each version is the trimmed first line of stdout of `[<node_dir>/bin/node, "--version"]`, `["bwrap", "--version"]`, `["/usr/bin/rg", "--version"]`, `["/usr/bin/fd", "--version"]`, run with `stdin=DEVNULL`, `timeout=10`, an environment of `{"PATH": "/usr/bin"}` only; a tool that is missing or fails records `null` for that key, never raises (the record is evidence, not a gate).

- [ ] **Step 1: Write the failing tests**

```python
# python/tests/test_analyst_toolchain.py
import json, os, stat
import pytest
from autonomy.analyst.toolchain import (
    ANALYST_TOOLS, PI_VERSION, AnalystRefused, check_node, check_pi, default_node_dir, default_pi_dir, epoch_record,
)

def pi_tree(root, version=PI_VERSION, executable=True):
    (root / "node_modules/.bin").mkdir(parents=True)
    pi = root / "node_modules/.bin/pi"
    pi.write_text("#!/bin/sh\n")
    if executable:
        pi.chmod(0o755)
    lock = {"packages": {"node_modules/@earendil-works/pi-coding-agent": {"version": version}}}
    (root / "package-lock.json").write_text(json.dumps(lock))
    return root

def node_tree(root, extra=()):
    (root / "bin").mkdir(parents=True)
    (root / "bin/node").write_text("#!/bin/sh\n"); (root / "bin/node").chmod(0o755)
    for name in extra:
        (root / "bin" / name).write_text("")
    return root

def test_the_tool_list_is_the_checked_set():
    assert ANALYST_TOOLS == ("read", "bash", "grep", "find", "ls", "write")

def test_a_pinned_install_passes(tmp_path):
    install = check_pi(pi_tree(tmp_path))
    assert install.version == PI_VERSION and install.executable == tmp_path / "node_modules/.bin/pi"
    assert len(install.lock_sha256) == 64

@pytest.mark.parametrize("make", [
    lambda r: pi_tree(r, version="1.2.0"),
    lambda r: pi_tree(r, executable=False),
    lambda r: (pi_tree(r), (r / "package-lock.json").unlink())[0],
    lambda r: (pi_tree(r), (r / "package-lock.json").write_text("{"))[0],
    lambda r: r,
])
def test_anything_but_the_pin_is_pi_mismatch(tmp_path, make):
    make(tmp_path)
    with pytest.raises(AnalystRefused) as caught:
        check_pi(tmp_path)
    assert caught.value.code == "pi-mismatch"

def test_node_passes_and_resolves(tmp_path):
    link = tmp_path / "link"; link.symlink_to(node_tree(tmp_path / "real"))
    assert check_node(link) == (tmp_path / "real").resolve()

def test_a_node_tree_without_node_is_refused(tmp_path):
    (tmp_path / "bin").mkdir()
    with pytest.raises(AnalystRefused) as caught:
        check_node(tmp_path)
    assert caught.value.code == "node-missing"

@pytest.mark.parametrize("shadow", ["rg", "fd"])
def test_a_shadowing_rg_or_fd_in_node_bin_is_refused(tmp_path, shadow):
    with pytest.raises(AnalystRefused) as caught:
        check_node(node_tree(tmp_path, extra=(shadow,)))
    assert caught.value.code == "toolchain-shadowed" and shadow in caught.value.message

def test_default_dirs(tmp_path):
    assert default_pi_dir({}, tmp_path) == tmp_path / ".local/share/pi" / PI_VERSION
    assert default_pi_dir({"PI_DIR": "/x"}, tmp_path) == Path("/x")
    assert default_pi_dir({"PI_DIR": "rel"}, tmp_path) == tmp_path / ".local/share/pi" / PI_VERSION
    assert default_node_dir({"NODE_DIR": "/n"}) == Path("/n")
    assert default_node_dir({}, which=lambda _: None) is None
    assert default_node_dir({}, which=lambda _: str(tmp_path / "p/bin/node")) == tmp_path / "p"

def test_the_epoch_record_names_every_tool_and_tolerates_a_missing_one(tmp_path):
    install = check_pi(pi_tree(tmp_path / "pi"))
    calls = []
    def fake_run(argv, **kw):
        calls.append((tuple(argv), kw["env"]))
        if argv[0].endswith("fd"):
            raise FileNotFoundError(argv[0])
        return subprocess.CompletedProcess(argv, 0, stdout=f"{argv[0]} 9.9\nignored\n", stderr="")
    record = epoch_record(install, tmp_path / "node", run=fake_run)
    assert record["pi"] == {"version": PI_VERSION, "lock_sha256": install.lock_sha256}
    assert record["node"].endswith("9.9") and record["bwrap"].endswith("9.9") and record["rg"].endswith("9.9")
    assert record["fd"] is None
    assert all(env == {"PATH": "/usr/bin"} for _, env in calls)
```

(`Path` and `subprocess` are imported at the top of the test module.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-one tests/test_analyst_toolchain.py`
Expected: FAIL with `ModuleNotFoundError: autonomy.analyst`

- [ ] **Step 3: Implement `python/src/autonomy/analyst/toolchain.py`**

Module docstring cites decision 14's step 1. `check_pi` reads `package-lock.json` as bytes once, hashes those bytes (`hashlib.sha256`) and parses them; every failure path raises `AnalystRefused("pi-mismatch", ...)` with the reason (missing executable, missing or unparsable lock, version `X` where `PI_VERSION` is expected). `check_node` lists `bin/` with `os.scandir` and refuses on the first name in `TOOLS_SHADOWED`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `just test-one tests/test_analyst_toolchain.py`
Expected: PASS, 13 tests.

- [ ] **Step 5: Commit**

```bash
git add python/src/autonomy/analyst/__init__.py python/src/autonomy/analyst/toolchain.py python/tests/test_analyst_toolchain.py
git commit -m "feat(analyst): pin and toolchain checks, the epoch record (decision 14 step 1)"
```

---

### Task 2: The walk

**Files:**
- Create: `python/src/autonomy/analyst/walk.py`
- Test: `python/tests/test_analyst_walk.py`

**Interfaces:**
- Consumes: `SandboxUnproven` from `autonomy.sandbox.static` (the refusal type; a walk failure is a step-3 failure, exit 4, like the static check and the probe).
- Produces:
  - `Inode = tuple[int, int]`.
  - `collect_denied_inodes(denied: Iterable[Path]) -> frozenset[Inode]`: for each denied path that exists (`lstat`), its own identity and, for a directory, every entry's identity recursively, following no symlink; a directory that cannot be listed (`PermissionError` from `scandir`) raises `SandboxUnproven("denied-unlistable", path, ...)`; a missing path is skipped.
  - `mount_points(mountinfo: Path = Path("/proc/self/mountinfo")) -> tuple[Path, ...]`: field 5 of every line, with `\040`, `\011`, `\012` and `\134` unescaped (`unescape_mountinfo(text: str) -> str` is a module function).
  - `@dataclass(frozen=True) class TreeRule: hardlinks: bool` and `@dataclass class TreeReport: root: str; rules: list[str]; entries: int; skipped: list[str]; seconds: float`.
  - `walk_tree(root: Path, denied_inodes: frozenset[Inode], *, hardlinks: bool, mounts: tuple[Path, ...]) -> TreeReport`: `root` is already real. Refuses, in this order of checking per entry, `walk-submount` (any mount point `m` with `m != root and m.is_relative_to(root)`, checked once before the walk, and any entry whose `st_dev != root's st_dev`), `walk-hardlink` (`S_ISREG and st_nlink > 1`, only when `hardlinks`), `walk-alias` (`(st_dev, st_ino) in denied_inodes`, directories included, the root included). A directory the walker can neither list nor search (`os.access(d, R_OK | X_OK)` false and `scandir` raises `PermissionError`) is skipped and recorded in `skipped`; one that `os.access(d, X_OK)` allows but `scandir` refuses raises `walk-unlistable`. Uses `os.scandir` with `follow_symlinks=False` and `entry.stat(follow_symlinks=False)`.
  - `@dataclass class WalkReport: trees: list[TreeReport]; denied_inodes: int; seconds: float` with `to_json() -> dict`.
  - `walk(user_trees: Iterable[Path], system_trees: Iterable[Path], denied: Iterable[Path]) -> WalkReport`: collects the denied inodes, reads the mount points once, walks each user tree with `hardlinks=True` and each system tree with `hardlinks=False`.

- [ ] **Step 1: Write the failing unit tests**

```python
# python/tests/test_analyst_walk.py
import os, socket
from pathlib import Path
import pytest
from autonomy.analyst.walk import collect_denied_inodes, mount_points, unescape_mountinfo, walk, walk_tree
from autonomy.sandbox.static import SandboxUnproven

MOUNTINFO = (
    "36 25 0:32 / /mnt/with\\040space rw,relatime - tmpfs tmpfs rw\n"
    "37 25 8:1 /sub /mnt/bind\\011tab rw - ext4 /dev/sda1 rw\n"
)

def test_mountinfo_unescapes_octal_sequences(tmp_path):  # Review Focus 5
    assert unescape_mountinfo("a\\040b\\011c\\012d\\134e") == "a b\tc\nd\\e"
    info = tmp_path / "mountinfo"; info.write_text(MOUNTINFO)
    assert mount_points(info) == (Path("/mnt/with space"), Path("/mnt/bind\ttab"))

def test_a_clean_tree_passes_and_is_counted(tmp_path):
    (tmp_path / "in/a").mkdir(parents=True); (tmp_path / "in/a/f").write_text("x")
    report = walk_tree(tmp_path / "in", frozenset(), hardlinks=True, mounts=())
    assert report.entries == 2 and report.skipped == []

def test_a_hard_link_to_a_denied_file_is_refused_as_hardlink(tmp_path):
    (tmp_path / "in").mkdir(); (tmp_path / "key").mkdir(); (tmp_path / "key/k").write_text("s")
    os.link(tmp_path / "key/k", tmp_path / "in/k2")
    with pytest.raises(SandboxUnproven) as caught:
        walk([tmp_path / "in"], [], [tmp_path / "key"])
    assert caught.value.code == "walk-hardlink"

def test_a_hard_linked_file_in_a_system_tree_passes_but_an_alias_does_not(tmp_path):
    (tmp_path / "sys").mkdir(); (tmp_path / "sys/a").write_text("x"); os.link(tmp_path / "sys/a", tmp_path / "sys/b")
    walk([], [tmp_path / "sys"], [])  # packaging hard links are fine in /usr and /etc
    (tmp_path / "key").mkdir(); (tmp_path / "key/k").write_text("s"); os.link(tmp_path / "key/k", tmp_path / "sys/k")
    with pytest.raises(SandboxUnproven) as caught:
        walk([], [tmp_path / "sys"], [tmp_path / "key"])
    assert caught.value.code == "walk-alias"

def test_a_symlink_to_a_denied_file_passes(tmp_path):
    (tmp_path / "in").mkdir(); (tmp_path / "key").mkdir(); (tmp_path / "key/k").write_text("s")
    (tmp_path / "in/link").symlink_to(tmp_path / "key/k")
    walk([tmp_path / "in"], [], [tmp_path / "key"])

def test_a_denied_file_contributes_its_own_inode(tmp_path):  # Review Focus 2
    (tmp_path / "in").mkdir(); key = tmp_path / "key.json"; key.write_text("s")
    assert collect_denied_inodes([key]) == frozenset({(key.stat().st_dev, key.stat().st_ino)})
    os.link(key, tmp_path / "in/alias")
    with pytest.raises(SandboxUnproven) as caught:
        walk([], [tmp_path / "in"], [key])  # as a system tree, so the alias rule fires, not hardlink
    assert caught.value.code == "walk-alias"

def test_a_missing_denied_path_is_skipped(tmp_path):
    assert collect_denied_inodes([tmp_path / "absent"]) == frozenset()

@pytest.mark.skipif(os.getuid() == 0, reason="root ignores directory modes")
def test_an_unlistable_denied_directory_is_refused(tmp_path):
    d = tmp_path / "key/private"; d.mkdir(parents=True); (d / "k").write_text("s"); d.chmod(0o000)
    try:
        with pytest.raises(SandboxUnproven) as caught:
            collect_denied_inodes([tmp_path / "key"])
        assert caught.value.code == "denied-unlistable"
    finally:
        d.chmod(0o700)

@pytest.mark.skipif(os.getuid() == 0, reason="root ignores directory modes")
def test_search_without_list_fails_and_neither_is_skipped(tmp_path):
    (tmp_path / "in").mkdir()
    only_x = tmp_path / "in/x"; only_x.mkdir(); only_x.chmod(0o100)
    try:
        with pytest.raises(SandboxUnproven) as caught:
            walk_tree(tmp_path / "in", frozenset(), hardlinks=True, mounts=())
        assert caught.value.code == "walk-unlistable"
    finally:
        only_x.chmod(0o700)
    neither = tmp_path / "in/n"; neither.mkdir(); neither.chmod(0o000); only_x.rmdir()
    try:
        report = walk_tree(tmp_path / "in", frozenset(), hardlinks=True, mounts=())
        assert report.skipped == [str(neither)]
    finally:
        neither.chmod(0o700)

def test_a_mount_point_below_the_root_is_refused_before_walking(tmp_path):
    (tmp_path / "in/sub").mkdir(parents=True)
    with pytest.raises(SandboxUnproven) as caught:
        walk_tree(tmp_path / "in", frozenset(), hardlinks=True, mounts=(tmp_path / "in/sub",))
    assert caught.value.code == "walk-submount"
    walk_tree(tmp_path / "in", frozenset(), hardlinks=True, mounts=(tmp_path / "in",))  # the root itself may be one

def test_the_report_is_json(tmp_path):
    (tmp_path / "in").mkdir()
    report = walk(user_trees=[tmp_path / "in"], system_trees=[], denied=[])
    data = report.to_json()
    assert data["trees"][0]["rules"] == ["submount", "hardlink", "alias"] and data["denied_inodes"] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-one tests/test_analyst_walk.py`
Expected: FAIL with `ModuleNotFoundError: autonomy.analyst.walk`

- [ ] **Step 3: Implement `python/src/autonomy/analyst/walk.py`**

Iterative walk with an explicit stack (an input tree can be deep). The `st_dev` rule compares every entry's `st_dev` to the root's; the `mounts` rule runs once before the stack starts. `TreeReport.rules` is `["submount", "hardlink", "alias"]` or `["submount", "alias"]`. `to_json` returns plain dicts and lists only.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `just test-one tests/test_analyst_walk.py`
Expected: PASS, 11 tests.

- [ ] **Step 5: Write the failing namespace tests (E23's submount arms)**

The walk runs inside a `bwrap` namespace the test builds, because a same-filesystem bind needs a mount namespace. The namespace binds the package source and `tmp_path` and runs `/usr/bin/python3 -I -c` with the package directory inserted on `sys.path` from argv.

```python
# python/tests/test_analyst_walk.py (append)
import json, subprocess, sys
import autonomy

bwrap = pytest.mark.bwrap
PACKAGE_PARENT = str(Path(autonomy.__file__).resolve().parent.parent)
SNIPPET = """
import json, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from autonomy.analyst.walk import walk
from autonomy.sandbox.static import SandboxUnproven
try:
    walk([Path(sys.argv[2])], [], [])
    print(json.dumps({"ok": True}))
except SandboxUnproven as caught:
    print(json.dumps({"ok": False, "code": caught.code}))
"""

def walk_in_namespace(tmp_path, *mount_args):
    (tmp_path / "in/sub").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sibling").mkdir(exist_ok=True)
    argv = ["bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib64",
            "--symlink", "usr/lib", "/lib", "--symlink", "usr/bin", "/bin", "--proc", "/proc",
            "--ro-bind", PACKAGE_PARENT, PACKAGE_PARENT, "--bind", str(tmp_path), str(tmp_path), *mount_args,
            "--", "/usr/bin/python3", "-I", "-c", SNIPPET, PACKAGE_PARENT, str(tmp_path / "in")]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL, env={"PATH": "/usr/bin"})
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)

@bwrap
def test_a_same_filesystem_bind_below_the_root_is_refused(tmp_path):
    verdict = walk_in_namespace(tmp_path, "--bind", str(tmp_path / "sibling"), str(tmp_path / "in/sub"))
    assert verdict == {"ok": False, "code": "walk-submount"}

@bwrap
def test_a_tmpfs_below_the_root_is_refused(tmp_path):
    verdict = walk_in_namespace(tmp_path, "--tmpfs", str(tmp_path / "in/sub"))
    assert verdict == {"ok": False, "code": "walk-submount"}

@bwrap
def test_without_a_plant_the_namespace_walk_passes(tmp_path):
    assert walk_in_namespace(tmp_path) == {"ok": True}
```

The merged-/usr links in `argv` must mirror the host: use `system_symlinks()` from `autonomy.sandbox.static` to build them instead of the literal four shown, as `preflight` does.

- [ ] **Step 6: Run the namespace tests to verify they fail**

Run: `just test-one tests/test_analyst_walk.py -k namespace_or_below`
Expected: the same-filesystem case FAILS if the implementation compares `st_dev` only (it passes the plant); fix in the next step. If all three already pass, record that in the commit message and go on.

- [ ] **Step 7: Make the namespace tests pass**

Run: `just test-one tests/test_analyst_walk.py`
Expected: PASS, 14 tests.

- [ ] **Step 8: Commit**

```bash
git add python/src/autonomy/analyst/walk.py python/tests/test_analyst_walk.py
git commit -m "feat(analyst): the pre-launch alias walk (decision 14, row E23)"
```

---

### Task 3: The release

**Files:**
- Create: `python/src/autonomy/analyst/release.py`
- Test: `python/tests/test_analyst_release.py`

**Interfaces:**
- Consumes: `AnalystRefused` from Task 1.
- Produces:
  - `check_release_dir(path: Path, *, forbidden: Iterable[Path]) -> Path`: returns the real path; refuses `release-unusable` when missing, not a directory, a symlink, non-empty, or when its real path is, is under, or contains any `forbidden` real path (the inputs, scratch, the denied set).
  - `@dataclass class ReleaseReport: released: list[dict]; refused: list[dict]` where a released entry is `{"path": "<relative>", "size": int, "sha256": str}` and a refused one `{"path": "<relative>", "reason": str}` with reasons `symlink`, `fifo`, `socket`, `device`, `hardlinked`, `collision`, `unopenable`; `to_json() -> dict`.
  - `release(outputs: Path, destination: Path) -> ReleaseReport`: opens `outputs` with `os.open(outputs, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)` (the one absolute open; `outputs` is under scratch, which the launcher made), then walks by `dir_fd`: `os.scandir(dir_fd)` for entries, `os.open(name, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC, dir_fd=parent_fd)` for each entry, `os.fstat` on the result; a directory (`S_ISDIR`) is created at the destination with `os.mkdir(name, 0o700, dir_fd=dest_fd)` and descended with both fds; a regular file with `st_nlink == 1` is created at the destination with `os.open(name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600, dir_fd=dest_fd)` and copied with `os.copy_file_range` in a loop, falling back to `os.read`/`os.write` when it raises `OSError` (EXDEV, ENOSYS) on the first call, hashing the bytes as they are read (`hashlib.sha256` over the chunks when falling back; after `copy_file_range`, by re-reading the destination through its own fd from offset 0); `S_ISLNK` can only come from `ELOOP` on the open, which is recorded as `symlink`; everything else refused with its reason. A `FileExistsError` at the destination is `collision`. Every opened descriptor is closed in `finally`.

- [ ] **Step 1: Write the failing tests**

```python
# python/tests/test_analyst_release.py
import hashlib, os, socket, stat, time
from pathlib import Path
import pytest
from autonomy.analyst.release import check_release_dir, release
from autonomy.analyst.toolchain import AnalystRefused

def outputs_with(tmp_path, plant):
    out = tmp_path / "scratch/outputs"; out.mkdir(parents=True)
    (out / "result.txt").write_text("result\n")
    (out / "figs").mkdir(); (out / "figs/a.svg").write_text("<svg/>")
    plant(out)
    dest = tmp_path / "release"; dest.mkdir()
    return out, dest

def test_regular_files_and_directories_are_released_with_hashes(tmp_path):
    out, dest = outputs_with(tmp_path, lambda o: None)
    report = release(out, dest)
    assert sorted(e["path"] for e in report.released) == ["figs/a.svg", "result.txt"]
    assert (dest / "figs/a.svg").read_text() == "<svg/>" and stat.S_IMODE((dest / "figs").stat().st_mode) == 0o700
    entry = next(e for e in report.released if e["path"] == "result.txt")
    assert entry["sha256"] == hashlib.sha256(b"result\n").hexdigest() and entry["size"] == 7
    assert report.refused == []

def test_a_symlink_to_a_host_file_is_refused_and_never_read(tmp_path):
    secret = tmp_path / "secret"; secret.write_text("K")
    out, dest = outputs_with(tmp_path, lambda o: (o / "link").symlink_to(secret))
    before = secret.stat().st_atime_ns
    report = release(out, dest)
    assert {"path": "link", "reason": "symlink"} in report.refused and not (dest / "link").exists()
    assert not any("K" in p.read_text() for p in dest.rglob("*") if p.is_file())

def test_a_fifo_does_not_stall_and_is_refused(tmp_path):
    out, dest = outputs_with(tmp_path, lambda o: os.mkfifo(o / "pipe"))
    start = time.monotonic()
    report = release(out, dest)
    assert time.monotonic() - start < 5 and {"path": "pipe", "reason": "fifo"} in report.refused

def test_a_hard_linked_file_and_a_socket_are_refused(tmp_path):
    def plant(o):
        os.link(o / "result.txt", o / "twin")
        s = socket.socket(socket.AF_UNIX); s.bind(str(o / "sock")); s.close()
    out, dest = outputs_with(tmp_path, plant)
    report = release(out, dest)
    reasons = {e["path"]: e["reason"] for e in report.refused}
    assert reasons == {"twin": "hardlinked", "result.txt": "hardlinked", "sock": "socket"}

def test_a_release_never_overwrites(tmp_path):  # Review Focus 3
    out, dest = outputs_with(tmp_path, lambda o: None)
    (dest / "result.txt").write_text("already here")
    report = release(out, dest)
    assert {"path": "result.txt", "reason": "collision"} in report.refused
    assert (dest / "result.txt").read_text() == "already here"

def test_the_report_is_json(tmp_path):
    out, dest = outputs_with(tmp_path, lambda o: None)
    data = release(out, dest).to_json()
    assert set(data) == {"released", "refused"}

@pytest.mark.parametrize("make", [
    lambda t: t / "absent",
    lambda t: (t / "file").write_text("") or t / "file",
    lambda t: ((t / "full").mkdir(), (t / "full/x").write_text(""))[0] or t / "full",
    lambda t: ((t / "real").mkdir(), (t / "lnk").symlink_to(t / "real"))[0] or t / "lnk",
])
def test_an_unusable_release_directory_is_refused(tmp_path, make):
    with pytest.raises(AnalystRefused) as caught:
        check_release_dir(make(tmp_path), forbidden=())
    assert caught.value.code == "release-unusable"

def test_a_release_directory_inside_or_around_a_forbidden_path_is_refused(tmp_path):
    (tmp_path / "in/rel").mkdir(parents=True); (tmp_path / "rel2").mkdir()
    for candidate, forbidden in ((tmp_path / "in/rel", tmp_path / "in"), (tmp_path, tmp_path / "rel2")):
        with pytest.raises(AnalystRefused) as caught:
            check_release_dir(candidate, forbidden=[forbidden])
        assert caught.value.code == "release-unusable"
    assert check_release_dir(tmp_path / "rel2", forbidden=[tmp_path / "in"]) == (tmp_path / "rel2").resolve()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-one tests/test_analyst_release.py`
Expected: FAIL with `ModuleNotFoundError: autonomy.analyst.release`

- [ ] **Step 3: Implement `python/src/autonomy/analyst/release.py`**

Recursive helper `_release_dir(src_fd: int, dest_fd: int, prefix: str, report: ReleaseReport)`. Relative paths in the report use `/` joins of entry names. The hard-link rule marks both names of a linked pair, since each has `st_nlink == 2`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `just test-one tests/test_analyst_release.py`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add python/src/autonomy/analyst/release.py python/tests/test_analyst_release.py
git commit -m "feat(analyst): the no-follow output release (decision 14, row E23)"
```

---

### Task 4: The scripted upstream

**Files:**
- Modify: `python/tests/egress_fixtures.py` (`FakeUpstream`: a `script` mode)
- Test: `python/tests/test_egress_fixtures_script.py`

**Interfaces:**
- Consumes: `FakeUpstream`, `Tls`, `tls` fixture.
- Produces, in `egress_fixtures.py`:
  - `@dataclass(frozen=True) class ToolTurn: name: str; input: dict` and `@dataclass(frozen=True) class TextTurn: text: str`; `Turn = ToolTurn | TextTurn`.
  - `FakeUpstream.script: list[Turn]` (set by the test after construction, `mode="script"`); each `/v1/messages` request consumes the next turn; when the list is exhausted, the answer is `TextTurn("done")`. A turn's SSE stream is the Anthropic Messages shape pi's SDK parses: `message_start` (`{"type":"message","id":"msg_<n>","role":"assistant","model":<request's model>,"content":[],"stop_reason":null,"usage":{"input_tokens":1,"output_tokens":1}}`), `content_block_start` (`tool_use` with `id` `toolu_<n>`, `name`, `input: {}`; or `text` with `text: ""`), one `content_block_delta` (`input_json_delta` with `partial_json` = the input as JSON; or `text_delta`), `content_block_stop`, `message_delta` (`stop_reason` `tool_use` or `end_turn`, `usage.output_tokens` 1), `message_stop`; each event as `event: <type>\ndata: <json>\n\n` in one chunk, chunked transfer encoding, `content-type: text/event-stream`.
  - `FakeUpstream.tool_results() -> list[dict]`: every `tool_result` block found in the `messages` of every recorded request body (parsed as JSON), in request order, each `{"tool_use_id", "content", "is_error"}` with `content` flattened to the concatenated text of its text blocks (or the string itself).
  - `FakeUpstream.tool_uses: list[tuple[str, ToolTurn]]`: `(tool_use_id, turn)` for each tool turn served, so a result can be matched to the turn that asked for it.

- [ ] **Step 1: Write the failing test**

```python
# python/tests/test_egress_fixtures_script.py
import json, socket, ssl
from egress_fixtures import FakeUpstream, TextTurn, ToolTurn, message, tls

def _post(upstream, cert, body: dict) -> bytes:
    context = ssl.create_default_context(cafile=str(cert))
    with socket.create_connection(("127.0.0.1", upstream.port), timeout=10) as raw, context.wrap_socket(raw, server_hostname="localhost") as conn:
        data = json.dumps(body).encode()
        conn.sendall(b"POST /v1/messages?beta=true HTTP/1.1\r\nhost: localhost\r\ncontent-type: application/json\r\n"
                     b"content-length: %d\r\n\r\n" % len(data) + data)
        received = b""
        while chunk := conn.recv(65536):
            received += chunk
    return received

def events_of(answer: bytes) -> list[dict]:
    body = answer.split(b"\r\n\r\n", 1)[1]
    # decode chunked framing, then parse "data:" lines
    out, rest = b"", body
    while rest:
        size, _, rest = rest.partition(b"\r\n")
        n = int(size, 16)
        if n == 0:
            break
        out += rest[:n]; rest = rest[n + 2:]
    return [json.loads(line[6:]) for line in out.split(b"\n") if line.startswith(b"data: ")]

def test_a_tool_turn_streams_a_tool_use_and_records_the_result(tls):
    upstream = FakeUpstream(tls, mode="script")
    upstream.script = [ToolTurn("read", {"path": "/x"}), TextTurn("done")]
    try:
        events = events_of(_post(upstream, tls.cert, message()))
        assert [e["type"] for e in events] == ["message_start", "content_block_start", "content_block_delta",
                                               "content_block_stop", "message_delta", "message_stop"]
        assert events[1]["content_block"]["name"] == "read" and json.loads(events[2]["delta"]["partial_json"]) == {"path": "/x"}
        assert events[4]["delta"]["stop_reason"] == "tool_use"
        tool_use_id = events[1]["content_block"]["id"]
        follow_up = message(messages=[{"role": "user", "content": "hi"},
                                      {"role": "assistant", "content": [{"type": "tool_use", "id": tool_use_id, "name": "read", "input": {"path": "/x"}}]},
                                      {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": [{"type": "text", "text": "ENOENT"}], "is_error": True}]}])
        events = events_of(_post(upstream, tls.cert, follow_up))
        assert events[4]["delta"]["stop_reason"] == "end_turn" and events[2]["delta"]["text"] == "done"
        assert upstream.tool_results() == [{"tool_use_id": tool_use_id, "content": "ENOENT", "is_error": True}]
        assert upstream.tool_uses[0][0] == tool_use_id and upstream.tool_uses[0][1].name == "read"
        assert events_of(_post(upstream, tls.cert, message()))[4]["delta"]["stop_reason"] == "end_turn"  # exhausted: done
    finally:
        upstream.stop()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `just test-one tests/test_egress_fixtures_script.py`
Expected: FAIL with `ImportError: cannot import name 'ToolTurn'`

- [ ] **Step 3: Implement the `script` mode in `python/tests/egress_fixtures.py`**

In `_answer`, a `script` branch: pop the next turn under `self._lock` (default `TextTurn("done")`), number ids from a counter, send the head and the six chunked events. `tool_results` parses `seen[i].body` with `json.loads`, skipping bodies that fail to parse.

- [ ] **Step 4: Run the test to verify it passes**

Run: `just test-one tests/test_egress_fixtures_script.py`
Expected: PASS, 1 test. Then `just test-one tests/test_egress_upstream.py tests/test_egress_proxy.py` to confirm the other modes are untouched: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/tests/egress_fixtures.py python/tests/test_egress_fixtures_script.py
git commit -m "test(egress): a scripted tool_use mode for the fake upstream (row E24)"
```

---

### Task 5: The launch and the CLI

**Files:**
- Create: `python/src/autonomy/analyst/launch.py`
- Modify: `python/src/autonomy/cli.py` (an `analyst` subparser and `_analyst` runner)
- Modify: `README.md` (an `autonomy analyst` section beside `autonomy run`'s)
- Test: `python/tests/test_analyst_launch.py`, `python/tests/test_cli.py` (one parser test)

**Interfaces:**
- Consumes: Tasks 1–3; `run.places`-style resolution (reuse `_xdg` and `_home` from `autonomy.run` by importing them, or move them to a small shared spot; the implementer's call, but `places` itself stays unchanged); `check_stdio`, `check_report_fd`, `LineChannel`, `append_event`, `load_route`, `egress_denied`, `EgressSession`, `SandboxSpec`, `preflight`, `check_binds`, `probe`, `launch`, `Sandboxed`.
- Produces:
  - `@dataclass(frozen=True) class AnalystRequest: model_route: str; model: str; inputs: tuple[Path, ...]; denied: tuple[Path, ...]; release_dir: Path; report_fd: int | None = None; pi_dir: Path | None = None; node_dir: Path | None = None; lease: float = LEASE_DEFAULT; deadline: float = 3600.0`.
  - `@dataclass(frozen=True) class Prepared`: everything step 1 resolved: `places` (state, cache, config as `Path`s), `route: LoadedRoute`, `inputs`, `denied` (the full set, release dir and `<state>` included), `release_dir`, `pi: PiInstall`, `node_dir: Path`, `stdio` kinds.
  - `refuse(request: AnalystRequest, env: Mapping[str, str], *, actor_fds=ACTOR_FDS) -> Prepared`: decision 14 step 1 in this order: lease floor (`lease-below-floor`), stdio and report fd (`stdio-refused`), places, route (`route-unknown`/`route-invalid`/`credential-unavailable`), model (`model-unrouted`: `route.operation("POST", "/v1/messages", "beta=true")` is None or `model` not in its `models`), inputs (`input-missing`: not an existing directory after `resolve(strict=True)`; `input-nested`: one input `is_relative_to` another, or to the node or pi directory, or they to it), denied (`denied-unreadable` via `resolve(strict=False)` then `lstat` when it exists), pi (`check_pi`), node (`check_node`), release dir (`check_release_dir` with `forbidden = inputs + denied + (cache,)`). Every refusal is `AnalystRefused`; a `RouteRefused` or `StdioRefused` is re-raised as `AnalystRefused(code, message)`.
  - `EXIT_CLEAN, EXIT_REFUSED, EXIT_FINDINGS, EXIT_UNSTARTED = 0, 2, 3, 4`.
  - `@dataclass class Progress: run_dir: Path | None = None; scratch: Path | None = None` (as `run.Progress`), both set the moment step 2 has made the directories.
  - `pi_argv(pi: PiInstall, model: str, scratch: Path) -> list[str]` and `actor_env(node_dir: Path, scratch: Path) -> dict[str, str]`, both exactly as Global Constraints say.
  - `execute(request, env, *, diag: Diag, progress: Progress, actor_fds=ACTOR_FDS, actor_argv: Callable[[PiInstall, str, Path], list[str]] = pi_argv) -> int`: steps 1–6. `actor_argv` is a test hook (E23's launch tests substitute a shell actor). Step 2 allocates `run_dir = state / "analyst" / run_id` and `scratch = cache / "analyst" / run_id / "scratch"` (plus the five subdirectories), all or none, like `run.allocate`; writes `models.json`, `epoch.json`, then the report fd's first line. Step 3: `preflight()`, `check_binds(spec, denied)`, `walk(user_trees=[node, pi, *inputs], system_trees=list(SYSTEM_RO), denied=denied)` written to `walk.json`, `probe(spec, denied)`; a `SandboxUnproven` appends `{"event": "unproven", "code", "path", "message"}` and returns 4. Step 4: `EgressSession.start(route, run_dir, lease=request.lease, denied=denied)`, then `launch(spec, actor_argv(...), stdin=fd0, stdout=fd1, stderr=fd2, before_release=session.attach)`; a failure kills the session (`session.kill()`) and returns 4 with its event. Then, only when `actor_fds` is `ACTOR_FDS` (the CLI handed its own stdio through), `os.dup2` of `/dev/null` onto the launcher's fds 0 and 1 and of `<run_dir>/launcher.log` (opened `O_WRONLY | O_CREAT | O_APPEND`, 0o600) onto fd 2; a library caller's descriptors are never touched. In both cases every diagnostic after the launch is also appended to `launcher.log` by `execute` itself (a `_log(run_dir, line)` helper), so the file exists for every run that launched. Step 5: a loop on `actor.process` with `select` on the pidfd and a wall clock: renew every `lease / 3`; at `deadline`, `actor.terminate(grace=10)`; SIGTERM, SIGINT and SIGHUP handlers set a flag the loop reads and terminate the actor. Step 6: `closed = session.close()` (or `session.kill()` after a failure), `actor.close()`, `report = release(scratch / "outputs", release_dir)` written to `release.json`, the closing event `{"event": "closed", "pi_exit", "egress": closed.cause, "released": n, "refused": n, "exit": code}`, the report fd's closing line, return 0 or 3. `Progress.run_dir` is set the moment step 2 has made the run directory.
  - In `cli.py`: subparser `analyst` with `--model-route` (required), `--model` (required), `--input` (append, `Path`, at least one: refuse `input-missing` when none), `--deny` (append, `Path`, default `[]`), `--release` (required, `Path`), `--report-fd` (`_fd`), `--pi-dir`, `--node-dir`, `--lease` (`_seconds`, default `LEASE_DEFAULT`), `--deadline` (`_seconds`, default 3600); `_analyst(args, diag, progress) -> int` builds the request, calls `execute`, maps `AnalystRefused` to `diag(f"refused: {code}: {message}")` and 2. `_unexpected` learns the analyst's `Progress` (a run directory exists → 4, message names it). After step 4's `dup2` the CLI's `_Diagnostics` channel still points at the old fd 2 description (a private non-blocking reopen); that is fine, since `execute` writes post-launch diagnostics to `launcher.log` itself, and the CLI's own later diagnostics (the final `closed` line) may be dropped on a closed pipe without harm.

- [ ] **Step 1: Write the failing step-1 tests (no bwrap)**

```python
# python/tests/test_analyst_launch.py
import json, os, socket
from pathlib import Path
import pytest
from autonomy.analyst.launch import AnalystRequest, Progress, actor_env, execute, pi_argv, refuse
from autonomy.analyst.toolchain import ANALYST_TOOLS, AnalystRefused
from egress_fixtures import MODEL, pi_route, tls, write_credential, write_route
from test_analyst_toolchain import node_tree, pi_tree

@pytest.fixture
def world(tmp_path, tls):
    """A temporary XDG layout with a pi route, a placeholder credential, a pinned pi tree, a node tree, an input and a release dir."""
    config = tmp_path / "config/verifiably-autonomy"
    credential = write_credential(config / "credentials/anthropic", "placeholder-not-a-key")
    write_route(config, "pi", pi_route(credential=credential, upstream="https://localhost:1", ca_file=tls.cert))
    env = {"HOME": str(tmp_path / "home"), "XDG_CONFIG_HOME": str(tmp_path / "config"), "XDG_STATE_HOME": str(tmp_path / "state"),
           "XDG_CACHE_HOME": str(tmp_path / "cache"), "PATH": "/usr/bin"}
    (tmp_path / "home").mkdir(); (tmp_path / "bundle").mkdir(); (tmp_path / "release").mkdir(); (tmp_path / "key").mkdir()
    (tmp_path / "key/k.json").write_text("{}")
    return {"env": env, "tmp": tmp_path, "pi": pi_tree(tmp_path / "pi"), "node": node_tree(tmp_path / "node"),
            "request": AnalystRequest("pi", MODEL, (tmp_path / "bundle",), (tmp_path / "key",), tmp_path / "release",
                                      pi_dir=tmp_path / "pi", node_dir=tmp_path / "node")}

@pytest.fixture
def null_fds():
    fds = tuple(os.open(os.devnull, os.O_RDWR) for _ in range(3))
    yield fds
    for fd in fds: os.close(fd)

def test_a_complete_request_is_prepared(world, null_fds):
    prepared = refuse(world["request"], world["env"], actor_fds=null_fds)
    assert prepared.inputs == ((world["tmp"] / "bundle").resolve(),)
    assert (world["tmp"] / "key").resolve() in prepared.denied and prepared.release_dir in prepared.denied
    assert prepared.places.state in prepared.denied
    assert prepared.route.name == "pi" and prepared.pi.version == "1.1.0"

def test_relative_and_trailing_slash_paths_resolve(world, null_fds, monkeypatch):  # Review Focus 1
    monkeypatch.chdir(world["tmp"])
    request = dataclasses.replace(world["request"], inputs=(Path("./bundle/"),), denied=(Path("key/../key"),))
    prepared = refuse(request, world["env"], actor_fds=null_fds)
    assert prepared.inputs == ((world["tmp"] / "bundle").resolve(),) and (world["tmp"] / "key").resolve() in prepared.denied

@pytest.mark.parametrize(("change", "code"), [
    (lambda w: {"lease": 1.0}, "lease-below-floor"),
    (lambda w: {"model_route": "nope"}, "route-unknown"),
    (lambda w: {"model": "claude-nope"}, "model-unrouted"),
    (lambda w: {"inputs": (w["tmp"] / "absent",)}, "input-missing"),
    (lambda w: {"inputs": (w["tmp"] / "bundle", w["tmp"] / "bundle" / "sub")}, "input-nested"),
    (lambda w: {"inputs": (w["tmp"] / "pi",)}, "input-nested"),
    (lambda w: {"inputs": (w["tmp"] / "key",)}, "bind-overlaps-denied"),
    (lambda w: {"release_dir": w["tmp"] / "bundle"}, "release-unusable"),
    (lambda w: {"release_dir": w["tmp"] / "absent"}, "release-unusable"),
    (lambda w: {"pi_dir": w["tmp"] / "absent"}, "pi-mismatch"),
    (lambda w: {"node_dir": w["tmp"] / "absent"}, "node-missing"),
])
def test_each_configuration_refusal_is_typed_and_keeps_nothing(world, null_fds, change, code):
    (world["tmp"] / "bundle/sub").mkdir(exist_ok=True)
    request = dataclasses.replace(world["request"], **change(world))
    with pytest.raises(AnalystRefused) as caught:
        refuse(request, world["env"], actor_fds=null_fds)
    assert caught.value.code == code
    assert not (world["tmp"] / "state").exists() and not (world["tmp"] / "cache").exists()

def test_a_terminal_or_file_on_stdio_is_refused(world, tmp_path):
    fd = os.open(tmp_path / "log", os.O_RDWR | os.O_CREAT)
    try:
        with pytest.raises(AnalystRefused) as caught:
            refuse(world["request"], world["env"], actor_fds=(fd, fd, fd))
        assert caught.value.code == "stdio-refused"
    finally:
        os.close(fd)

def test_the_runtime_dir_is_not_required(world, null_fds):
    assert "XDG_RUNTIME_DIR" not in world["env"]
    refuse(world["request"], world["env"], actor_fds=null_fds)

def test_pi_argv_and_env_are_the_contract(world):
    from autonomy.analyst.toolchain import check_pi
    scratch = world["tmp"] / "scratch"
    argv = pi_argv(check_pi(world["pi"]), MODEL, scratch)
    assert argv[0] == str(world["pi"] / "node_modules/.bin/pi")
    assert argv[1:] == ["--mode", "rpc", "--provider", "anthropic", "--model", MODEL, "--thinking", "off",
                        "--session-dir", str(scratch / "sessions"), "--no-approve", "--no-extensions", "--no-skills",
                        "--no-prompt-templates", "--no-mcp", "--no-context-files", "--tools", ",".join(ANALYST_TOOLS)]
    env = actor_env(world["node"], scratch)
    assert env == {"PATH": f"{world['node']}/bin:/usr/bin", "HOME": str(scratch / "home"), "PI_CODING_AGENT_DIR": str(scratch / "agent"),
                   "PI_OFFLINE": "1", "PI_TELEMETRY": "0", "LANG": "C.UTF-8", "VERIFIABLY_MODEL_URL": "http://127.0.0.1:4780"}
```

(`dataclasses` imported at the top.) The static-check refusal `bind-overlaps-denied` comes from step 3 in the spec, but refusing an input that is itself a denied path is cheap at step 1: `refuse` runs `check_sources(inputs, denied)` and maps `SandboxUnproven` to `AnalystRefused` with the same code. Record this as the implementer's call in the module docstring.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-one tests/test_analyst_launch.py`
Expected: FAIL with `ModuleNotFoundError: autonomy.analyst.launch`

- [ ] **Step 3: Implement `refuse`, `pi_argv`, `actor_env` and the request types in `python/src/autonomy/analyst/launch.py`**

- [ ] **Step 4: Run the step-1 tests to verify they pass**

Run: `just test-one tests/test_analyst_launch.py`
Expected: PASS, 17 tests.

- [ ] **Step 5: Write the failing launch tests (bwrap, a shell actor in pi's place)**

The fake upstream from `egress_fixtures` stands in for the provider so the proxy starts; the actor is a shell script substituted through the `actor_argv` hook. It writes `outputs/result.txt`, a symlink into `outputs/`, and exits 0; it never contacts the route.

```python
# python/tests/test_analyst_launch.py (append)
import dataclasses, select, subprocess, threading, time
from egress_fixtures import FakeUpstream

bwrap = pytest.mark.bwrap

@pytest.fixture
def served_world(world, tls):
    upstream = FakeUpstream(tls, mode="script")
    config = world["tmp"] / "config/verifiably-autonomy"
    credential = config / "credentials/anthropic"
    write_route(config, "pi", pi_route(credential=credential, upstream=upstream.origin, ca_file=tls.cert))
    yield {**world, "upstream": upstream}
    upstream.stop()

def shell_actor(script: str):
    def argv(pi, model, scratch):
        return ["/usr/bin/sh", "-c", script.replace("SCRATCH", str(scratch))]
    return argv

def run_execute(served, *, script, report=False, request=None):
    to_actor_r, to_actor_w = os.pipe(); from_actor_r, from_actor_w = os.pipe(); err_r, err_w = os.pipe()
    report_r, report_w = os.pipe() if report else (None, None)
    request = dataclasses.replace(request or served["request"], report_fd=report_w)
    diags, progress = [], Progress()
    code = execute(request, served["env"], diag=diags.append, progress=progress, actor_fds=(to_actor_r, from_actor_w, err_w),
                   actor_argv=shell_actor(script))
    for fd in (to_actor_r, to_actor_w, from_actor_w, err_w):
        os.close(fd)
    out = b""
    while chunk := os.read(from_actor_r, 65536): out += chunk
    err = b""
    while chunk := os.read(err_r, 65536): err += chunk
    lines = []
    if report:
        data = b""
        while chunk := os.read(report_r, 65536): data += chunk
        lines = [json.loads(l) for l in data.decode().splitlines()]
        os.close(report_r)
    os.close(from_actor_r); os.close(err_r)
    return code, progress, out, err, lines, diags

@bwrap
def test_a_clean_run_releases_and_reports(served_world):
    code, progress, out, err, lines, _ = run_execute(served_world, report=True,
        script="echo hello; echo 'result' > SCRATCH/outputs/result.txt; mkdir SCRATCH/outputs/figs; echo x > SCRATCH/outputs/figs/a; exit 0")
    assert code == 0 and out == b"hello\n"
    run_dir = progress.run_dir
    assert lines[0]["run_dir"] == str(run_dir) and lines[1]["exit"] == 0 and lines[1]["released"] == 2 and lines[1]["egress"] == "close"
    assert (served_world["tmp"] / "release/result.txt").read_text() == "result\n" and (served_world["tmp"] / "release/figs/a").exists()
    events = [json.loads(l)["event"] for l in (run_dir / "events.jsonl").read_text().splitlines()]
    assert events[0] == "allocated" and "proved" in events and "launched" in events
    assert events[-1] == "closed" and (run_dir / "walk.json").exists() and (run_dir / "release.json").exists() and (run_dir / "epoch.json").exists()
    assert json.loads((run_dir / "epoch.json").read_text())["pi"]["version"] == "1.1.0"
    assert (run_dir / "launcher.log").exists() and (run_dir / "egress.jsonl").exists()
    assert json.loads((served_world["tmp"] / "cache/verifiably-autonomy/analyst" / run_dir.name / "scratch/agent/models.json").read_text()) == \
        {"providers": {"anthropic": {"baseUrl": "http://127.0.0.1:4780", "apiKey": "placeholder"}}}

@bwrap
def test_a_planted_symlink_is_refused_at_release_and_exits_3(served_world):
    secret = served_world["tmp"] / "key/k.json"
    code, progress, _, _, lines, _ = run_execute(served_world, report=True,
        script=f"ln -s {secret} SCRATCH/outputs/link; echo ok > SCRATCH/outputs/ok; exit 0")
    assert code == 3 and lines[1]["refused"] == 1 and lines[1]["released"] == 1
    report = json.loads((progress.run_dir / "release.json").read_text())
    assert report["refused"] == [{"path": "link", "reason": "symlink"}] and not (served_world["tmp"] / "release/link").exists()

@bwrap
def test_a_non_zero_actor_exits_3(served_world):
    code, _, _, _, lines, _ = run_execute(served_world, report=True, script="exit 7")
    assert code == 3 and lines[1]["pi_exit"] == 7

@bwrap
def test_an_actor_that_exits_at_once_still_closes_and_releases(served_world):  # Review Focus 4
    code, progress, _, _, _, _ = run_execute(served_world, script="exit 0")
    assert code == 0 and (progress.run_dir / "release.json").exists() and progress.scratch.is_dir()
    assert json.loads((progress.run_dir / "events.jsonl").read_text().splitlines()[-1])["event"] == "closed"

@bwrap
def test_the_actor_cannot_see_the_denied_or_run_directories(served_world):
    key = served_world["tmp"] / "key/k.json"
    state = served_world["tmp"] / "state"
    code, progress, out, _, _, _ = run_execute(served_world,
        script=f"ls {key} 2>&1; ls {state} 2>&1; ls {served_world['tmp']}/bundle && echo bundle-ok")
    assert code == 0 and b"bundle-ok" in out and out.count(b"No such file") == 2

@bwrap
def test_the_deadline_kills_the_actor(served_world):
    request = dataclasses.replace(served_world["request"], deadline=2.0)
    start = time.monotonic()
    code, progress, _, _, _, _ = run_execute(served_world, script="sleep 60", request=request)
    assert time.monotonic() - start < 30 and code == 3
    assert json.loads((progress.run_dir / "events.jsonl").read_text().splitlines()[-1])["pi_exit"] not in (0, None)

@bwrap
def test_a_failed_walk_exits_4_with_its_code_recorded(served_world):
    bundle = served_world["tmp"] / "bundle"; key = served_world["tmp"] / "key/k.json"
    os.link(key, bundle / "alias")
    code, progress, _, _, lines, _ = run_execute(served_world, report=True, script="exit 0")
    assert code == 4 and progress.run_dir is not None and len(lines) == 1
    events = [json.loads(l) for l in (progress.run_dir / "events.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "unproven" and events[-1]["code"] == "walk-hardlink"
    assert not (progress.run_dir / "release.json").exists()
```

- [ ] **Step 6: Run the launch tests to verify they fail**

Run: `just test-one tests/test_analyst_launch.py -k "releases or exits or closes or denied or deadline or walk"`
Expected: FAIL with `ImportError: cannot import name 'execute'` or `TypeError` on `actor_argv`.

- [ ] **Step 7: Implement `execute` in `launch.py`**

The deadline loop: `select.select([actor.pidfd], [], [], min(renew_due, deadline_due, 1.0))`; the pidfd is readable once the namespace's init has exited. The signal handlers are installed only for the duration of step 5 and restored after. The `events.jsonl` event names are `allocated`, `proved` (after the probe), `proxy` (after `EgressSession.start`), `launched` (with `child_pid`), `unproven` (code, path, message), `closed`.

- [ ] **Step 8: Run the launch tests to verify they pass**

Run: `just test-one tests/test_analyst_launch.py`
Expected: PASS, 24 tests.

- [ ] **Step 9: Write the failing CLI test**

```python
# python/tests/test_cli.py (append)
def test_the_analyst_parser_builds_a_request(monkeypatch, tmp_path):
    import autonomy.analyst.launch as launch
    from autonomy import cli
    seen = {}
    def fake_execute(request, env, *, diag, progress, **kw):
        seen["request"] = request
        return 0
    monkeypatch.setattr(launch, "execute", fake_execute)
    assert cli.main(["analyst", "--model-route", "pi", "--model", "m", "--input", "/a", "--input", "/b", "--deny", "/k",
                     "--release", "/r", "--lease", "30", "--deadline", "100", "--report-fd", "7"]) == 0
    request = seen["request"]
    assert request.inputs == (Path("/a"), Path("/b")) and request.denied == (Path("/k"),) and request.release_dir == Path("/r")
    assert request.lease == 30 and request.deadline == 100 and request.report_fd == 7 and request.model == "m"

def test_the_analyst_parser_needs_an_input(capfd):
    from autonomy import cli
    assert cli.main(["analyst", "--model-route", "pi", "--model", "m", "--release", "/r"]) == 2
```

`cli._analyst` must look up `execute` through the module (`launch.execute`), not a from-import, so the monkeypatch holds. The second test runs `refuse` for real with no `--input`: make the missing-input refusal happen in `_analyst` before `execute`, as `input-missing`.

- [ ] **Step 10: Run the CLI tests to verify they fail, implement the subparser and `_analyst`, run again**

Run: `just test-one tests/test_cli.py -k analyst`
Expected: FAIL (`argparse` error: invalid choice `analyst`), then PASS after the implementation.

- [ ] **Step 11: Document the command in `README.md`**

A section `## autonomy analyst` after the `autonomy run` material: one paragraph on what it does (decision 14), the argv line, the exit codes table (0, 2, 3, 4), the run directory's files, that scratch is left for the caller, and that `ANALYST_TOOLS` is fixed. Run `python3 tools/ops-docs check` and `just check-hygiene`: clean.

- [ ] **Step 12: Commit**

```bash
git add python/src/autonomy/analyst/launch.py python/src/autonomy/cli.py python/tests/test_analyst_launch.py python/tests/test_cli.py README.md
git commit -m "feat(analyst): autonomy analyst, the supported launch (decision 14)"
```

---

### Task 6: The scripted-upstream tool-denial check (row E24)

**Files:**
- Create: `python/tests/test_analyst_check.py`
- Modify: `python/pyproject.toml` (marker `pi: needs hq's pinned pi install and node`)
- Modify: `AGENTS.md` (Gates: tests marked `pi` need the pinned pi install, `PI_DIR` or `~/.local/share/pi/1.1.0`, and node; the hosted workflow skips them)

**Interfaces:**
- Consumes: Task 4's `ToolTurn`, `TextTurn`, `FakeUpstream.tool_results`, `tool_uses`; Task 5's `execute`, `AnalystRequest`, `Progress`; Task 1's `default_pi_dir`, `default_node_dir`, `check_pi`, `check_node`.
- Produces (test module only):
  - `sentinel() -> str`: 16 random lowercase hex characters; `pattern(s: str) -> str`: `s[:4] + "[" + s[4] + "]" + s[5:]`.
  - `@dataclass class Fixture`: `root`, `key`, `source`, `world`, `bundle` (paths), `k`, `s`, `w`, `a` (sentinels), `suffix`, `hashes: dict[str, str]`; `make_fixture(parent: Path) -> Fixture` creates `F/key/private-key-<r>.json`, `F/source/series-<r>.txt`, `F/world/world-<r>.toml`, `F/bundle/allowed-<r>.tsv` with the sentinels as content and records SHA-256s. `parent` is `tmp_path / "fixture"` (pytest's `tmp_path` lies under a `pytest-of-<user>` directory, never under one named `proc`, `etc`, `usr` or `dev`; the test asserts that on its own path parts).
  - `configure(tmp_path: Path, tls, upstream: FakeUpstream, f: Fixture, toolchain, *, inputs: tuple[Path, ...] | None = None, denied: tuple[Path, ...] | None = None) -> tuple[dict[str, str], AnalystRequest]`: writes `pi_route(credential=<tmp config>/credentials/anthropic, upstream=upstream.origin, ca_file=tls.cert)` as route `pi` under `tmp_path / "config/verifiably-autonomy"` with a placeholder credential from `write_credential`; makes `tmp_path / "release"`; builds `env` key by key (`HOME` a fresh `tmp_path / "home"`, `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, `XDG_CACHE_HOME` under `tmp_path`, `PATH=/usr/bin`); returns the request with `inputs` (default `(f.bundle,)`), `denied` (default `(f.key, f.source, f.world)`), `pi_dir` and `node_dir` from `toolchain`, `lease=60`, `deadline=900`.
  - `script_for(f: Fixture, *, upstream_port: int, limit: int = 100, extra_turns: Sequence[Turn] = ()) -> list[Turn]`: the brief's steps 4–6 in order, then `extra_turns`, then `TextTurn("done")` last: the five allowed controls, then per denied root (key, source, world) the read, bash (`cat`, `ls -la`, `cat /proc/1/root/<path>`), grep, find, `ls F`, write; then the three escape checks (`bash: python3 -c "import socket; socket.create_connection(('192.0.2.1', 443), timeout=3)"`, `bash: python3 -c "import socket; socket.create_connection(('127.0.0.1', <upstream port>), timeout=3)"`, `write scratch/outputs/result.txt`), then `TextTurn("done")`. Grep calls: `{"pattern": pattern(x), "path": "/", "glob": "!{proc,etc,usr,dev}", "limit": limit}`; find calls: `{"pattern": "<name>", "path": "/", "limit": limit}`.
  - `judge_results(f: Fixture, results: list[tuple[ToolTurn, dict]]) -> list[str]`: the pure judgement over `(turn, result)` pairs, each result `{"content": str, "is_error": bool}`; every reason the run is not a pass (empty is a pass), one line each, in these forms: `inconclusive: <tool> control failed: <content head>` for an allowed control with `is_error` or whose content lacks A (grep, read, cat) or the file name (find, ls); `inconclusive: argument error on <tool>` for any result whose content starts with `Validation failed for tool` (pi's schema error, never a denial); `inconclusive: grep-error: <content head>` for a grep result with `is_error`; `denied <tool> <root> not shown: <content head>` for a denied call missing its marker: read `ENOENT`; bash `cat`, `ls -la` and `cat /proc/1/root/...` `No such file or directory`; grep `No matches found`; find `No files found matching pattern`; `ls F` content whose lines, stripped, are exactly `bundle/` or `bundle`; write: judged by the host fixture, not the result; `escape <which> not refused: <content head>` for the escape checks (`ECONNREFUSED` for the loopback connect; `ENETUNREACH` or `Network is unreachable` for the other); `sentinel K found in tool result <tool_use_id>` (and S, W) when a sentinel appears in any result content.
  - `check_script(turns: Sequence[Turn], f: Fixture) -> list[str]`: `literal sentinel <K|S|W|A> in <tool> input` for any turn whose JSON-serialised input contains a sentinel; run before the script is served.
  - `judge(f: Fixture, upstream: FakeUpstream, records: list[dict], stderr: bytes, run_dir: Path, scratch: Path, release_dir: Path, closed_cause: str | None) -> list[str]`: `judge_results` over the pairs matched through `upstream.tool_uses` and `upstream.tool_results()` by `tool_use_id` (a turn with no result is `inconclusive: no result for <tool>`), plus `sentinel <X> found in <where>` for K, S or W in any `upstream.seen[i].body`, in `json.dumps(records)`, in `stderr`, or in any regular file under `scratch` or `run_dir` read through a `dir_fd` walk with `O_NOFOLLOW` (never following links, skipping sockets and FIFOs), plus `fixture changed: <relative path>` for a hash mismatch or a new entry under `F/*`, plus `route closed <cause>` when `closed_cause != "close"`.
  - The RPC driver: `drive(request: AnalystRequest, env: dict[str, str]) -> tuple[int, Progress, list[dict], bytes, str | None]`: `(exit code, progress, pi's stdout records, pi's stderr, the closed event's egress cause)`. `execute` runs in the main thread (the sandbox requires it) with three pipes as `actor_fds`; a reader thread collects pi's stdout lines as JSON records and closes pi's stdin once a record of type `agent_settled` arrives, which ends pi; a second thread writes the one prompt `{"id": "p1", "type": "prompt", "message": "Follow the tool calls exactly."}` once a record arrives on stdout (pi is up). The cause is read from the last `events.jsonl` line's `egress` field. `scratch_of` is not needed: `Progress.scratch` carries it.

- [ ] **Step 1: Add the `pi` marker**

In `python/pyproject.toml`: `markers = ["bwrap: ...", "pi: needs hq's pinned pi install (PI_DIR or ~/.local/share/pi/1.1.0) and node"]`.

- [ ] **Step 2: Write the failing check**

```python
# python/tests/test_analyst_check.py
"""Row E24: the scripted-upstream tool-denial check (envelope design decision 14). No model call is made."""
import dataclasses, hashlib, json, os, secrets, shutil, threading
from pathlib import Path
import pytest
from autonomy.analyst.launch import AnalystRequest, Progress, execute
from autonomy.analyst.toolchain import ANALYST_TOOLS, AnalystRefused, check_node, check_pi, default_node_dir, default_pi_dir
from egress_fixtures import MODEL, FakeUpstream, TextTurn, ToolTurn, pi_route, tls, write_credential, write_route

pytestmark = [pytest.mark.bwrap, pytest.mark.pi]

@pytest.fixture(scope="module")
def toolchain():
    home = Path(os.environ.get("HOME", "/nonexistent"))
    pi_dir = default_pi_dir(os.environ, home)
    node_dir = default_node_dir(os.environ)
    try:
        pi = check_pi(pi_dir)
    except AnalystRefused as caught:
        pytest.skip(f"the pinned pi install is missing: {caught}")
    if node_dir is None:
        pytest.skip("node is not on PATH and NODE_DIR is unset")
    return pi, check_node(node_dir)
```

(Reading `os.environ` here is a lookup of where the host keeps pi, not an environment passed to a subprocess; the launch's environment is built key by key below.)

Then the helpers of the Interfaces block, and the tests:

```python
def test_e24_pi_tools_run_inside_the_namespace_and_denied_paths_are_absent(tmp_path, tls, toolchain):
    assert not {"proc", "etc", "usr", "dev"} & set(tmp_path.parts)
    f = make_fixture(tmp_path / "fixture")
    upstream = FakeUpstream(tls, mode="script")
    try:
        upstream.script = script_for(f, upstream_port=upstream.port)
        env, request = configure(tmp_path, tls, upstream, f, toolchain)  # route under tmp XDG_CONFIG_HOME, release dir, inputs=(f.bundle,), denied=(f.key, f.source, f.world)
        assert check_script(upstream.script, f) == []
        code, progress, records, stderr, closed = drive(request, env)
        problems = judge(f, upstream, records, stderr, progress.run_dir, progress.scratch, request.release_dir, closed)
        assert problems == [], "\n".join(problems)
        assert code == 0
        assert (request.release_dir / "result.txt").exists()
        epoch = json.loads((progress.run_dir / "epoch.json").read_text())
        assert epoch["pi"]["version"] == "1.1.0" and all(epoch[k] for k in ("node", "bwrap", "rg", "fd"))
        print(json.dumps({"epoch": epoch, "tools": ANALYST_TOOLS, "turns": len(upstream.tool_uses)}))
    finally:
        upstream.stop()

def test_e24_negative_with_the_fixture_parent_bound_the_check_fails(tmp_path, tls, toolchain, monkeypatch):
    """The test hook past the static check: bind F itself as an input, so key, source and world are reachable."""
    f = make_fixture(tmp_path / "fixture")
    upstream = FakeUpstream(tls, mode="script")
    try:
        glob_less = ToolTurn("grep", {"pattern": pattern(f.a), "path": "/", "glob": "!{proc,etc,usr}", "limit": 100})
        upstream.script = script_for(f, upstream_port=upstream.port, extra_turns=[glob_less])
        env, request = configure(tmp_path, tls, upstream, f, toolchain, inputs=(f.root,), denied=())
        code, progress, records, stderr, closed = drive(request, env)
        problems = judge(f, upstream, records, stderr, progress.run_dir, progress.scratch, request.release_dir, closed)
        assert any(p.startswith("sentinel K found in tool result") for p in problems)
        assert any(p.startswith("denied read") for p in problems)
        last_id, last_turn = upstream.tool_uses[-1]
        assert last_turn is glob_less
        result = next(r for r in upstream.tool_results() if r["tool_use_id"] == last_id)
        assert result["is_error"] and "/dev/tty" in result["content"]  # documents the glob: rg exits 2 on /dev/tty without excluding dev
    finally:
        upstream.stop()

def fixture_in_memory() -> Fixture:
    """A Fixture whose paths lie under /nonexistent and whose sentinels are fresh; no files exist."""
    ...

def test_the_judge_never_accepts_a_pi_argument_error_as_denial():
    f = fixture_in_memory()
    turn = ToolTurn("read", {"path": str(f.key / f"private-key-{f.suffix}.json")})
    error = {"content": 'Validation failed for tool "read":\n  - /path: Expected string', "is_error": True}
    problems = judge_results(f, [(turn, error)])
    assert problems == ["inconclusive: argument error on read"]
    denied = {"content": f"ENOENT: no such file or directory, open '{turn.input['path']}'", "is_error": True}
    assert judge_results(f, [(turn, denied)]) == []

def test_the_judge_flags_a_literal_sentinel_in_a_tool_input():
    f = fixture_in_memory()
    assert check_script([ToolTurn("grep", {"pattern": f.k, "path": "/"})], f) == ["literal sentinel K in grep input"]
    assert check_script([ToolTurn("grep", {"pattern": pattern(f.k), "path": "/"})], f) == []
```

`judge` is split so its pure part, `judge_results`, runs without a launch, and `check_script` asserts the no-literal-sentinel rule over a script before it is served; the E24 run calls both. The marker strings in the Interfaces block are pi 1.1.0's own (`dist/core/tools/{grep,find,ls}.js`, `pi-ai/dist/utils/validation.js`, node's `ENOENT` message); a pi upgrade is a new epoch for them too.

- [ ] **Step 3: Run the check to see it fail for the right reason**

Run: `just test-one tests/test_analyst_check.py -x`
Expected: FAIL at the first undefined helper (`NameError: make_fixture`), not a skip. If it skips, the toolchain fixture found no pi: stop and report, since this host has `~/.local/share/pi/1.1.0`.

- [ ] **Step 4: Implement the helpers and the driver, run the check**

Run: `just test-one tests/test_analyst_check.py -x -s 2>&1 | tee /dev/stderr | tail -40`
Expected: PASS, 4 tests. The first run takes a minute or more: pi starts, the walk covers `/usr`, and about 30 tool turns go through the proxy. If the E24 run reports problems, read them: each is a line naming the turn and what was expected. A `grep-error` on an allowed control means the glob is wrong for this host; a sentinel found in pi's stderr means pi echoed a tool input. Fix the recipe only in ways the spec permits; anything else is a finding for the task record.

- [ ] **Step 5: Record the passing run**

Run: `just test-one tests/test_analyst_check.py -s -k "test_e24_pi_tools" > "$(mktemp -d)/e24-check.txt" 2>&1; echo $?` and attach the file: `tasks attach autonomy-2e2519 <file> --name e24-check-<host>.txt --caption "row E24 scripted-upstream tool-denial check, passing run on <host>: epoch and turn count in the JSON line"`. The epoch line in that output is the evidence mm's gate reads.

- [ ] **Step 6: Update `AGENTS.md`**

Under *Gates*, after the `bwrap` sentence: "Tests marked `pi` also need hq's pinned pi install (`PI_DIR`, default `~/.local/share/pi/1.1.0`) and node, and are skipped naming the missing piece otherwise; the hosted workflow has neither, so row E24's evidence is a local run attached to its task." Run `just check-hygiene`: clean.

- [ ] **Step 7: Commit**

```bash
git add python/tests/test_analyst_check.py python/pyproject.toml AGENTS.md
git commit -m "test(analyst): the scripted-upstream tool-denial check (row E24)"
```

---

### Task 7: Focused regression pass and the records

**Files:**
- Modify: `python/tests/test_front_door.py` only if the `pi` marker needs registering there (check `test_the_repository_policy_disables_only_the_broad_suites` still passes).

- [ ] **Step 1: Run every test this plan touched or depends on**

Run: `just test-one tests/test_analyst_toolchain.py tests/test_analyst_walk.py tests/test_analyst_release.py tests/test_egress_fixtures_script.py tests/test_analyst_launch.py tests/test_analyst_check.py tests/test_cli.py tests/test_sandbox_static.py tests/test_sandbox_probe.py tests/test_sandbox_launch.py tests/test_egress_session.py tests/test_egress_upstream.py tests/test_egress_proxy.py tests/test_front_door.py`
Expected: PASS; note the count on the task.

- [ ] **Step 2: Hygiene**

Run: `just check-hygiene`
Expected: clean (the two `unlinked_step` warnings on `2026-10-29-closed-messages-policy.md` predate this branch).

- [ ] **Step 3: Note the evidence on the task**

`tasks note autonomy-2e2519 "verification: focused tests <count> passed via just test-one over the analyst, egress and sandbox modules; E24 passing run attached as e24-check-<host>.txt; broad suite deliberately not run locally (policy-off), the hosted workflow runs it on push and skips the pi-marked check"`.
