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

from channels import blocking, drain, fill, one_page_pipe, read_all
from egress_fixtures import pi_route, write_credential, write_route

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
    epilogue: str = ""  # runs after `main` returns `status`, and may change it
    env: dict[str, str] | None = None


def autonomy(tmp_path, args: list[str], io: Stdio, timeout: float = 30) -> tuple[int, float]:
    """Run `autonomy` in a child whose fds 0–2 are `io`'s; return its status and seconds."""
    code = "\n".join([
        "import sys",
        f"sys.path.insert(0, {str(TESTS)!r})",
        io.prelude,
        "from autonomy.cli import main",
        "status = main(sys.argv[1:])",
        io.epilogue,
        "raise SystemExit(status)",
    ])
    started = time.monotonic()
    child = subprocess.Popen(
        [sys.executable, "-c", code, *args], stdin=io.stdin, stdout=io.stdout, stderr=io.stderr,
        pass_fds=io.pass_fds, env=io.env or environment(tmp_path),
    )
    try:
        return child.wait(timeout=timeout), time.monotonic() - started
    except subprocess.TimeoutExpired:
        child.kill()  # a hung child fails the test, and never outlives it
        child.wait()
        raise


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


def scratches(tmp_path) -> list[Path]:
    root = tmp_path / "cache" / "verifiably-autonomy" / "scratch"
    return sorted(root.iterdir()) if root.exists() else []


@pytest.mark.parametrize("stderr", ["readable", "a filled one-page pipe"])
def test_an_unusable_runtime_dir_exits_2_and_keeps_nothing(tmp_path, pipes, held, stderr):  # I1 (a)
    (tmp_path / "not-a-directory").write_text("")
    env = environment(tmp_path)
    env["XDG_RUNTIME_DIR"] = str(tmp_path / "not-a-directory" / "runtime")  # absolute, and cannot be made
    io = pipes["io"]
    io.env = env
    if stderr != "readable":
        err_read, err_write = one_page_pipe()
        held.extend([err_read, err_write])
        fill(err_write)  # never read
        io.stderr = err_write
    status, seconds = autonomy(tmp_path, [*RUN, "--report-fd", str(pipes["report_write"]), *ACTOR], io)
    assert status == 2 and seconds < 10
    assert runs(tmp_path) == [] and scratches(tmp_path) == []
    assert drain(pipes["report"]) == b""
    if stderr == "readable":
        said = drain(pipes["err"])
        assert b"refused: allocation-failed" in said and b"Traceback" not in said


RAISING_STEPS = """
import autonomy.cli as cli
def steps(opened):
    raise {kind}("steps failed\\nafter allocation")
cli.endpoint_side_unbuilt = steps
"""

REPORT_FD_CLOSED = """
import os
try:
    os.fstat({fd})
except OSError:
    pass
else:
    status = 99  # main returned with the report fd still open
"""


@pytest.mark.parametrize("kind", ["RuntimeError", "KeyboardInterrupt"])
def test_steps_that_raise_after_allocation_exit_4_with_one_diagnostic(tmp_path, pipes, kind):  # I1 (c), (e)
    report = pipes["report_write"]
    io = pipes["io"]
    io.prelude = RAISING_STEPS.format(kind=kind)
    io.epilogue = REPORT_FD_CLOSED.format(fd=report)
    status, _ = autonomy(tmp_path, [*RUN, "--report-fd", str(report), *ACTOR], io)
    assert status == 4
    (run_dir,) = runs(tmp_path)
    assert not (run_dir / "disposition.json").exists()  # left for run close
    said = drain(pipes["err"]).decode().splitlines()
    assert said[0].startswith("autonomy: run ")  # the run's own line
    (failure,) = said[1:]
    assert kind in failure and "steps failed after allocation" in failure and run_dir.name in failure
    os.close(pipes["report_write"])
    (first,) = read_all(pipes["report"]).decode().splitlines()  # the first line, then EOF
    assert json.loads(first)["run"] == run_dir.name


RAISING_PLACES = """
import autonomy.run as run
def places(env):
    raise RuntimeError("places failed\\nbefore allocation")
run.places = places
"""


def test_an_unexpected_error_before_allocation_exits_2_with_one_diagnostic(tmp_path, pipes):
    report = pipes["report_write"]
    io = pipes["io"]
    io.prelude = RAISING_PLACES
    status, _ = autonomy(tmp_path, [*RUN, "--report-fd", str(report), *ACTOR], io)
    assert status == 2
    assert runs(tmp_path) == [] and scratches(tmp_path) == []
    (failure,) = drain(pipes["err"]).decode().splitlines()
    assert failure == "autonomy: failed: RuntimeError: places failed before allocation"
    os.close(pipes["report_write"])
    assert read_all(pipes["report"]) == b""


@pytest.mark.parametrize("value", ["99999999999", "2147483648", "\u0663", "-1"])
def test_a_report_fd_that_is_not_a_descriptor_number_is_a_usage_error(tmp_path, pipes, value):  # I1 (d), M2
    status, _ = autonomy(tmp_path, [*RUN, "--report-fd", value, *ACTOR], pipes["io"])
    assert status == 2 and runs(tmp_path) == []
    said = drain(pipes["err"])
    assert b"is not a descriptor number" in said and b"Traceback" not in said


@pytest.mark.parametrize("args", [
    ["run", "--tier", "t" * 9000, *ACTOR],  # a refusal naming the tier
    [*RUN, "--lease", "9" * 8999 + "x", *ACTOR],  # argparse's usage error quoting the value
])
def test_a_long_diagnostic_is_truncated_to_one_write(tmp_path, pipes, args):  # M3, Review Focus 4
    status, _ = autonomy(tmp_path, args, pipes["io"])
    assert status == 2
    said = drain(pipes["err"])
    assert said.endswith(b"\n")
    lines = said.splitlines()
    assert all(len(line) + 1 <= 4096 for line in lines)
    assert max(len(line) for line in lines) == 4095  # the long one, cut to one write


def test_the_diagnostic_channel_is_closed_before_exit(tmp_path, pipes, held):  # M1
    mine, theirs = socket.socketpair()
    held.extend([mine, theirs])
    io = pipes["io"]
    io.stderr = mine.fileno()
    io.env = {**environment(tmp_path), "PYTHONDEVMODE": "1"}
    status, _ = autonomy(tmp_path, [*RUN, *ACTOR], io)
    assert status == 4
    said = drain(theirs.fileno())
    assert b"closed unwired" in said and b"ResourceWarning" not in said


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
