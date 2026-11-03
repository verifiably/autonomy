import dataclasses
import hashlib
import json
import os
import shutil
import stat
import time
from pathlib import Path

import pytest

from autonomy.analyst.launch import CommandRequest, Progress, command_env, execute_command, refuse_command
from autonomy.analyst.toolchain import AnalystRefused
from autonomy.sandbox.static import SandboxUnproven
from egress_fixtures import pi_route, write_credential, write_route

bwrap = pytest.mark.bwrap


@pytest.fixture
def cmd_world(tmp_path):
    config = tmp_path / "config/verifiably-autonomy"
    ext_secret = tmp_path / "external_creds/anthropic.key"
    write_credential(ext_secret, "placeholder-not-a-key")
    write_route(config, "pi", pi_route(credential=ext_secret, upstream="https://localhost:1"))
    # Also plant a broken route to verify refuse_command ignores malformed route files
    (config / "routes").mkdir(parents=True, exist_ok=True)
    (config / "routes/broken.toml").write_text("not = [valid toml\n")
    env = {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "PATH": "/usr/bin",
    }
    for name in ("home", "bundle", "release", "key", "code"):
        (tmp_path / name).mkdir()
    (tmp_path / "key/k.json").write_text("{}")
    (tmp_path / "bundle/data.tsv").write_text("a\t1\n")
    disjoint = tmp_path / "disjoint.json"
    disjoint.write_text('{"cohort": 1}\n')
    script = tmp_path / "code/entry.py"
    script.write_text("#!/usr/bin/python3\nprint('ok')\n")
    script.chmod(0o755)
    request = CommandRequest(
        inputs=(tmp_path / "bundle", disjoint, tmp_path / "code"),
        denied=(tmp_path / "key",),
        release_dir=tmp_path / "release",
        argv=("/usr/bin/python3", "-I", str(script)),
        workdir=tmp_path / "code",
    )
    return {
        "env": env,
        "tmp": tmp_path,
        "request": request,
        "disjoint": disjoint,
        "script": script,
        "ext_secret": ext_secret,
    }


def test_a_complete_command_request_is_prepared(cmd_world):
    prepared = refuse_command(cmd_world["request"], cmd_world["env"])
    tmp = cmd_world["tmp"]
    assert prepared.inputs == (
        (tmp / "bundle").resolve(),
        cmd_world["disjoint"].resolve(),
        (tmp / "code").resolve(),
    )
    assert prepared.input_kinds == ("directory", "file", "directory")
    assert prepared.workdir == (tmp / "code").resolve()
    assert prepared.executable_path == Path("/usr/bin/python3")
    assert prepared.executable_realpath == Path("/usr/bin/python3").resolve()
    assert prepared.executable_sha256 == hashlib.sha256(Path("/usr/bin/python3").resolve().read_bytes()).hexdigest()
    assert (tmp / "key").resolve() in prepared.denied
    assert cmd_world["ext_secret"].resolve() in prepared.denied
    assert prepared.places.config.resolve(strict=False) in prepared.denied
    assert prepared.places.state.resolve(strict=False) in prepared.denied
    assert prepared.release_dir in prepared.denied
    assert "bwrap" in prepared.bwrap or "version" in prepared.bwrap
    scratch = tmp / "scratch"
    assert command_env(scratch) == {
        "PATH": "/usr/bin",
        "HOME": str(scratch / "home"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "VERIFIABLY_SCRATCH": str(scratch),
        "VERIFIABLY_OUTPUTS": str(scratch / "outputs"),
    }
    if Path("/bin").is_symlink() and Path("/bin/sh").exists():
        sh_prep = refuse_command(dataclasses.replace(cmd_world["request"], argv=("/bin/sh", "-c", "true")), cmd_world["env"])
        assert sh_prep.executable_path == Path("/bin/sh")
        assert sh_prep.executable_realpath == Path("/bin/sh").resolve()


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda w: {"deadline": 0.0}, "deadline-invalid"),
        (lambda w: {"deadline": -5.0}, "deadline-invalid"),
        (lambda w: {"deadline": float("nan")}, "deadline-invalid"),
        (lambda w: {"inputs": ()}, "input-missing"),
        (lambda w: {"inputs": (w["tmp"] / "absent",)}, "input-missing"),
        (lambda w: {"inputs": (w["tmp"] / "fifo_in",)}, "input-unsupported"),
        (lambda w: {"inputs": (w["tmp"] / "bundle", w["tmp"] / "bundle")}, "input-nested"),
        (lambda w: {"inputs": (w["tmp"] / "bundle", w["tmp"] / "bundle/data.tsv")}, "input-nested"),
        (lambda w: {"inputs": (Path("/usr"),)}, "input-nested"),
        (lambda w: {"inputs": (Path("/etc"),)}, "input-nested"),
        (lambda w: {"workdir": w["tmp"] / "absent"}, "workdir-invalid"),
        (lambda w: {"workdir": w["disjoint"]}, "workdir-invalid"),
        (lambda w: {"workdir": w["tmp"] / "home"}, "workdir-unbound"),
        (lambda w: {"argv": ()}, "command-missing"),
        (lambda w: {"argv": (str(w["tmp"] / "code/missing"),)}, "command-missing"),
        (lambda w: {"argv": (str(w["tmp"] / "code"),)}, "command-missing"),
        (lambda w: {"argv": ("python3",)}, "command-invalid"),
        (lambda w: {"argv": ("/usr//bin/python3",)}, "command-invalid"),
        (lambda w: {"argv": ("/usr/bin/../bin/python3",)}, "command-invalid"),
        (lambda w: {"argv": ("/usr/bin/./python3",)}, "command-invalid"),
        (lambda w: {"argv": ("/usr/bin/python3/",)}, "command-invalid"),
        (lambda w: {"argv": (str(w["tmp"] / "code_link/entry.py"),)}, "command-invalid"),
        (lambda w: {"argv": (str(w["tmp"] / "bundle/data.tsv"),)}, "command-not-executable"),
        (lambda w: {"argv": (str(w["tmp"] / "unlisted_exec"),)}, "command-unbound"),
        (lambda w: {"inputs": (w["tmp"] / "key",), "workdir": None}, "bind-overlaps-denied"),
        (lambda w: {"release_dir": w["tmp"] / "bundle"}, "release-unusable"),
        (lambda w: {"release_dir": w["tmp"] / "absent"}, "release-unusable"),
    ],
)
def test_each_command_configuration_refusal_is_typed_and_keeps_nothing(cmd_world, change, code):
    tmp = cmd_world["tmp"]
    fifo_in = tmp / "fifo_in"
    if not fifo_in.exists():
        os.mkfifo(fifo_in)
    code_link = tmp / "code_link"
    if not code_link.exists():
        code_link.symlink_to(tmp / "code")
    unlisted = tmp / "unlisted_exec"
    if not unlisted.exists():
        unlisted.write_text("#!/bin/sh\nexit 0\n")
        unlisted.chmod(0o755)

    request = dataclasses.replace(cmd_world["request"], **change(cmd_world))
    with pytest.raises(AnalystRefused) as caught:
        refuse_command(request, cmd_world["env"])
    assert caught.value.code == code
    assert not (tmp / "state").exists() and not (tmp / "cache").exists()


@pytest.mark.skipif(os.getuid() == 0, reason="root ignores directory modes")
def test_a_denied_path_that_cannot_be_stat_ed_is_refused_in_command(cmd_world):
    locked = cmd_world["tmp"] / "locked"
    locked.mkdir()
    (locked / "k").write_text("")
    locked.chmod(0o000)
    try:
        with pytest.raises(AnalystRefused) as caught:
            refuse_command(dataclasses.replace(cmd_world["request"], denied=(locked / "k",)), cmd_world["env"])
        assert caught.value.code == "denied-unreadable"
    finally:
        locked.chmod(0o700)


def test_caller_terminal_or_file_on_stdio_is_permitted_while_report_fd_exclusions_hold(cmd_world, tmp_path):
    reg_fd = os.open(tmp_path / "caller_stdio.log", os.O_RDWR | os.O_CREAT, 0o600)
    r_pipe, w_pipe = os.pipe()
    err_r, err_w = os.pipe()
    dup_w = os.dup(w_pipe)
    try:
        # Caller regular files on fds 0-2 are permitted for autonomy command
        prepared = refuse_command(cmd_world["request"], cmd_world["env"], stdio_fds=(reg_fd, reg_fd, reg_fd))
        assert prepared.executable_path == Path("/usr/bin/python3")

        # But report_fd equal to one of stdio_fds (e.g. --report-fd 1) is refused
        req_same_fd = dataclasses.replace(cmd_world["request"], report_fd=w_pipe)
        with pytest.raises(AnalystRefused) as caught:
            refuse_command(req_same_fd, cmd_world["env"], stdio_fds=(r_pipe, w_pipe, err_w))
        assert caught.value.code == "stdio-refused"

        # And report_fd duplicated from one of stdio_fds is refused
        req_dup_fd = dataclasses.replace(cmd_world["request"], report_fd=dup_w)
        with pytest.raises(AnalystRefused) as caught:
            refuse_command(req_dup_fd, cmd_world["env"], stdio_fds=(r_pipe, w_pipe, err_w))
        assert caught.value.code == "stdio-refused"
    finally:
        for fd in (reg_fd, r_pipe, w_pipe, err_r, err_w, dup_w):
            os.close(fd)


def test_chained_and_relative_venv_symlinks_discover_recreated_directory_link(cmd_world):
    tmp = cmd_world["tmp"]
    real_py = tmp / "uv/cpython-3.13.12"
    (real_py / "bin").mkdir(parents=True)
    py_bin = real_py / "bin/python3.13"
    shutil.copy2("/usr/bin/python3", py_bin)
    py_bin.chmod(0o755)

    link_py = tmp / "uv/cpython-3.13"
    link_py.symlink_to(real_py)

    venv = tmp / "venv"
    (venv / "bin").mkdir(parents=True)
    # Chained relative symlinks: venv/bin/python -> python3 -> ../../uv/cpython-3.13/bin/python3.13
    (venv / "bin/python").symlink_to("python3")
    (venv / "bin/python3").symlink_to("../../uv/cpython-3.13/bin/python3.13")
    (venv / "pyvenv.cfg").write_text(f"home = {link_py / 'bin'}\n")

    req_ok = dataclasses.replace(
        cmd_world["request"],
        inputs=(venv, real_py, tmp / "code"),
        argv=(str(venv / "bin/python"), "-I", str(cmd_world["script"])),
    )
    prepared = refuse_command(req_ok, cmd_world["env"])
    assert prepared.symlinks == ((real_py.resolve(), link_py),)

    # Omitting real_py from inputs refuses command-unbound
    req_unbound = dataclasses.replace(
        cmd_world["request"],
        inputs=(venv, tmp / "code"),
        argv=(str(venv / "bin/python"), "-I", str(cmd_world["script"])),
    )
    with pytest.raises(AnalystRefused) as caught:
        refuse_command(req_unbound, cmd_world["env"])
    assert caught.value.code == "command-unbound"


@bwrap
def test_command_clean_run_records_epoch_input_digests_and_stdio_logs(cmd_world):
    report_r, report_w = os.pipe()
    cmd_world["script"].write_text(
        "import os, sys\n"
        "from pathlib import Path\n"
        "assert os.read(0, 1) == b''\n"
        "Path('/run/va/outputs/out.txt').write_text('via-fixed\\n')\n"
        "Path(os.environ['VERIFIABLY_OUTPUTS'], 'out2.txt').write_text('via-env\\n')\n"
        "print('hello-stdout')\n"
        "print('hello-stderr', file=sys.stderr)\n"
    )
    request = dataclasses.replace(cmd_world["request"], report_fd=report_w)
    diags: list[str] = []
    progress = Progress()
    code = execute_command(request, cmd_world["env"], diag=diags.append, progress=progress)
    assert code == 0

    # report_w was closed by execute_command
    with pytest.raises(OSError):
        os.fstat(report_w)
    raw_report = b""
    while chunk := os.read(report_r, 65536):
        raw_report += chunk
    os.close(report_r)
    lines = [json.loads(line) for line in raw_report.decode().splitlines()]
    assert len(lines) == 2
    assert lines[0]["run_dir"] == str(progress.run_dir)
    assert lines[1] == {
        "run": progress.run_dir.name,
        "exit": 0,
        "command_exit": 0,
        "released": 2,
        "refused": 0,
    }

    run_dir = progress.run_dir
    assert (cmd_world["tmp"] / "release/out.txt").read_text() == "via-fixed\n"
    assert (cmd_world["tmp"] / "release/out2.txt").read_text() == "via-env\n"
    assert (run_dir / "stdout.log").read_bytes() == b"hello-stdout\n"
    assert (run_dir / "stderr.log").read_bytes() == b"hello-stderr\n"
    assert stat.S_IMODE((run_dir / "stdout.log").stat().st_mode) == 0o600
    assert stat.S_IMODE((run_dir / "stderr.log").stat().st_mode) == 0o600
    assert not (run_dir / "egress.jsonl").exists()
    assert not (run_dir / "proxy.log").exists()

    epoch = json.loads((run_dir / "epoch.json").read_text())
    walked = json.loads((run_dir / "walk.json").read_text())
    assert epoch["inputs"] == walked["inputs"]
    assert len(epoch["inputs"]) == 3
    assert all(len(item["sha256"]) == 64 for item in epoch["inputs"])
    assert epoch["argv"] == list(request.argv)
    assert len(epoch["argv_sha256"]) == 64
    assert epoch["workdir"] == str((cmd_world["tmp"] / "code").resolve())

    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    assert [e["event"] for e in events] == ["allocated", "proved", "launched", "closed"]
    closed = events[-1]
    assert closed["stdout"]["bytes"] == len(b"hello-stdout\n")
    assert closed["stderr"]["bytes"] == len(b"hello-stderr\n")
    assert closed["timed_out"] is False and closed["signal"] is None


@bwrap
def test_command_timeout_and_large_stdio_do_not_deadlock_and_record_digests(cmd_world):
    # 1. Large stdio (256 KiB each on stdout and stderr)
    cmd_world["script"].write_text(
        "import sys\n"
        "sys.stdout.buffer.write(b'O' * (256 * 1024))\n"
        "sys.stdout.buffer.flush()\n"
        "sys.stderr.buffer.write(b'E' * (256 * 1024))\n"
        "sys.stderr.buffer.flush()\n"
    )
    p1 = Progress()
    code1 = execute_command(cmd_world["request"], cmd_world["env"], diag=lambda _: None, progress=p1)
    assert code1 == 0
    closed1 = json.loads((p1.run_dir / "events.jsonl").read_text().splitlines()[-1])
    assert closed1["stdout"]["bytes"] == 256 * 1024
    assert closed1["stderr"]["bytes"] == 256 * 1024
    assert closed1["stdout"]["sha256"] == hashlib.sha256(b"O" * (256 * 1024)).hexdigest()
    assert closed1["stderr"]["sha256"] == hashlib.sha256(b"E" * (256 * 1024)).hexdigest()

    # 2. Deadline timeout
    cmd_world["script"].write_text("import time\ntime.sleep(60)\n")
    p2 = Progress()
    req_timeout = dataclasses.replace(cmd_world["request"], deadline=1.0)
    code2 = execute_command(req_timeout, cmd_world["env"], diag=lambda _: None, progress=p2)
    assert code2 == 3
    closed2 = json.loads((p2.run_dir / "events.jsonl").read_text().splitlines()[-1])
    assert closed2["timed_out"] is True and closed2["exit"] == 3


@bwrap
def test_command_failed_walk_or_launch_exits_4_and_closes_report_fd(cmd_world, monkeypatch):
    import autonomy.analyst.launch as launch_module

    # 1. Hard-link inside --input fails walk with exit 4 and closes report_fd
    hard = cmd_world["tmp"] / "hard_link.tsv"
    os.link(cmd_world["tmp"] / "bundle/data.tsv", hard)
    r1, w1 = os.pipe()
    p1 = Progress()
    try:
        code1 = execute_command(
            dataclasses.replace(cmd_world["request"], report_fd=w1),
            cmd_world["env"],
            diag=lambda _: None,
            progress=p1,
        )
        assert code1 == 4
        with pytest.raises(OSError):
            os.fstat(w1)
        lines1 = [json.loads(line) for line in os.read(r1, 65536).decode().splitlines()]
        assert len(lines1) == 1
        events1 = [json.loads(line) for line in (p1.run_dir / "events.jsonl").read_text().splitlines()]
        assert events1[-1]["event"] == "unproven" and events1[-1]["code"] == "walk-hardlink"
        epoch1 = json.loads((p1.run_dir / "epoch.json").read_text())
        assert all(item["sha256"] is None for item in epoch1["inputs"])
    finally:
        os.close(r1)
        hard.unlink()

    # 2. SandboxUnproven raised from launch() maps to exit 4 and closes report_fd
    def fail_launch(*args, **kwargs):
        raise SandboxUnproven("launch-failed", "bwrap", "boom")

    monkeypatch.setattr(launch_module, "launch", fail_launch)
    r2, w2 = os.pipe()
    p2 = Progress()
    try:
        code2 = execute_command(
            dataclasses.replace(cmd_world["request"], report_fd=w2),
            cmd_world["env"],
            diag=lambda _: None,
            progress=p2,
        )
        assert code2 == 4
        with pytest.raises(OSError):
            os.fstat(w2)
        events2 = [json.loads(line) for line in (p2.run_dir / "events.jsonl").read_text().splitlines()]
        assert events2[-1]["event"] == "unproven"
        assert events2[-1]["code"] == "launch-failed" and events2[-1]["path"] == "launch"
    finally:
        os.close(r2)


def _alive(pid: int, start_time: int | None) -> bool:
    try:
        stat_ = Path(f"/proc/{pid}/stat").read_bytes()
    except FileNotFoundError:
        return False
    return start_time is None or int(stat_.rsplit(b")", 1)[1].split()[19]) == start_time


@bwrap
def test_a_failure_after_launch_still_kills_the_command_and_closes_report_fd(cmd_world, monkeypatch):
    import autonomy.analyst.launch as launch_module

    actors = []
    real_launch = launch_module.launch

    def recording_launch(*args, **kwargs):
        actor = real_launch(*args, **kwargs)
        actors.append(actor)
        return actor

    def boom(actor, deadline, log):
        raise RuntimeError("supervision failed")

    monkeypatch.setattr(launch_module, "launch", recording_launch)
    monkeypatch.setattr(launch_module, "_supervise_command", boom)

    cmd_world["script"].write_text("import time\ntime.sleep(60)\n")
    report_r, report_w = os.pipe()
    progress = Progress()
    try:
        with pytest.raises(RuntimeError, match="supervision failed"):
            execute_command(
                dataclasses.replace(cmd_world["request"], report_fd=report_w),
                cmd_world["env"],
                diag=lambda _: None,
                progress=progress,
            )
        with pytest.raises(OSError):
            os.fstat(report_w)
        assert len(actors) == 1 and actors[0].pidfd == -1
        events = [json.loads(line) for line in (progress.run_dir / "events.jsonl").read_text().splitlines()]
        launched = next(e for e in events if e["event"] == "launched")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and _alive(launched["child_pid"], launched["start_time"]):
            time.sleep(0.1)
        assert not _alive(launched["child_pid"], launched["start_time"])
    finally:
        os.close(report_r)
        del actors[:]
