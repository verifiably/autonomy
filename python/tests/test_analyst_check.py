"""The scripted-upstream tool-denial check (docs/envelope.md, docs/egress.md). No
model call is made: the fake upstream answers pi's requests with scripted `tool_use`
turns, and the judge reads what pi's tools returned, what reached the upstream, and what
the host filesystem shows afterwards. The marker strings are pi 1.1.0's own
(`dist/core/tools/{grep,find,ls}.js`, `pi-ai/dist/utils/validation.js`, node's `ENOENT`
message); a pi upgrade is a new epoch for them too."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import secrets
import stat
import threading
from collections.abc import Sequence
from pathlib import Path

import pytest

from autonomy.analyst.launch import AnalystRequest, Progress, execute
from autonomy.analyst.toolchain import (
    ANALYST_TOOLS, AnalystRefused, check_node, check_pi, check_thinking, default_node_dir, default_pi_dir,
)
from egress_fixtures import MODEL, FakeUpstream, TextTurn, ToolTurn, Turn, pi_route, tls, write_credential, write_route  # noqa: F401

pytestmark = [pytest.mark.bwrap, pytest.mark.pi]

GLOB = "!{proc,etc,usr,dev}"
PI_1_1_0_BETAS = ["mid-conversation-output-config-2026-07-01", "thinking-binding-controls-2026-08-01", "inline-tools-2026-09-15"]
"""The anthropic-beta tokens pi 1.1.0 sends beside the fixture route's two older ones. A
token alone grants no body capability: the dialect still closes every
shape, so the check's route lists them, as an operator's live route for pi 1.1.0 must."""
LIMIT = 100
ARGUMENT_ERROR = "Validation failed for tool"
LOOPBACK_REFUSED = ("Connection refused", "ConnectionRefusedError", "Errno 111")
NETWORK_UNREACHABLE = ("Network is unreachable", "ENETUNREACH", "Errno 101")


@pytest.fixture(scope="module")
def toolchain():
    # os.environ is read here only to find where this host keeps pi and node; the launch's
    # own environment is built key by key in `configure`.
    home = Path(os.environ.get("HOME", "/nonexistent"))
    try:
        pi = check_pi(default_pi_dir(os.environ, home))
    except AnalystRefused as caught:
        pytest.skip(f"the pinned pi install is missing: {caught}")
    node_dir = default_node_dir(os.environ)
    if node_dir is None:
        pytest.skip("node is not on PATH and NODE_DIR is unset")
    try:
        return pi, check_node(node_dir)
    except AnalystRefused as caught:  # a system node (/usr/bin/node gives node_dir=/usr, whose bin holds rg): set NODE_DIR
        pytest.skip(f"the node directory is unusable for the analyst: {caught}; point NODE_DIR at a node prefix")


def sentinel() -> str:
    return secrets.token_hex(8)


def pattern(s: str) -> str:
    """Matches `s` without containing it: `abcd[e]fgh` for `abcdefgh`."""
    return s[:4] + "[" + s[4] + "]" + s[5:]


@dataclasses.dataclass
class Fixture:
    root: Path
    suffix: str
    k: str
    s: str
    w: str
    a: str
    hashes: dict[str, str]

    @property
    def key(self) -> Path:
        return self.root / "key"

    @property
    def source(self) -> Path:
        return self.root / "source"

    @property
    def world(self) -> Path:
        return self.root / "world"

    @property
    def bundle(self) -> Path:
        return self.root / "bundle"

    def files(self) -> dict[str, Path]:
        return {
            "K": self.key / f"private-key-{self.suffix}.json",
            "S": self.source / f"series-{self.suffix}.txt",
            "W": self.world / f"world-{self.suffix}.toml",
            "A": self.bundle / f"allowed-{self.suffix}.tsv",
        }

    def sentinels(self) -> dict[str, str]:
        return {"K": self.k, "S": self.s, "W": self.w, "A": self.a}

    def denied_roots(self) -> dict[str, Path]:
        return {"key": self.key, "source": self.source, "world": self.world}


def make_fixture(parent: Path) -> Fixture:
    f = Fixture(parent, secrets.token_hex(4), sentinel(), sentinel(), sentinel(), sentinel(), {})
    contents = {
        "K": json.dumps({"private_key": f.k}) + "\n",
        "S": f"t\tvalue\n1\t{f.s}\n",
        "W": f'name = "{f.w}"\n',
        "A": f"t\tvalue\n1\t{f.a}\n",
    }
    for letter, path in f.files().items():
        path.parent.mkdir(parents=True)
        path.write_text(contents[letter])
        f.hashes[str(path.relative_to(parent))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return f


def fixture_in_memory() -> Fixture:
    """A Fixture whose paths lie under /nonexistent and whose sentinels are fresh; no files."""
    return Fixture(Path("/nonexistent/F"), secrets.token_hex(4), sentinel(), sentinel(), sentinel(), sentinel(), {})


def script_for(f: Fixture, *, upstream_port: int, limit: int = LIMIT, extra_turns: Sequence[Turn] = ()) -> list[Turn]:
    """Allowed control turns first, then denied tool calls: the allowed controls first, then the denied calls per
    root, one `ls F`, the three writes, the escape checks, `extra_turns`, and `done`."""
    files = f.files()
    allowed = files["A"]
    turns: list[Turn] = [
        ToolTurn("grep", {"pattern": pattern(f.a), "path": "/", "glob": GLOB, "limit": limit}),
        ToolTurn("read", {"path": str(allowed)}),
        ToolTurn("bash", {"command": f"cat {allowed}"}),
        ToolTurn("find", {"pattern": allowed.name, "path": "/", "limit": limit}),
        ToolTurn("ls", {"path": str(f.bundle)}),
    ]
    for letter in ("K", "S", "W"):
        path = files[letter]
        turns += [
            ToolTurn("read", {"path": str(path)}),
            ToolTurn("bash", {"command": f"cat {path}"}),
            ToolTurn("bash", {"command": f"ls -la {path.parent}"}),
            ToolTurn("bash", {"command": f"cat /proc/1/root{path}"}),
            ToolTurn("grep", {"pattern": pattern(f.sentinels()[letter]), "path": "/", "glob": GLOB, "limit": limit}),
            ToolTurn("find", {"pattern": path.name, "path": "/", "limit": limit}),
        ]
    turns.append(ToolTurn("ls", {"path": str(f.root)}))
    for root in f.denied_roots().values():
        turns.append(ToolTurn("write", {"path": str(root / f"planted-{f.suffix}.txt"), "content": "planted\n"}))
    turns += [
        ToolTurn("bash", {"command": "python3 -c \"import socket; socket.create_connection(('192.0.2.1', 443), timeout=3)\""}),
        ToolTurn("bash", {"command": f"python3 -c \"import socket; socket.create_connection(('127.0.0.1', {upstream_port}), timeout=3)\""}),
        ToolTurn("write", {"path": "outputs/result.txt", "content": "released\n"}),
    ]
    turns += list(extra_turns)
    turns.append(TextTurn("done"))
    return turns


def check_script(turns: Sequence[Turn], f: Fixture) -> list[str]:
    problems = []
    for turn in turns:
        if isinstance(turn, ToolTurn):
            serialised = json.dumps(turn.input)
            for letter, value in f.sentinels().items():
                if value in serialised:
                    problems.append(f"literal sentinel {letter} in {turn.name} input")
    return problems


def role_of(turn: ToolTurn, f: Fixture) -> tuple[str, str | None]:
    """What a scripted turn is for: `control`, `denied <root>` (read, bash, grep, find),
    `ls-F`, `denied-write <root>`, `escape loopback|network`, or `release`."""
    text = json.dumps(turn.input)
    if str(f.bundle) in text or pattern(f.a) in text or f"allowed-{f.suffix}" in text:
        return "control", None
    if turn.name == "write" and not turn.input["path"].startswith("/"):
        return "release", None
    if turn.name == "bash" and "create_connection" in turn.input["command"]:
        return "escape", "loopback" if "127.0.0.1" in turn.input["command"] else "network"
    if turn.name == "ls" and turn.input.get("path") == str(f.root):
        return "ls-F", None
    files = f.files()
    for name, root in f.denied_roots().items():
        letter = {"key": "K", "source": "S", "world": "W"}[name]
        if str(root) in text or pattern(f.sentinels()[letter]) in text or files[letter].name in text:
            return ("denied-write" if turn.name == "write" else "denied"), name
    return "unknown", None


def _head(content: str) -> str:
    return content.strip().replace("\n", " ")[:120]


def judge_results(f: Fixture, results: list[tuple[ToolTurn, dict]]) -> list[str]:
    """The pure judgement over `(turn, result)` pairs; empty is a pass."""
    problems: list[str] = []
    for turn, result in results:
        content, is_error = str(result.get("content", "")), bool(result.get("is_error"))
        tool_use_id = result.get("tool_use_id", "?")
        role, which = role_of(turn, f)
        if content.startswith(ARGUMENT_ERROR):
            problems.append(f"inconclusive: argument error on {turn.name}")
            continue
        if role == "control":
            expected = f.a if turn.name in ("grep", "read", "bash") else f"allowed-{f.suffix}.tsv"
            if is_error or expected not in content:
                problems.append(f"inconclusive: {turn.name} control failed: {_head(content)}")
        elif role == "denied":
            if turn.name == "grep":
                if is_error:
                    problems.append(f"inconclusive: grep-error: {_head(content)}")
                elif "No matches found" not in content:
                    problems.append(f"denied grep {which} not shown: {_head(content)}")
            else:
                marker = {"read": "ENOENT", "bash": "No such file or directory", "find": "No files found matching pattern"}[turn.name]
                if marker not in content:
                    problems.append(f"denied {turn.name} {which} not shown: {_head(content)}")
        elif role == "ls-F":
            lines = {line.strip() for line in content.splitlines() if line.strip()}
            if lines not in ({"bundle/"}, {"bundle"}):
                problems.append(f"denied ls F not shown: {_head(content)}")
        elif role == "escape":
            markers = LOOPBACK_REFUSED if which == "loopback" else NETWORK_UNREACHABLE
            if not any(marker in content for marker in markers):
                problems.append(f"escape {which} not refused: {_head(content)}")
        elif role == "unknown":
            problems.append(f"inconclusive: a turn with no role: {turn}")
        for letter in ("K", "S", "W"):
            if f.sentinels()[letter] in content:
                problems.append(f"sentinel {letter} found in tool result {tool_use_id}")
    return problems


def _regular_files(root: Path):
    """Every regular file under `root`, read through a dir_fd walk with O_NOFOLLOW."""
    stack = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)]
    paths = [Path(root)]
    while stack:
        fd, base = stack.pop(), paths.pop()
        try:
            with os.scandir(fd) as entries:
                names = [e.name for e in entries]
            for name in names:
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISDIR(info.st_mode):
                    stack.append(os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd))
                    paths.append(base / name)
                elif stat.S_ISREG(info.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
                    try:
                        with open(child, "rb", closefd=False) as handle:
                            yield base / name, handle.read()
                    finally:
                        os.close(child)
        finally:
            os.close(fd)


def judge(f: Fixture, upstream: FakeUpstream, records: list[dict], stderr: bytes, run_dir: Path, scratch: Path,
          release_dir: Path, closed_cause: str | None) -> list[str]:
    by_id = {r["tool_use_id"]: r for r in upstream.tool_results()}
    pairs: list[tuple[ToolTurn, dict]] = []
    problems: list[str] = []
    scripted = sum(isinstance(turn, ToolTurn) for turn in upstream.script)
    if len(upstream.tool_uses) < scripted:  # a run pi abandoned early proves nothing
        problems.append(f"inconclusive: {len(upstream.tool_uses)} of {scripted} scripted tool turns were served")
    for tool_use_id, turn in upstream.tool_uses:
        if tool_use_id in by_id:
            pairs.append((turn, by_id[tool_use_id]))
        else:
            problems.append(f"inconclusive: no result for {turn.name} ({tool_use_id})")
    problems += judge_results(f, pairs)
    sentinels = {letter: f.sentinels()[letter].encode() for letter in ("K", "S", "W")}
    for index, seen in enumerate(upstream.seen):
        for letter, value in sentinels.items():
            if value in seen.body:
                problems.append(f"sentinel {letter} found in upstream request {index}")
    stdout = json.dumps(records).encode()
    for letter, value in sentinels.items():
        if value in stdout:
            problems.append(f"sentinel {letter} found in pi stdout")
        if value in stderr:
            problems.append(f"sentinel {letter} found in pi stderr")
    for tree in (scratch, run_dir):
        for path, data in _regular_files(tree):
            for letter, value in sentinels.items():
                if value in data:
                    problems.append(f"sentinel {letter} found in file {path}")
    for relative, digest in f.hashes.items():
        path = f.root / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            problems.append(f"fixture changed: {relative}")
    for path, _ in _regular_files(f.root):
        if str(path.relative_to(f.root)) not in f.hashes:
            problems.append(f"fixture changed: new file {path.relative_to(f.root)}")
    if closed_cause != "close":
        problems.append(f"route closed {closed_cause}")
    return problems


def configure(tmp_path: Path, tls, upstream: FakeUpstream, f: Fixture, toolchain, *, thinking: str = "low",
              inputs=None, denied=None):
    pi, node_dir = toolchain
    config = tmp_path / "config/verifiably-autonomy"
    credential = write_credential(config / "credentials/anthropic", "placeholder-not-a-key")
    doc = pi_route(credential=credential, upstream=upstream.origin, ca_file=tls.cert)
    doc["header_tokens"]["anthropic-beta"] = doc["header_tokens"]["anthropic-beta"] + PI_1_1_0_BETAS
    write_route(config, "pi", doc)
    for name in ("home", "release"):
        (tmp_path / name).mkdir()
    env = {"HOME": str(tmp_path / "home"), "XDG_CONFIG_HOME": str(tmp_path / "config"),
           "XDG_STATE_HOME": str(tmp_path / "state"), "XDG_CACHE_HOME": str(tmp_path / "cache"), "PATH": "/usr/bin"}
    request = AnalystRequest(
        "pi", MODEL, thinking, inputs if inputs is not None else (f.bundle,),
        denied if denied is not None else (f.key, f.source, f.world), tmp_path / "release",
        pi_dir=pi.dir, node_dir=node_dir, lease=60.0, deadline=600.0,
    )
    return env, request


PROMPT = {"id": "p1", "type": "prompt", "message": "Follow the tool calls exactly."}


def drive(request: AnalystRequest, env: dict[str, str]) -> tuple[int, Progress, list[dict], bytes, str | None]:
    """Run `execute` in the main thread with pipes as pi's stdio. pi's RPC mode writes
    nothing until a command arrives, so the prompt is written before the launch; a
    reader thread closes pi's stdin once it settles (EOF is pi's shutdown), and a second
    thread drains pi's stderr."""
    to_pi_r, to_pi_w = os.pipe()
    from_pi_r, from_pi_w = os.pipe()
    err_r, err_w = os.pipe()
    os.write(to_pi_w, (json.dumps(PROMPT) + "\n").encode())
    records: list[dict] = []
    stderr = bytearray()
    stdin_closed = threading.Event()

    def close_stdin() -> None:
        if not stdin_closed.is_set():
            stdin_closed.set()
            os.close(to_pi_w)

    def read_stdout() -> None:
        buffer = b""
        while chunk := os.read(from_pi_r, 65536):
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    record = {"type": "unparsed", "line": line.decode("utf-8", "replace")}
                records.append(record)
                if record.get("type") == "agent_settled" or (record.get("type") == "response" and not record.get("success", True)):
                    close_stdin()

    def read_stderr() -> None:
        while chunk := os.read(err_r, 65536):
            stderr.extend(chunk)

    readers = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=read_stderr, daemon=True)]
    for thread in readers:
        thread.start()
    progress = Progress()
    try:
        code = execute(request, env, diag=lambda line: None, progress=progress, actor_fds=(to_pi_r, from_pi_w, err_w))
    finally:
        for fd in (to_pi_r, from_pi_w, err_w):
            os.close(fd)
        close_stdin()
        for thread in readers:
            thread.join(timeout=30)
        os.close(from_pi_r)
        os.close(err_r)
    cause = None
    if progress.run_dir is not None:
        lines = (progress.run_dir / "events.jsonl").read_text().splitlines()
        last = json.loads(lines[-1]) if lines else {}
        cause = last.get("egress") if last.get("event") == "closed" else None
    return code, progress, records, bytes(stderr), cause


def test_e24_pi_tools_run_inside_the_namespace_and_denied_paths_are_absent(tmp_path, tls, toolchain):
    assert not {"proc", "etc", "usr", "dev"} & set(tmp_path.parts)
    f = make_fixture(tmp_path / "fixture")
    upstream = FakeUpstream(tls, mode="script")
    try:
        upstream.script = script_for(f, upstream_port=upstream.port)
        env, request = configure(tmp_path, tls, upstream, f, toolchain)
        assert check_script(upstream.script, f) == []
        code, progress, records, stderr, closed = drive(request, env)
        problems = judge(f, upstream, records, stderr, progress.run_dir, progress.scratch, request.release_dir, closed)
        assert problems == [], "\n".join(problems)
        assert code == 0
        assert (request.release_dir / "result.txt").read_text() == "released\n"
        epoch = json.loads((progress.run_dir / "epoch.json").read_text())
        assert epoch["pi"]["version"] == "1.1.0" and all(epoch[k] for k in ("node", "bwrap", "rg", "fd"))
        assert epoch["model"] == MODEL and epoch["thinking"] == "low"
        assert json.loads(upstream.seen[0].body)["messages"][-1]["output_config"] == {"effort": "low"}
        print(json.dumps({"epoch": epoch, "tools": ANALYST_TOOLS, "turns": len(upstream.tool_uses)}))
    finally:
        upstream.stop()


def test_e24_negative_with_the_fixture_parent_bound_the_check_fails(tmp_path, tls, toolchain):
    """The test hook past the static check: bind F itself as the input and deny nothing,
    so key, source and world are reachable, and the judge must say so."""
    f = make_fixture(tmp_path / "fixture")
    upstream = FakeUpstream(tls, mode="script")
    try:
        glob_less = ToolTurn("grep", {"pattern": pattern(f.a), "path": "/", "glob": "!{proc,etc,usr}", "limit": 100})
        literal = ToolTurn("bash", {"command": f"printf %s {f.w}"})  # a sentinel in a tool input: pi echoes it everywhere
        upstream.script = script_for(f, upstream_port=upstream.port, extra_turns=[glob_less, literal])
        assert check_script(upstream.script, f) == ["literal sentinel W in bash input"]
        env, request = configure(tmp_path, tls, upstream, f, toolchain, inputs=(f.root,), denied=())
        code, progress, records, stderr, closed = drive(request, env)
        problems = judge(f, upstream, records, stderr, progress.run_dir, progress.scratch, request.release_dir, closed)
        assert any(p.startswith("sentinel K found in tool result") for p in problems)
        assert any(p.startswith("denied read") for p in problems)
        last_id, last_turn = upstream.tool_uses[-2]
        assert last_turn is glob_less
        result = next(r for r in upstream.tool_results() if r["tool_use_id"] == last_id)
        assert result["is_error"] and "/dev/tty" in result["content"]  # documents the glob: rg exits 2 on /dev/tty without excluding dev
        assert any(p.startswith("sentinel W found in upstream request") for p in problems)  # the echoed input reached the request bodies
        assert any(p.startswith("sentinel W found in file") and "sessions" in p for p in problems)  # and pi's session files
    finally:
        upstream.stop()


def test_the_judge_never_accepts_a_pi_argument_error_as_denial():
    f = fixture_in_memory()
    turn = ToolTurn("read", {"path": str(f.key / f"private-key-{f.suffix}.json")})
    error = {"content": 'Validation failed for tool "read":\n  - /path: Expected string', "is_error": True}
    problems = judge_results(f, [(turn, error)])
    assert problems == ["inconclusive: argument error on read"]
    denied = {"content": f"ENOENT: no such file or directory, access '{turn.input['path']}'", "is_error": True}
    assert judge_results(f, [(turn, denied)]) == []


def test_the_shipped_pi_registry_matches_thinking_validation(toolchain):
    pi, _ = toolchain
    for model in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"):
        for level in ("low", "medium", "high", "xhigh", "max"):
            check_thinking(pi, model, level)
        for level in ("off", "minimal"):
            with pytest.raises(AnalystRefused) as caught:
                check_thinking(pi, model, level)
            assert caught.value.code == "thinking-unsupported"


def test_the_judge_flags_a_literal_sentinel_in_a_tool_input():
    f = fixture_in_memory()
    assert check_script([ToolTurn("grep", {"pattern": f.k, "path": "/"})], f) == ["literal sentinel K in grep input"]
    assert check_script([ToolTurn("grep", {"pattern": pattern(f.k), "path": "/"})], f) == []
