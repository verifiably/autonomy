"""autonomy-c5c566 probe: pi over RPC inside Plan A's bwrap sandbox, stdio held by the caller.

Throwaway. Usage: probe.py <root> <run: bare|gitmeta>
<root> holds main/ (main checkout), scratch/wt (linked worktree), scratch/sessions,
scratch/home, agent/ (auth.json). Writes <root>/out-<run>/{rpc.jsonl,stderr.txt,report.json}.
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

from autonomy.sandbox.bwrap import _read_info, build_argv, prove
from autonomy.sandbox.spec import SandboxSpec
from autonomy.sandbox.static import SandboxUnproven, check_binds

HOME = Path.home()
NODE = HOME / ".nvm/versions/node/v26.5.0"
PI_DIR = HOME / ".local/share/pi/1.1.0"
PI = PI_DIR / "node_modules/.bin/pi"
MODEL = "claude-haiku-5-5"

root = Path(sys.argv[1]).resolve()
run = sys.argv[2]
main, scratch, agent = root / "main", root / "scratch", root / "agent"
wt, sessions, home = scratch / "wt", scratch / "sessions", scratch / "home"
out = root / f"out-{run}"
out.mkdir(exist_ok=True)
report: dict[str, object] = {"run": run}

env = {
    "PATH": f"{NODE}/bin:/usr/bin",
    "HOME": str(home),
    "PI_CODING_AGENT_DIR": str(agent),
    "PI_SKIP_VERSION_CHECK": "1",
    "PI_TELEMETRY": "0",
    "GIT_AUTHOR_NAME": "probe", "GIT_AUTHOR_EMAIL": "probe@invalid",
    "GIT_COMMITTER_NAME": "probe", "GIT_COMMITTER_EMAIL": "probe@invalid",
    "LANG": "C.UTF-8",
}
spec = SandboxSpec(scratch=scratch, ro_binds=(NODE, PI_DIR), network="host", env=env)
denied = [p for p in (HOME / ".ssh", HOME / ".pi/agent", HOME / ".config/gh", HOME / ".config/crew") if p.exists()]

# Extra binds the spec cannot express: git metadata for the linked worktree.
admin = main / ".git/worktrees/wt"
extra: list[str] = ["--bind", str(agent), str(agent)]  # pi locks auth.json by mkdir beside it
if run in ("gitmeta", "gitcommit"):
    extra += ["--ro-bind", str(main / ".git"), str(main / ".git"), "--bind", str(admin), str(admin)]
    if run == "gitcommit":
        for sub in ("objects", "refs/heads", "logs"):
            (main / ".git" / sub).mkdir(parents=True, exist_ok=True)
            extra += ["--bind", str(main / ".git" / sub), str(main / ".git" / sub)]
    # The static check with the main checkout denied, as a dev mode would want: expect a refusal.
    try:
        check_binds(SandboxSpec(scratch=scratch, ro_binds=(NODE, PI_DIR, main / ".git")), [*denied, main])
        report["static_check_main_denied_with_git_bound"] = "passed"
    except SandboxUnproven as caught:
        report["static_check_main_denied_with_git_bound"] = f"refused: {caught}"
else:
    denied.append(main)

print("proving", flush=True, file=sys.stderr)
prove(spec, denied)
print("proved", flush=True, file=sys.stderr)
report["prove"] = {"denied": [str(p) for p in denied], "result": "ENOENT on every denied path"}


def sandbox_argv(argv: list[str], info_fd: int | None) -> list[str]:
    args = build_argv(spec, argv, info_fd=info_fd)
    at = args.index("--chdir")
    return [*args[:at], *extra, *args[at:]]


# Credential readability, checked by a non-model actor in the same sandbox: never through pi.
cred = subprocess.run(
    sandbox_argv(["/usr/bin/sh", "-c", f'test -r "{agent}/auth.json" && wc -c < "{agent}/auth.json"'], None),
    capture_output=True, text=True, timeout=60,
)
report["credential_readable_inside"] = {"exit": cred.returncode, "bytes": cred.stdout.strip()}

# Launch: the gate takes its release on its own fd; pi's stdin and stdout are the caller's pipes.
info_r, info_w = os.pipe()
gate_r, gate_w = os.pipe()
gate = f'read -r go <&{gate_r}; exec {gate_r}<&-; [ "$go" = run ] || exit 125; cd "{wt}" || exit 124; exec "$@"'
pi_argv = [
    str(PI), "--mode", "rpc", "--provider", "anthropic", "--model", MODEL, "--thinking", "off",
    "--tools", "read,bash,edit,write,ls", "--session-dir", str(sessions),
    "--no-approve", "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-mcp",
]
stderr_f = open(out / "stderr.txt", "wb")
proc = subprocess.Popen(
    sandbox_argv(["/usr/bin/sh", "-c", gate, "va-gate", *pi_argv], info_w),
    pass_fds=(info_w, gate_r), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr_f,
)
os.close(info_w)
os.close(gate_r)
info = _read_info(info_r, proc)
os.close(info_r)
child = info["child-pid"]
pidfd = os.pidfd_open(child)
os.write(gate_w, b"run\n")
os.close(gate_w)
report["launch"] = {"child_pid": child}
print("launched", child, report["credential_readable_inside"], flush=True, file=sys.stderr)

rpc_log = open(out / "rpc.jsonl", "w", buffering=1)
buf = b""
records: list[dict] = []


def send(cmd: dict) -> None:
    proc.stdin.write(json.dumps(cmd).encode() + b"\n")
    proc.stdin.flush()
    rpc_log.write(json.dumps({"dir": "in", **cmd}) + "\n")


def pump(until, timeout: float) -> dict | None:
    """Read records until `until(record)` is true; return that record, or None on timeout/EOF."""
    global buf
    deadline = time.monotonic() + timeout
    fd = proc.stdout.fileno()
    while True:
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if not line.strip():
                continue
            rec = json.loads(line)
            records.append(rec)
            rpc_log.write(json.dumps({"dir": "out", **rec}) + "\n")
            if until(rec):
                return rec
        left = deadline - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            return None
        chunk = os.read(fd, 65536)
        if not chunk:
            return None
        buf += chunk


t0 = time.monotonic()
send({"id": "s0", "type": "get_state"})
r = pump(lambda r: r.get("id") == "s0", 60)
print("get_state", r is not None, flush=True, file=sys.stderr)
if os.environ.get("ONLY_STATE"):
    proc.kill(); sys.exit(0)
report["get_state"] = None if r is None else {"success": r.get("success"), "secs": round(time.monotonic() - t0, 2)}

prompt = (
    "You are in a git worktree. Do exactly these steps with the bash tool, one command per step, "
    "and report each command's full output verbatim:\n"
    "1. git status\n2. git log -1 --oneline\n3. git rev-parse --git-dir --git-common-dir\n"
    "4. append the line 'probe edit' to NOTES.md (use bash: echo 'probe edit' >> NOTES.md)\n"
    "5. git add NOTES.md && git commit -m 'probe edit'\n6. git log -1 --oneline\n"
    "Do not try to fix failures; just report them. Then stop."
)
t1 = time.monotonic()
send({"id": "p1", "type": "prompt", "message": prompt})
resp1 = pump(lambda r: r.get("id") == "p1", 60)
report["prompt1_response"] = resp1
settled = pump(lambda r: r.get("type") == "agent_settled", 240) if resp1 and resp1.get("success") else None
report["prompt1"] = {
    "settled": settled is not None,
    "aborted": None if settled is None else settled.get("aborted"),
    "secs": round(time.monotonic() - t1, 2),
}
tools = []
for rec in records:
    if rec.get("type") == "tool_execution_end":
        tools.append({"tool": rec.get("toolName"), "isError": rec.get("isError"), "result": rec.get("result")})
report["prompt1_tools"] = tools

# Abort: start a long command, abort once the tool starts.
n0 = len(records)
send({"id": "p2", "type": "prompt", "message": "Run exactly this with the bash tool: sleep 60; echo done"})
started = pump(lambda r: r.get("type") == "tool_execution_start", 120)
t2 = time.monotonic()
send({"id": "a1", "type": "abort"})
settled2 = pump(lambda r: r.get("type") == "agent_settled", 60)
report["abort"] = {
    "tool_started": started is not None,
    "settled": settled2 is not None,
    "aborted": None if settled2 is None else settled2.get("aborted"),
    "secs_to_settle": round(time.monotonic() - t2, 2),
}

send({"id": "st", "type": "get_session_stats"})
st = pump(lambda r: r.get("id") == "st", 30)
report["stats"] = None if st is None else st.get("data")

# Orderly shutdown: close stdin.
proc.stdin.close()
try:
    report["exit"] = proc.wait(timeout=30)
except subprocess.TimeoutExpired:
    signal.pidfd_send_signal(pidfd, signal.SIGKILL)
    report["exit"] = f"killed after 30 s: {proc.wait()}"
os.close(pidfd)
rpc_log.close()
stderr_f.close()

(out / "report.json").write_text(json.dumps(report, indent=2, default=str))
print(json.dumps({k: v for k, v in report.items() if k != "prompt1_tools"}, indent=2, default=str))
