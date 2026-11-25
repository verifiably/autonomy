import errno
import json
import os
import pty
import pwd
import select
import shutil
import time
from pathlib import Path

import pytest

from autonomy.baseline import publish_bytes
from autonomy.delegation import Delegation, Start, definition
from autonomy.development._delegated import ceiling
from autonomy.development._records import allocate_run, development_places
from autonomy.development._workspace import Limits


def _setup_account(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    account_home = tmp_path / "account-home"
    config_dir = account_home / ".config/verifiably-autonomy"
    delegations_dir = config_dir / "delegations"
    delegations_dir.mkdir(parents=True, mode=0o700)
    store_dir = tmp_path / "store"
    store_dir.mkdir(mode=0o700)
    st = store_dir.stat()
    publish_bytes(
        config_dir / "allowance-storage.json",
        json.dumps({"version": 1, "path": str(store_dir), "device": st.st_dev, "inode": st.st_ino}).encode("utf-8"),
    )
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    return account_home, config_dir, store_dir, repo_dir


def _write_grant_file(
    config_dir: Path,
    name: str,
    repo_dir: Path,
    *,
    delegation_id: str = "del-1",
    starts: int = 3,
    deadline_seconds: int = 60,
    writable_bytes: int = 96 << 20,
    memory_bytes: int = 416 << 20,
    tasks: int = 64,
    unit: str = "band.service",
    expires: int | None = None,
) -> dict:
    doc = {
        "kind": "development-delegation.v1",
        "delegation_id": delegation_id,
        "source": "autonomy-a22882 operator approval",
        "expires": (int(time.time()) + 3600) if expires is None else expires,
        "orchestrator": {"name": "band", "unit": unit},
        "repositories": {"autonomy": {"path": str(repo_dir), "ref": "refs/heads/main"}},
        "actors": {"check": ["/usr/bin/true", "--quiet"]},
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
    return doc


def _read_until(fd: int, marker: bytes, timeout: float = 10.0) -> bytes:
    buf = b""
    deadline = time.monotonic() + timeout
    while marker not in buf:
        remaining = deadline - time.monotonic()
        assert remaining > 0, f"timed out waiting for {marker!r}; got {buf!r}"
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError as exc:
            if exc.errno == errno.EIO:
                break
            raise
        if not chunk:
            break
        buf += chunk
    return buf


def _drain_fd(fd: int, timeout: float = 5.0) -> bytes:
    buf = b""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            break
        try:
            chunk = os.read(fd, 4096)
        except OSError as exc:
            if exc.errno == errno.EIO:
                break
            raise
        if not chunk:
            break
        buf += chunk
    return buf


def _run_under_pty(
    account_home: Path,
    argv: list[str],
    *,
    reply: bytes | None,
    close_master: bool = False,
    env_home: Path | None = None,
    env_xdg_config: Path | None = None,
) -> tuple[int, bytes, bytes, bytes]:
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
            uid = os.getuid()
            pwd.getpwuid = lambda requested: pwd.struct_passwd(("u", "x", requested, uid, "", str(account_home), "/bin/sh"))
            os.environ.clear()
            os.environ["PATH"] = "/usr/bin"
            os.environ["HOME"] = str(env_home or account_home)
            if env_xdg_config is not None:
                os.environ["XDG_CONFIG_HOME"] = str(env_xdg_config)
            from autonomy.cli import main

            os._exit(main(argv))
        except BaseException:
            os._exit(99)

    os.close(out_w)
    os.close(err_w)
    tty_bytes = b""
    try:
        tty_bytes = _read_until(master_fd, b"confirm:")
        if close_master:
            os.close(master_fd)
            master_fd = -1
        elif reply is not None and b"confirm:" in tty_bytes:
            os.write(master_fd, reply)
            tty_bytes += _drain_fd(master_fd, timeout=2.0)
        _, wait_status = os.waitpid(pid, 0)
        stdout = _drain_fd(out_r, timeout=2.0)
        stderr = _drain_fd(err_r, timeout=2.0)
        return os.waitstatus_to_exitcode(wait_status), tty_bytes, stdout, stderr
    finally:
        if master_fd >= 0:
            os.close(master_fd)
        os.close(out_r)
        os.close(err_r)


def _run_without_tty(
    account_home: Path,
    argv: list[str],
    *,
    env_home: Path | None = None,
    env_xdg_config: Path | None = None,
) -> tuple[int, bytes, bytes]:
    out_r, out_w = os.pipe()
    err_r, err_w = os.pipe()
    in_r, in_w = os.pipe()
    os.close(in_w)
    pid = os.fork()
    if pid == 0:
        try:
            os.setsid()
            os.close(out_r)
            os.close(err_r)
            os.dup2(in_r, 0)
            os.dup2(out_w, 1)
            os.dup2(err_w, 2)
            os.close(in_r)
            os.close(out_w)
            os.close(err_w)
            uid = os.getuid()
            pwd.getpwuid = lambda requested: pwd.struct_passwd(("u", "x", requested, uid, "", str(account_home), "/bin/sh"))
            os.environ.clear()
            os.environ["PATH"] = "/usr/bin"
            os.environ["HOME"] = str(env_home or account_home)
            if env_xdg_config is not None:
                os.environ["XDG_CONFIG_HOME"] = str(env_xdg_config)
            from autonomy.cli import main

            os._exit(main(argv))
        except BaseException:
            os._exit(99)

    os.close(in_r)
    os.close(out_w)
    os.close(err_w)
    try:
        _, wait_status = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(wait_status), _drain_fd(out_r, 2.0), _drain_fd(err_r, 2.0)
    finally:
        os.close(out_r)
        os.close(err_r)


def test_issue_prints_the_terms_and_publishes(tmp_path):
    account_home, config_dir, store_dir, repo_dir = _setup_account(tmp_path)
    expires = int(time.time()) + 3600
    _write_grant_file(
        config_dir,
        "band",
        repo_dir,
        delegation_id="del-1",
        starts=3,
        deadline_seconds=60,
        writable_bytes=96 << 20,
        memory_bytes=416 << 20,
        expires=expires,
    )
    rc, tty_out, stdout, stderr = _run_under_pty(account_home, ["delegation", "issue", "band"], reply=b"del-1\n")
    assert rc == 0, stderr.decode()
    text = tty_out.decode("utf-8")
    assert "band.service" in text
    assert str(repo_dir) in text and "refs/heads/main" in text
    assert "/usr/bin/true" in text and "--quiet" in text
    assert "180" in text  # 3 * 60 seconds
    assert str(3 * ((64 << 20) + (32 << 20) + (96 << 20))) in text
    assert str((416 << 20) + (96 << 20) + (768 << 20)) in text
    assert str(expires) in text

    receipt = json.loads(stdout.decode("utf-8"))
    assert receipt["grant"]["delegation_id"] == "del-1"
    assert receipt["starts_left"] == 3
    assert (store_dir / "del-1.sqlite").is_file()
    assert (store_dir / "del-1.lock").is_file()


def test_wrong_id(tmp_path):
    account_home, config_dir, store_dir, repo_dir = _setup_account(tmp_path)
    _write_grant_file(config_dir, "band", repo_dir, delegation_id="del-1")
    rc, _tty_out, stdout, stderr = _run_under_pty(account_home, ["delegation", "issue", "band"], reply=b"del-2\n")
    assert rc == 2
    assert stdout == b""
    assert b"delegation-unconfirmed" in stderr
    assert not (store_dir / "del-1.sqlite").exists()
    assert not (store_dir / "del-1.lock").exists()


@pytest.mark.parametrize("eof_mode", ["ctrl-d", "hangup"])
def test_end_of_input_at_the_prompt(tmp_path, eof_mode):
    account_home, config_dir, store_dir, repo_dir = _setup_account(tmp_path)
    _write_grant_file(config_dir, "band", repo_dir, delegation_id="del-1")
    rc, _tty_out, stdout, stderr = _run_under_pty(
        account_home,
        ["delegation", "issue", "band"],
        reply=b"\x04" if eof_mode == "ctrl-d" else None,
        close_master=(eof_mode == "hangup"),
    )
    assert rc == 2
    assert stdout == b""
    assert b"delegation-unconfirmed" in stderr
    assert not (store_dir / "del-1.sqlite").exists()
    assert not (store_dir / "del-1.lock").exists()


def test_no_controlling_terminal(tmp_path):
    account_home, config_dir, store_dir, repo_dir = _setup_account(tmp_path)
    _write_grant_file(config_dir, "band", repo_dir, delegation_id="del-1")
    rc, stdout, stderr = _run_without_tty(account_home, ["delegation", "issue", "band"])
    assert rc == 2
    assert stdout == b""
    assert b"delegation-unconfirmed" in stderr
    assert not (store_dir / "del-1.sqlite").exists()
    assert not (store_dir / "del-1.lock").exists()


def test_earlier_unfinished_start_is_printed(tmp_path):
    account_home, config_dir, store_dir, repo_dir = _setup_account(tmp_path)
    old_doc = _write_grant_file(config_dir, "old", repo_dir, delegation_id="del-old")
    old_grant = Delegation.issue(store_dir, definition(old_doc, ceiling(Limits())))
    old_run = "e" * 32
    old_grant.begin(
        Start(
            0, "att-unfinished", old_run, int(time.time()),
            tmp_path / "state", tmp_path / "cache", "autonomy", "check", "a" * 40,
            10.0, "band.service", "/user.slice/band.service", "c" * 32, False, None, None,
        ),
        margin=10.0,
    )
    old_grant.mark(old_run)
    old_grant.revoke()

    _write_grant_file(config_dir, "new", repo_dir, delegation_id="del-new")
    rc, tty_out, stdout, stderr = _run_under_pty(account_home, ["delegation", "issue", "new"], reply=b"del-new\n")
    assert rc == 0, stderr.decode()
    text = tty_out.decode("utf-8")
    assert old_run in text and "att-unfinished" in text
    assert json.loads(stdout.decode("utf-8"))["grant"]["delegation_id"] == "del-new"


def test_report_and_revoke_exit_codes(tmp_path):
    account_home, config_dir, store_dir, repo_dir = _setup_account(tmp_path)
    doc1 = _write_grant_file(config_dir, "g1", repo_dir, delegation_id="del-ack")
    Delegation.issue(store_dir, definition(doc1, ceiling(Limits())))

    rc_rep, out_rep, err_rep = _run_without_tty(account_home, ["delegation", "report", "del-ack", "--attempt", "none"])
    assert rc_rep == 0 and err_rep == b""
    assert json.loads(out_rep.decode("utf-8"))["starts"] == []

    rc_rev, out_rev, err_rev = _run_without_tty(account_home, ["delegation", "revoke", "del-ack"])
    assert rc_rev == 0 and err_rev == b""
    assert json.loads(out_rev.decode("utf-8"))["acknowledged"] is True

    # Unacknowledged revoke: allocated start whose roots are gone while <id>.lock is free
    doc2 = _write_grant_file(config_dir, "g2", repo_dir, delegation_id="del-unack")
    g2 = Delegation.issue(store_dir, definition(doc2, ceiling(Limits())))
    places = development_places({"XDG_STATE_HOME": str(tmp_path / "st"), "XDG_CACHE_HOME": str(tmp_path / "ca")})
    run_id = "f" * 32
    with allocate_run(places, repository=repo_dir, base="a" * 40, deadline_seconds=10.0, run_id=run_id):
        pass
    g2.begin(
        Start(
            0, "att-1", run_id, int(time.time()), places.state, places.cache,
            "autonomy", "check", "a" * 40, 10.0, "band.service", "/user.slice/band.service", "c" * 32,
            False, None, None,
        ),
        margin=10.0,
    )
    g2.mark(run_id)
    shutil.rmtree(places.state)

    rc_u, out_u, err_u = _run_without_tty(account_home, ["delegation", "revoke", "del-unack"])
    assert rc_u == 2
    rev_doc = json.loads(out_u.decode("utf-8"))
    assert rev_doc["acknowledged"] is False
    assert "systemctl --user stop band.service" in rev_doc["stop_unit"]
    assert b"refused: delegation-stop-unacknowledged" in err_u
    assert b"systemctl --user stop band.service" in err_u


def test_commands_ignore_home(tmp_path):
    account_home, config_dir, _store_dir, repo_dir = _setup_account(tmp_path)
    doc = _write_grant_file(config_dir, "real", repo_dir, delegation_id="del-real")

    # Populate forged HOME and XDG_CONFIG_HOME with a different store & grant "del-forged"
    forged_home = tmp_path / "forged-home"
    forged_xdg = tmp_path / "forged-xdg"
    for cfg in (forged_home / ".config/verifiably-autonomy", forged_xdg / "verifiably-autonomy"):
        (cfg / "delegations").mkdir(parents=True, mode=0o700)
        fstore = cfg / "store"
        fstore.mkdir(mode=0o700)
        fst = fstore.stat()
        publish_bytes(
            cfg / "allowance-storage.json",
            json.dumps({"version": 1, "path": str(fstore), "device": fst.st_dev, "inode": fst.st_ino}).encode("utf-8"),
        )
        fdoc = _write_grant_file(cfg, "forged", repo_dir, delegation_id="del-forged")
        Delegation.issue(fstore, definition(fdoc, ceiling(Limits())))

    rc_issue, _, out_issue, err_issue = _run_under_pty(
        account_home, ["delegation", "issue", "real"], reply=b"del-real\n",
        env_home=forged_home, env_xdg_config=forged_xdg,
    )
    assert rc_issue == 0, err_issue.decode()
    assert json.loads(out_issue.decode("utf-8"))["grant"]["delegation_id"] == doc["delegation_id"]

    rc_forged, _, err_forged = _run_without_tty(
        account_home, ["delegation", "report", "del-forged"],
        env_home=forged_home, env_xdg_config=forged_xdg,
    )
    assert rc_forged == 2 and b"delegation-missing" in err_forged

    rc_real, out_real, _ = _run_without_tty(
        account_home, ["delegation", "report", "del-real"],
        env_home=forged_home, env_xdg_config=forged_xdg,
    )
    assert rc_real == 0 and json.loads(out_real.decode("utf-8"))["grant"]["delegation_id"] == "del-real"
