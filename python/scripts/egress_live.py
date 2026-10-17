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

from autonomy.egress.errors import EgressUnproven, RouteRefused
from autonomy.egress.helper import MODEL_URL
from autonomy.egress.route import egress_denied, load_route
from autonomy.egress.session import EgressClosed, EgressSession
from autonomy.run import RunRefused, places
from autonomy.sandbox.bwrap import launch, prove
from autonomy.sandbox.spec import SandboxSpec
from autonomy.sandbox.static import SandboxUnproven


def main(argv: list[str]) -> int:
    try:
        return _main(argv)
    except (RouteRefused, EgressUnproven, RunRefused, SandboxUnproven) as caught:
        print(f"refused: {caught}", file=sys.stderr)
        return 2


def _main(argv: list[str]) -> int:
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
    try:
        records, exit_code = _prompt(spec, session, pi_dir, model, scratch, root)
        closed = session.close()
    except BaseException:
        if session.pidfd >= 0:
            session.kill()  # a failure after the start must not leave the proxy up for its lease
        raise
    lines = [json.loads(line) for line in (run_dir / "egress.jsonl").read_text().splitlines()]
    for line in lines:
        print(json.dumps(line))
    problems = verdict(lines, records, exit_code, closed)
    print(f"records: {root}")
    for problem in problems:
        print(f"failed: {problem}")
    return 1 if problems else 0


def verdict(lines: list[dict], records: list[dict], exit_code: int | None, closed: EgressClosed) -> list[str]:
    """Every reason the live run failed; empty only when pi answered. A 200 is not an
    answer: a provider can report an error inside the stream after it, and pi settling
    says only that it stopped. So the final assistant message must have stopped
    normally with text, pi must exit 0, the route must close cleanly, and a request
    must have streamed to completion with none refused or failed."""
    problems: list[str] = []
    if not any(r.get("type") == "agent_settled" and not r.get("aborted") for r in records):
        problems.append("pi never settled, or its run was aborted")
    finals = [r["message"] for r in records
              if r.get("type") == "message_end" and isinstance(r.get("message"), dict)
              and r["message"].get("role") == "assistant"]
    if not finals:
        problems.append("pi produced no final assistant message")
    else:
        last = finals[-1]
        if last.get("stopReason") != "stop" or last.get("errorMessage"):
            problems.append(f"the final assistant message stopped {last.get('stopReason')!r}: {last.get('errorMessage')}")
        text = "".join(block.get("text", "") for block in last.get("content", [])
                       if isinstance(block, dict) and block.get("type") == "text")
        if not text.strip():
            problems.append("the final assistant message has no text")
    if exit_code != 0:
        problems.append(f"pi exited {exit_code}")
    if closed.cause != "close" or closed.findings():
        problems.append(f"the route closed {closed.cause!r} with {[f.code for f in closed.findings()]}")
    requests = [line for line in lines if "seq" in line]
    if not any(line.get("status") == 200 and line.get("ended") == "complete" for line in requests):
        problems.append("no request streamed to completion")
    for line in requests:
        if line.get("refused") or line.get("ended") != "complete":
            problems.append(f"request {line.get('seq')} was {line.get('refused') or line.get('ended')}")
    return problems


def _prompt(spec: SandboxSpec, session: EgressSession, pi_dir: Path, model: str, scratch: Path, root: Path):
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
    records: list[dict] = []
    buffer, renewed = b"", time.monotonic()
    deadline = time.monotonic() + 240
    exit_code = None
    try:
        while time.monotonic() < deadline and not any(r.get("type") == "agent_settled" for r in records):
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
                if line.strip():
                    records.append(json.loads(line))
        os.close(to_pi)
        exit_code = actor.wait(timeout=30)
    finally:
        actor.close()
        os.close(from_pi)
    return records, exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
