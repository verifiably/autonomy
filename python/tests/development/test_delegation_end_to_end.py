import errno
import fcntl
import json
import os
import pty
import secrets
import select
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from autonomy.baseline import publish_bytes
from development.test_integration import ACTOR
from development.test_workspace import fixture_git, make_source
from user_manager import in_delegated_unit, stop_unit, unit_env, user_manager, with_passwd_home  # noqa: F401

pytestmark = [pytest.mark.user_manager, pytest.mark.bwrap]

AUTONOMY = Path(sys.prefix) / "bin" / "autonomy"
_TMPFS_MAGIC = 0x01021994


@pytest.fixture
def disk_root(tmp_path: Path) -> Path:
    # Ensure ext4/xfs/btrfs backing for allowance-storage.json qualification.
    buf_type = os.statvfs(tmp_path).f_bsize
    assert buf_type > 0
    root = tmp_path / "e2e"
    root.mkdir(mode=0o700)
    return root


def _clean_env_argv(account_home: Path, state_dir: Path, cache_dir: Path, extra_env: dict[str, str] | None = None) -> list[str]:
    pairs = {
        "PATH": "/usr/bin",
        "HOME": str(account_home),
        "LC_ALL": "C",
        "XDG_STATE_HOME": str(state_dir),
        "XDG_CACHE_HOME": str(cache_dir),
        "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
    }
    if extra_env:
        pairs.update(extra_env)
    return ["/usr/bin/env", "-i", *[f"{k}={v}" for k, v in pairs.items()]]


def _wrapped_autonomy(
    account_home: Path,
    state_dir: Path,
    cache_dir: Path,
    args: list[str],
    *,
    extra_env: dict[str, str] | None = None,
) -> list[str]:
    assert AUTONOMY.is_file(), f"installed autonomy binary missing at {AUTONOMY}"
    return with_passwd_home(
        account_home,
        [*_clean_env_argv(account_home, state_dir, cache_dir, extra_env), str(AUTONOMY), *args],
    )


def _setup_e2e_account(root: Path) -> dict[str, Path | str]:
    root.mkdir(parents=True, exist_ok=True)
    account_home = root / "account-home"
    config_dir = account_home / ".config/verifiably-autonomy"
    (config_dir / "delegations").mkdir(parents=True, mode=0o700)
    store_dir = root / "store"
    store_dir.mkdir(mode=0o700)
    st = store_dir.stat()
    publish_bytes(
        config_dir / "allowance-storage.json",
        json.dumps({"version": 1, "path": str(store_dir), "device": st.st_dev, "inode": st.st_ino}).encode("utf-8"),
    )
    state_dir = root / "state"
    cache_dir = root / "cache"
    state_dir.mkdir(mode=0o700)
    cache_dir.mkdir(mode=0o700)
    repo_dir = root / "repo"
    make_source(repo_dir)
    tip = fixture_git(repo_dir, "rev-parse", "refs/heads/main")
    return {
        "account_home": account_home,
        "config_dir": config_dir,
        "store_dir": store_dir,
        "state_dir": state_dir,
        "cache_dir": cache_dir,
        "repo_dir": repo_dir,
        "tip": tip,
    }


def _issue_via_pty(
    fx: dict,
    name: str,
    *,
    delegation_id: str,
    unit: str,
    actors: dict[str, list[str]],
    starts: int = 4,
    deadline_seconds: int = 30,
    writable_bytes: int = 96 << 20,
    memory_bytes: int = 416 << 20,
    tasks: int = 64,
) -> dict:
    config_dir = Path(fx["config_dir"])
    repo_dir = Path(fx["repo_dir"])
    doc = {
        "kind": "development-delegation.v1",
        "delegation_id": delegation_id,
        "source": "autonomy-a22882 e2e",
        "expires": int(time.time()) + 3600,
        "orchestrator": {"name": "e2e", "unit": unit},
        "repositories": {"repo": {"path": str(repo_dir), "ref": "refs/heads/main"}},
        "actors": actors,
        "limits": {
            "starts": starts,
            "deadline_seconds": deadline_seconds,
            "writable_bytes": writable_bytes,
            "memory_bytes": memory_bytes,
            "tasks": tasks,
        },
        "model": None,
    }
    publish_bytes(config_dir / "delegations" / f"{name}.json", (json.dumps(doc) + "\n").encode("utf-8"))

    cmd = _wrapped_autonomy(
        Path(fx["account_home"]),
        Path(fx["state_dir"]),
        Path(fx["cache_dir"]),
        ["delegation", "issue", name],
    )
    out_r, out_w = os.pipe()
    err_r, err_w = os.pipe()
    pid, master_fd = pty.fork()
    if pid == 0:
        try:
            os.close(out_r)
            os.close(err_r)
            os.dup2(out_w, 1)
            os.dup2(err_w, 2)
            os.close(out_w)
            os.close(err_w)
            os.execve(cmd[0], cmd, unit_env(Path(fx["account_home"])))
        except BaseException:
            os._exit(99)

    os.close(out_w)
    os.close(err_w)
    try:
        buf = b""
        deadline = time.monotonic() + 15.0
        while b"confirm:" not in buf:
            rem = deadline - time.monotonic()
            assert rem > 0, f"issue prompt timeout; got {buf!r}"
            if select.select([master_fd], [], [], rem)[0]:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                buf += chunk
        os.write(master_fd, (delegation_id + "\n").encode("ascii"))
        while True:
            if not select.select([master_fd], [], [], 0.2)[0]:
                break
            try:
                if not os.read(master_fd, 4096):
                    break
            except OSError:
                break
        _, status = os.waitpid(pid, 0)
        stdout = os.read(out_r, 65536)
        stderr = os.read(err_r, 65536)
        assert os.waitstatus_to_exitcode(status) == 0, stderr.decode("utf-8", "replace")
        return json.loads(stdout.decode("utf-8"))
    finally:
        os.close(master_fd)
        os.close(out_r)
        os.close(err_r)


def _unit_cgroup_dir(unit: str, account_home: Path) -> Path:
    res = subprocess.run(
        ["/usr/bin/systemctl", "--no-pager", "--user", "show", "-p", "ControlGroup", "--value", "--", unit],
        env=unit_env(account_home),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    rel = res.stdout.strip().lstrip("/")
    if rel:
        return Path("/sys/fs/cgroup") / rel
    uid = os.getuid()
    return Path(f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/{unit}")


def _run_outside(fx: dict, args: list[str], *, timeout: float = 35.0) -> subprocess.CompletedProcess:
    cmd = _wrapped_autonomy(
        Path(fx["account_home"]),
        Path(fx["state_dir"]),
        Path(fx["cache_dir"]),
        args,
    )
    return subprocess.run(
        cmd,
        env=unit_env(Path(fx["account_home"])),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


_ISOLATION_PROVED = False


def test_the_operators_store_is_not_reachable(disk_root, user_manager):
    global _ISOLATION_PROVED
    fx = _setup_e2e_account(disk_root)
    account_home = Path(fx["account_home"])
    expected = str(account_home / ".config/verifiably-autonomy")
    real_operator = str(Path.home() / ".config/verifiably-autonomy")
    assert expected != real_operator

    probe = [
        *_clean_env_argv(account_home, Path(fx["state_dir"]), Path(fx["cache_dir"])),
        sys.executable,
        "-c",
        "from autonomy.delegation import current_host; print(current_host().config)",
    ]
    outside = subprocess.run(
        with_passwd_home(account_home, probe),
        env=unit_env(account_home),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    assert outside.stdout.strip() == expected

    unit = f"autonomy-e2e-iso-{secrets.token_hex(6)}.service"
    try:
        inside = subprocess.run(
            in_delegated_unit(with_passwd_home(account_home, probe), unit=unit),
            env=unit_env(account_home),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
    finally:
        stop_unit(unit, account_home)
    assert inside.stdout.strip() == expected
    _ISOLATION_PROVED = True


@pytest.fixture
def isolated_e2e(disk_root, user_manager):
    if not _ISOLATION_PROVED:
        test_the_operators_store_is_not_reachable(disk_root / "guard-check", user_manager)
    return _setup_e2e_account(disk_root)


def test_d1_clean_delegated_run_and_outside_report(isolated_e2e):
    fx = isolated_e2e
    account_home = Path(fx["account_home"])
    unit = f"autonomy-e2e-d1-{secrets.token_hex(6)}.service"
    _issue_via_pty(
        fx,
        "d1",
        delegation_id="del-d1",
        unit=unit,
        actors={"candidate": ["/usr/bin/sh", "-c", ACTOR]},
        starts=2,
    )
    run_cmd = _wrapped_autonomy(
        account_home,
        Path(fx["state_dir"]),
        Path(fx["cache_dir"]),
        [
            "run", "--development",
            "--delegation", "del-d1",
            "--attempt", "att-1",
            "--repository", str(fx["repo_dir"]),
            "--base", str(fx["tip"]),
            "--deadline", "25",
            "--", "/usr/bin/sh", "-c", ACTOR,
        ],
    )
    try:
        res = subprocess.run(
            in_delegated_unit(run_cmd, unit=unit),
            env=unit_env(account_home),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=45,
        )
    finally:
        stop_unit(unit, account_home)
    assert res.returncode == 0, res.stderr

    rep = _run_outside(fx, ["delegation", "report", "del-d1"])
    assert rep.returncode == 0, rep.stderr
    doc = json.loads(rep.stdout)
    assert doc["starts_left"] == 1
    assert len(doc["starts"]) == 1
    start = doc["starts"][0]
    assert start["outcome"] == "clean"
    run_dir = Path(fx["state_dir"]) / "verifiably-autonomy/runs" / start["run"]
    disp = json.loads((run_dir / "disposition.json").read_text(encoding="utf-8"))
    assert disp["version"] == 2 and disp["containment_proven"] is True
    uid = os.getuid()
    actor_cg = Path(f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/{unit}/actor-{start['run']}")
    assert not actor_cg.exists()


def test_d4_revoke_against_stopped_supervisor_and_held_publication_lock(isolated_e2e):
    fx = isolated_e2e
    account_home = Path(fx["account_home"])
    sleep_actor = ["/usr/bin/sh", "-c", "printf 'actor-up\\n' && exec /usr/bin/sleep 60"]

    # Arm A: SIGSTOP supervisor while actor runs -> revoke acknowledged (exit 0), actor cgroup empty/gone
    unit_a = f"autonomy-e2e-d4a-{secrets.token_hex(6)}.service"
    _issue_via_pty(fx, "d4a", delegation_id="del-d4a", unit=unit_a, actors={"sleep": sleep_actor}, starts=2, deadline_seconds=60)
    cmd_a = _wrapped_autonomy(
        account_home, Path(fx["state_dir"]), Path(fx["cache_dir"]),
        [
            "run", "--development", "--delegation", "del-d4a", "--attempt", "att-a",
            "--repository", str(fx["repo_dir"]), "--base", str(fx["tip"]), "--deadline", "45",
            "--", *sleep_actor,
        ],
    )
    proc_a = subprocess.Popen(
        in_delegated_unit(cmd_a, unit=unit_a),
        env=unit_env(account_home),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stopped_pids: list[int] = []
    try:
        assert proc_a.stdout.readline().strip() == "actor-up"
        unit_cg_a = _unit_cgroup_dir(unit_a, account_home)
        main_procs = [int(p) for p in (unit_cg_a / "main/cgroup.procs").read_text().split()]
        assert main_procs
        for pid in main_procs:
            os.kill(pid, signal.SIGSTOP)
            stopped_pids.append(pid)
        actor_dirs = list(unit_cg_a.glob("actor-*"))
        assert len(actor_dirs) == 1 and actor_dirs[0].joinpath("cgroup.procs").read_text().strip() != ""

        rev_a = _run_outside(fx, ["delegation", "revoke", "del-d4a"], timeout=35.0)
        assert rev_a.returncode == 0, rev_a.stderr
        rev_doc_a = json.loads(rev_a.stdout)
        assert rev_doc_a["acknowledged"] is True and rev_doc_a["actor"] == "empty"
        assert actor_dirs[0].joinpath("cgroup.procs").read_text().strip() == ""
    finally:
        for pid in stopped_pids:
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        stop_unit(unit_a, account_home)
        proc_a.kill()
        proc_a.wait(timeout=10)

    # Arm B: supervisor stopped while publication.lock is held -> exit 2 (unacknowledged), actor ended
    unit_b = f"autonomy-e2e-d4b-{secrets.token_hex(6)}.service"
    _issue_via_pty(fx, "d4b", delegation_id="del-d4b", unit=unit_b, actors={"sleep": sleep_actor}, starts=2, deadline_seconds=60)
    cmd_b = _wrapped_autonomy(
        account_home, Path(fx["state_dir"]), Path(fx["cache_dir"]),
        [
            "run", "--development", "--delegation", "del-d4b", "--attempt", "att-b",
            "--repository", str(fx["repo_dir"]), "--base", str(fx["tip"]), "--deadline", "45",
            "--", *sleep_actor,
        ],
    )
    proc_b = subprocess.Popen(
        in_delegated_unit(cmd_b, unit=unit_b),
        env=unit_env(account_home),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stopped_b: list[int] = []
    lock_fd = -1
    try:
        assert proc_b.stdout.readline().strip() == "actor-up"
        unit_cg_b = _unit_cgroup_dir(unit_b, account_home)
        actor_dirs_b = list(unit_cg_b.glob("actor-*"))
        assert len(actor_dirs_b) == 1
        run_id_b = actor_dirs_b[0].name.removeprefix("actor-")
        pub_lock_path = Path(fx["state_dir"]) / "verifiably-autonomy/runs" / run_id_b / "publication.lock"
        lock_fd = os.open(pub_lock_path, os.O_RDONLY | os.O_CLOEXEC)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        for pid in [int(p) for p in (unit_cg_b / "main/cgroup.procs").read_text().split()]:
            os.kill(pid, signal.SIGSTOP)
            stopped_b.append(pid)

        rev_b = _run_outside(fx, ["delegation", "revoke", "del-d4b"], timeout=35.0)
        assert rev_b.returncode == 2
        rev_doc_b = json.loads(rev_b.stdout)
        assert rev_doc_b["acknowledged"] is False and rev_doc_b["actor"] == "empty"
        assert "delegation-stop-unacknowledged" in rev_b.stderr
        assert actor_dirs_b[0].joinpath("cgroup.procs").read_text().strip() == ""
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)
        for pid in stopped_b:
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        stop_unit(unit_b, account_home)
        proc_b.kill()
        proc_b.wait(timeout=10)


def test_d6_kill_supervisor_after_cgroup_join_before_release(isolated_e2e):
    fx = isolated_e2e
    account_home = Path(fx["account_home"])
    repo_dir = Path(fx["repo_dir"])
    # Add 400 small files to widen the hold_storage + seed_scratch window between cgroup join and gate release.
    seed_dir = repo_dir / "seed-padding"
    seed_dir.mkdir()
    for idx in range(400):
        (seed_dir / f"f{idx}.txt").write_bytes(b"x" * 8192)
    fixture_git(repo_dir, "add", "seed-padding")
    fixture_git(repo_dir, "commit", "-m", "seed padding")
    tip = fixture_git(repo_dir, "rev-parse", "refs/heads/main")
    fx["tip"] = tip

    unit = f"autonomy-e2e-d6-{secrets.token_hex(6)}.service"
    _issue_via_pty(fx, "d6", delegation_id="del-d6", unit=unit, actors={"true": ["/usr/bin/true"]}, starts=2)
    cmd = _wrapped_autonomy(
        account_home, Path(fx["state_dir"]), Path(fx["cache_dir"]),
        [
            "run", "--development", "--delegation", "del-d6", "--attempt", "att-d6",
            "--repository", str(repo_dir), "--base", tip, "--deadline", "25",
            "--", "/usr/bin/true",
        ],
    )
    uid = os.getuid()
    unit_cg = Path(f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/{unit}")
    proc = subprocess.Popen(
        in_delegated_unit(cmd, unit=unit),
        env=unit_env(account_home),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    killed_run_id = None
    try:
        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline and proc.poll() is None:
            for actor_cg in unit_cg.glob("actor-*"):
                try:
                    procs = (actor_cg / "cgroup.procs").read_text().split()
                except OSError:
                    continue
                if procs:
                    killed_run_id = actor_cg.name.removeprefix("actor-")
                    for sup_pid in (unit_cg / "main/cgroup.procs").read_text().split():
                        try:
                            os.kill(int(sup_pid), signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    break
            if killed_run_id is not None:
                break
            time.sleep(0.001)
        proc.wait(timeout=10)
    finally:
        stop_unit(unit, account_home)

    assert killed_run_id is not None, "did not observe launcher joining actor cgroup"
    close_res = _run_outside(fx, ["run", "close", killed_run_id])
    assert close_res.returncode == 4, close_res.stderr
    rep = _run_outside(fx, ["delegation", "report", "del-d6"])
    assert rep.returncode == 0, rep.stderr
    doc = json.loads(rep.stdout)
    assert doc["closed"] is None
    assert doc["starts"][0]["outcome"] == "unwired"
    assert not (unit_cg / f"actor-{killed_run_id}").exists()


def test_d7_actor_bounds_and_unit_misconfigurations(isolated_e2e):
    fx = isolated_e2e
    account_home = Path(fx["account_home"])
    repo_dir = Path(fx["repo_dir"])
    tip = str(fx["tip"])

    # 1. Dense files + empty entries at floor + setxattr refused -> write/xattr refused, actor lives and produces clean bundle!
    floor_script = (
        "import errno, os, shutil\n"
        "try:\n"
        "    os.setxattr('sample', b'user.test', b'1')\n"
        "except OSError as e:\n"
        "    assert e.errno == errno.EOPNOTSUPP, e\n"
        "else:\n"
        "    raise AssertionError('setxattr succeeded')\n"
        "os.mkdir('/tmp/fill')\n"
        "hit = False\n"
        "for i in range(200):\n"
        "    try:\n"
        "        with open(f'/tmp/fill/b{i}', 'wb') as f: f.write(b'x' * (1 << 20))\n"
        "    except OSError as e:\n"
        "        assert e.errno == errno.ENOSPC, e\n"
        "        hit = True\n"
        "        break\n"
        "assert hit\n"
        "shutil.rmtree('/tmp/fill')\n"
        "os.mkdir('/tmp/inodes')\n"
        "ihit = False\n"
        "for d in range(200):\n"
        "    sub = f'/tmp/inodes/d{d}'\n"
        "    try:\n"
        "        os.mkdir(sub)\n"
        "        for j in range(700):\n"
        "            open(f'{sub}/e{j}', 'x').close()\n"
        "    except OSError as e:\n"
        "        assert e.errno == errno.ENOSPC, e\n"
        "        ihit = True\n"
        "        break\n"
        "assert ihit\n"
        "shutil.rmtree('/tmp/inodes')\n"
    ) + "\nimport subprocess\nsubprocess.run(['/usr/bin/sh', '-c', " + repr(ACTOR) + "], check=True)\n"

    sparse_script = (
        "import os\n"
        "os.mkdir('/tmp/sp')\n"
        "for d in range(300):\n"
        "    sub = '/tmp/sp/' + ('d' * 180) + str(d)\n"
        "    os.mkdir(sub)\n"
        "    for j in range(600):\n"
        "        fd = os.open(sub + '/' + ('f' * 180) + str(j), os.O_WRONLY | os.O_CREAT, 0o600)\n"
        "        os.ftruncate(fd, 65536)\n"
        "        os.close(fd)\n"
    )
    mem_script = "x = bytearray(600 << 20); print(len(x))"
    tasks_script = (
        "import os, time\n"
        "pids = []\n"
        "for _ in range(80):\n"
        "    pid = os.fork()\n"
        "    if pid == 0:\n"
        "        time.sleep(5)\n"
        "        os._exit(0)\n"
        "    pids.append(pid)\n"
    )

    unit_ok = f"autonomy-e2e-d7-{secrets.token_hex(6)}.service"
    _issue_via_pty(
        fx,
        "d7",
        delegation_id="del-d7",
        unit=unit_ok,
        actors={
            "floor": ["/usr/bin/python3", "-I", "-c", floor_script],
            "sparse": ["/usr/bin/python3", "-I", "-c", sparse_script],
            "mem": ["/usr/bin/python3", "-I", "-c", mem_script],
            "tasks": ["/usr/bin/python3", "-I", "-c", tasks_script],
        },
        starts=6,
        deadline_seconds=45,
        writable_bytes=96 << 20,
        memory_bytes=416 << 20,
        tasks=24,
    )

    # Run all 4 workloads inside ONE transient delegated unit alongside a sibling process in `main`,
    # verifying the sibling survives every actor exhaustion/OOM!
    base_autonomy = _wrapped_autonomy(
        account_home,
        Path(fx["state_dir"]),
        Path(fx["cache_dir"]),
        [
            "run", "--development", "--delegation", "del-d7",
            "--repository", str(repo_dir), "--base", tip, "--deadline", "35",
        ],
    )
    base_str = shlex.join(base_autonomy)
    batch_script_path = account_home.parent / "run_d7.sh"
    batch_script_path.write_text(
        "#!/usr/bin/sh\n"
        "set -eu\n"
        "/usr/bin/sleep 120 &\n"
        "sibling=$!\n"
        f"{base_str} --attempt att-floor -- /usr/bin/python3 -I -c {shlex.quote(floor_script)}\n"
        "rc_floor=$?\n"
        "set +e\n"
        f"{base_str} --attempt att-sparse -- /usr/bin/python3 -I -c {shlex.quote(sparse_script)}\n"
        "rc_sparse=$?\n"
        f"{base_str} --attempt att-mem -- /usr/bin/python3 -I -c {shlex.quote(mem_script)}\n"
        "rc_mem=$?\n"
        f"{base_str} --attempt att-tasks -- /usr/bin/python3 -I -c {shlex.quote(tasks_script)}\n"
        "rc_tasks=$?\n"
        "set -e\n"
        'kill -0 "$sibling"\n'
        'kill "$sibling" 2>/dev/null || true\n'
        'printf "CODES=%d,%d,%d,%d\\n" "$rc_floor" "$rc_sparse" "$rc_mem" "$rc_tasks"\n',
        encoding="utf-8",
    )
    batch_script_path.chmod(0o700)
    try:
        res = subprocess.run(
            in_delegated_unit(["/usr/bin/sh", str(batch_script_path)], unit=unit_ok),
            env=unit_env(account_home),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        stop_unit(unit_ok, account_home)

    assert res.returncode == 0, f"stdout={res.stdout}\nstderr={res.stderr}"
    codes_line = [ln for ln in res.stdout.splitlines() if ln.startswith("CODES=")][-1]
    c_floor, c_sparse, c_mem, c_tasks = [int(x) for x in codes_line.removeprefix("CODES=").split(",")]
    assert c_floor == 0
    assert c_sparse in (3, 4)
    assert c_mem in (3, 4)
    assert c_tasks in (3, 4)

    rep = _run_outside(fx, ["delegation", "report", "del-d7"])
    doc = json.loads(rep.stdout)
    assert [s["outcome"] for s in doc["starts"]] == ["clean", "quarantined", "quarantined", "quarantined"]

    # Unit misconfigurations refused with exit 2: no delegation, OOMPolicy=stop, MemoryMax below peak
    for idx, props in enumerate(
        (
            ("Delegate=no",),
            ("Delegate=pids", "DelegateSubgroup=main"),
            ("OOMPolicy=stop",),
            ("MemoryMax=512M",),
        )
    ):
        bad_unit = f"autonomy-e2e-d7bad{idx}-{secrets.token_hex(4)}.service"
        del_id = f"del-d7bad{idx}"
        _issue_via_pty(fx, f"d7bad{idx}", delegation_id=del_id, unit=bad_unit, actors={"true": ["/usr/bin/true"]}, starts=1)
        bad_cmd = _wrapped_autonomy(
            account_home, Path(fx["state_dir"]), Path(fx["cache_dir"]),
            [
                "run", "--development", "--delegation", del_id, "--attempt", "att-1",
                "--repository", str(repo_dir), "--base", tip, "--deadline", "10",
                "--", "/usr/bin/true",
            ],
        )
        unit_argv = (
            [
                "/usr/bin/systemd-run", "--user", "--wait", "--pipe", "--collect",
                f"--unit={bad_unit}", "-p", "Delegate=no", "--", *bad_cmd,
            ]
            if props == ("Delegate=no",)
            else in_delegated_unit(bad_cmd, *props, unit=bad_unit)
        )
        try:
            bad_res = subprocess.run(
                unit_argv, env=unit_env(account_home), stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=25,
            )
        finally:
            stop_unit(bad_unit, account_home)
        assert bad_res.returncode == 2, bad_res.stderr
        expected_err = "delegation-caller" if props == ("Delegate=no",) else "delegation-bounds"
        assert expected_err in bad_res.stderr


def test_d8_undelegated_start_refused_in_service_allowed_in_scope(isolated_e2e):
    fx = isolated_e2e
    account_home = Path(fx["account_home"])
    undelegated_args = [
        "run", "--development",
        "--repository", str(fx["repo_dir"]),
        "--base", str(fx["tip"]),
        "--deadline", "20",
        "--", "/usr/bin/sh", "-c", ACTOR,
    ]
    cmd = _wrapped_autonomy(account_home, Path(fx["state_dir"]), Path(fx["cache_dir"]), undelegated_args)

    unit = f"autonomy-e2e-d8-{secrets.token_hex(6)}.service"
    try:
        in_svc = subprocess.run(
            in_delegated_unit(cmd, unit=unit),
            env=unit_env(account_home),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        stop_unit(unit, account_home)
    assert in_svc.returncode == 2
    assert "delegation-required" in in_svc.stderr

    scope_name = f"autonomy-e2e-d8scope-{secrets.token_hex(6)}.scope"
    in_scope = subprocess.run(
        ["/usr/bin/systemd-run", "--user", "--scope", f"--unit={scope_name}", "--", *cmd],
        env=unit_env(account_home),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert in_scope.returncode == 0, in_scope.stderr


def test_d10_supervisor_environment_and_cgroups_unreachable(isolated_e2e):
    fx = isolated_e2e
    account_home = Path(fx["account_home"])
    canary = f"canary-{secrets.token_hex(12)}"
    inspect_script = (
        "import os, subprocess\n"
        f"needle = {canary.encode('ascii')!r}\n"
        "for entry in os.listdir('/proc'):\n"
        "    if entry.isdigit():\n"
        "        try:\n"
        "            raw = open(f'/proc/{entry}/environ', 'rb').read()\n"
        "        except OSError:\n"
        "            continue\n"
        "        assert needle not in raw, f'canary leaked in /proc/{entry}/environ'\n"
        "for denied in ('/sys/fs/cgroup', "
        + repr(str(fx["config_dir"]))
        + ", "
        + repr(str(fx["store_dir"]))
        + "):\n"
        "    assert not os.path.lexists(denied), f'reachable denied path {denied}'\n"
        "subprocess.run(['/usr/bin/sh', '-c', " + repr(ACTOR) + "], check=True)\n"
    )

    unit = f"autonomy-e2e-d10-{secrets.token_hex(6)}.service"
    _issue_via_pty(
        fx,
        "d10",
        delegation_id="del-d10",
        unit=unit,
        actors={"inspect": ["/usr/bin/python3", "-I", "-c", inspect_script]},
        starts=2,
    )
    cmd = _wrapped_autonomy(
        account_home,
        Path(fx["state_dir"]),
        Path(fx["cache_dir"]),
        [
            "run", "--development", "--delegation", "del-d10", "--attempt", "att-d10",
            "--repository", str(fx["repo_dir"]), "--base", str(fx["tip"]), "--deadline", "25",
            "--", "/usr/bin/python3", "-I", "-c", inspect_script,
        ],
        extra_env={"SUPERVISOR_CANARY_SECRET": canary},
    )
    try:
        res = subprocess.run(
            in_delegated_unit(cmd, unit=unit),
            env=unit_env(account_home),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=45,
        )
    finally:
        stop_unit(unit, account_home)
    assert res.returncode == 0, res.stderr
