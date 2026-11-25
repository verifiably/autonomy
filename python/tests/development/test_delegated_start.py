import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import MappingProxyType

import pytest

from autonomy.allowance import Campaign
from autonomy.baseline import publish_bytes
from autonomy.delegation import Delegation, Host, definition
from autonomy.development._records import file_digest, read_journal, read_json
from autonomy.development._workspace import Limits
from autonomy.run import DevelopmentProgress, RunRefused
from development.test_integration import ACTOR
from development.test_workspace import fixture_git, make_source

pytestmark = pytest.mark.bwrap


class SeamCgroup:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.created = False
        self.checked = False
        self.removed = 0

    def create(self, *, memory_bytes: int, tasks: int) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "cgroup.procs").write_bytes(b"")
        self.created = True

    def check(self, pid: int, *, memory_bytes: int, tasks: int) -> None:
        assert (self.path / "cgroup.procs").read_bytes() == b"0\n"
        self.checked = True

    def empty(self) -> bool:
        return True

    def kill(self) -> None:
        pass

    def remove(self, *, wait: float) -> bool:
        self.removed += 1
        return True


def _build_fixture(
    tmp_path: Path,
    *,
    starts: int = 3,
    deadline_seconds: int = 30,
    writable_bytes: int = 96 << 20,
    memory_bytes: int = 416 << 20,
    tasks: int = 64,
    expires_offset: int = 3600,
    unit: str = "band.service",
):
    from autonomy.development._delegated import ceiling

    root = tmp_path / "fixture"
    root.mkdir()
    repo = root / "repo"
    make_source(repo)
    tip = fixture_git(repo, "rev-parse", "refs/heads/main")

    config_dir = root / "account-config"
    config_dir.mkdir(mode=0o700)
    store_dir = root / "store"
    store_dir.mkdir(mode=0o700)
    st = store_dir.stat()
    publish_bytes(
        config_dir / "allowance-storage.json",
        json.dumps({"version": 1, "path": str(store_dir), "device": st.st_dev, "inode": st.st_ino}).encode("utf-8"),
    )

    uid = os.getuid()
    cgroup_root = root / "cgroups"
    unit_rel = f"user.slice/user-{uid}.slice/user@{uid}.service/{unit}"
    unit_cg = "/" + unit_rel
    for anc in (
        cgroup_root,
        cgroup_root / "user.slice",
        cgroup_root / "user.slice" / f"user-{uid}.slice",
        cgroup_root / "user.slice" / f"user-{uid}.slice" / f"user@{uid}.service",
        cgroup_root / unit_rel,
    ):
        anc.mkdir(parents=True, exist_ok=True)
        (anc / "memory.max").write_text("max\n", encoding="ascii")
        (anc / "pids.max").write_text("max\n", encoding="ascii")

    cgroups_seen: dict[str, SeamCgroup] = {}

    def make_cg(_unit_cg: str, run_id: str) -> SeamCgroup:
        if run_id not in cgroups_seen:
            cgroups_seen[run_id] = SeamCgroup(cgroup_root / unit_rel / f"actor-{run_id}")
        return cgroups_seen[run_id]

    props = {
        "ActiveState": "active",
        "Type": "simple",
        "ControlGroup": unit_cg,
        "InvocationID": "c" * 32,
        "Delegate": "yes",
        "DelegateControllers": "memory pids",
        "DelegateSubgroup": "main",
        "OOMPolicy": "continue",
    }
    host = Host(
        config=config_dir,
        cgroup=f"{unit_cg}/main",
        cgroups=cgroup_root,
        show=lambda requested: MappingProxyType(props) if requested == unit else {},
        actor_cgroup=make_cg,
    )

    raw_grant = {
        "kind": "development-delegation.v1",
        "delegation_id": "del-main",
        "source": "autonomy-a22882 fixture",
        "expires": int(time.time()) + expires_offset,
        "orchestrator": {"name": "band", "unit": unit},
        "repositories": {"repo": {"path": str(repo), "ref": "refs/heads/main"}},
        "actors": {
            "candidate": ["/usr/bin/sh", "-c", ACTOR],
            "true": ["/usr/bin/true"],
        },
        "limits": {
            "starts": starts,
            "deadline_seconds": deadline_seconds,
            "writable_bytes": writable_bytes,
            "memory_bytes": memory_bytes,
            "tasks": tasks,
        },
        "model": None,
    }
    validated = definition(raw_grant, ceiling(Limits()))
    grant = Delegation.issue(store_dir, validated)

    env = {
        "PATH": "/usr/bin",
        "HOME": str(root / "caller-home"),
        "LC_ALL": "C",
        "XDG_STATE_HOME": str(root / "state"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "XDG_CONFIG_HOME": str(root / "caller-config"),
    }
    (root / "caller-home").mkdir()
    return {
        "root": root,
        "repo": repo,
        "tip": tip,
        "config_dir": config_dir,
        "store_dir": store_dir,
        "cgroup_root": cgroup_root,
        "unit_cg": unit_cg,
        "props": props,
        "host": host,
        "grant": grant,
        "env": env,
        "cgroups": cgroups_seen,
    }


@pytest.fixture
def stdio():
    fd = os.open(os.devnull, os.O_RDWR | os.O_CLOEXEC)
    try:
        yield (fd, fd, fd)
    finally:
        os.close(fd)


def test_clean_delegated_run(tmp_path, stdio):
    from autonomy.development import _delegated, _run

    fx = _build_fixture(tmp_path)
    progress = DevelopmentProgress()
    req = _run.DevelopmentRequest(
        repository=fx["repo"],
        base=fx["tip"],
        deadline_seconds=15.0,
        actor_argv=("/usr/bin/sh", "-c", ACTOR),
        report_fd=None,
        delegation="del-main",
        attempt="att-1",
    )
    status = _run.execute(req, fx["env"], diag=lambda _: None, progress=progress, actor_fds=stdio, host=fx["host"])
    assert status == 0
    run_dir = progress.run_dir
    assert run_dir is not None

    header = read_json(run_dir / "run.json")
    grant_rec = read_json(run_dir / "grant.json")
    cand_rec = read_json(run_dir / "candidate.json")
    disp_rec = read_json(run_dir / "disposition.json")
    info = fx["grant"].grant()

    assert header["delegation"] == {
        "id": "del-main",
        "grant_digest": info.digest,
        "attempt": "att-1",
    }
    assert grant_rec["approval"] == "delegation"
    assert grant_rec["delegation"] == {
        "id": "del-main",
        "grant_digest": info.digest,
        "storage": info.storage,
        "attempt": "att-1",
        "start": 1,
        "repository": "repo",
        "actor": "candidate",
        "ref": "refs/heads/main",
        "caller": {
            "unit": "band.service",
            "cgroup": fx["unit_cg"],
            "invocation_id": "c" * 32,
        },
        "bounds": {
            "memory_bytes": 416 << 20,
            "swap_bytes": 0,
            "tasks": 64,
        },
    }
    assert disp_rec["disposition"] == "clean" and disp_rec["containment_proven"] is True
    assert grant_rec["run_sha256"] == file_digest(run_dir / "run.json")
    assert cand_rec["grant_sha256"] == disp_rec["grant_sha256"] == file_digest(run_dir / "grant.json")
    assert disp_rec["candidate_sha256"] == file_digest(run_dir / "candidate.json")

    (row,) = fx["grant"].starts()
    assert row.outcome == "clean"
    assert row.disposition_sha256 == file_digest(run_dir / "disposition.json")
    cg = fx["cgroups"][run_dir.name]
    assert cg.created and cg.checked and cg.removed >= 1
    rep = _delegated.report(fx["grant"], fx["host"], attempt="att-1")
    assert rep["starts"][0]["outcome"] == "clean"


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("bad-delegation-id", "delegation-invalid"),
        ("bad-attempt-id", "delegation-invalid"),
        ("unknown-delegation", "delegation-missing"),
        ("campaign-id", "delegation-missing"),
        ("missing-storage", "delegation-unavailable"),
        ("already-expired", "delegation-expired"),
        ("margin-past-expiry", "delegation-expired"),
        ("revoked", "delegation-closed"),
        ("containment-closed", "delegation-closed"),
        ("wrong-caller", "delegation-caller"),
        ("wrong-repo", "delegation-repository"),
        ("wrong-actor", "delegation-actor"),
        ("deadline-too-high", "delegation-deadline"),
        ("stale-base", "delegation-base"),
        ("oom-stop", "delegation-bounds"),
        ("ancestor-mem-low", "delegation-bounds"),
        ("busy-lock", "delegation-busy"),
        ("unfinished-run", "delegation-run-unfinished"),
        ("attempt-reused", "delegation-attempt-used"),
        ("exhausted", "delegation-exhausted"),
    ],
)
def test_each_admission_refusal(tmp_path, stdio, monkeypatch, case, expected_code):
    from autonomy.development import _run

    starts = 1 if case == "exhausted" else 2
    fx = _build_fixture(tmp_path, starts=starts, expires_offset=80 if case == "margin-past-expiry" else 3600)
    delegation_id = "del-main"
    attempt_id = "att-1"
    repo = fx["repo"]
    base = fx["tip"]
    deadline = 15.0
    argv = ("/usr/bin/true",)
    host = fx["host"]
    holder = None

    if case == "bad-delegation-id":
        delegation_id = "../bad"
    elif case == "bad-attempt-id":
        attempt_id = "bad/attempt"
    elif case == "unknown-delegation":
        delegation_id = "does-not-exist"
    elif case == "campaign-id":
        Campaign.issue(
            fx["store_dir"],
            {
                "campaign_id": "camp-1",
                "source": "fixture",
                "expires": int(time.time()) + 3600,
                "limits": {"attempts": 1, "input_tokens": 100, "output_tokens": 100, "micro_usd": 1000, "job_starts": 1},
                "tariff": {
                    "model": "claude-haiku-4-5",
                    "billing_mode": "standard",
                    "context": 200000,
                    "output_cap": 1024,
                    "max_input_micro_usd_per_mtok": 1000,
                    "output_micro_usd_per_mtok": 1000,
                    "rates_micro_usd_per_mtok": {
                        "input": 1000, "output": 1000, "cache_read": 100, "cache_write_5m": 1000, "cache_write_1h": 1000,
                    },
                },
                "members": {
                    "m1": {
                        "caller": "analyst",
                        "target": {"model": "claude-haiku-4-5"},
                        "route_digest": "a" * 64,
                        "limits": {"attempts": 1, "input_tokens": 100, "output_tokens": 100, "micro_usd": 1000, "job_starts": 0},
                    }
                },
            },
        )
        delegation_id = "camp-1"
    elif case == "missing-storage":
        (fx["config_dir"] / "allowance-storage.json").unlink()
    elif case in ("already-expired", "revoked", "containment-closed"):
        if case == "already-expired":
            import sqlite3

            with sqlite3.connect(fx["grant"].path) as db:
                row = json.loads(db.execute("SELECT cfg FROM grant_record").fetchone()[0])
                row["expires"] = int(time.time()) - 10
                db.execute("UPDATE grant_record SET cfg=?", (json.dumps(row, sort_keys=True, separators=(",", ":")),))
        elif case == "revoked":
            fx["grant"].revoke()
        else:
            fx["grant"].contain()
        # Closed/expired must refuse at step 2 BEFORE admit_source!
        monkeypatch.setattr(_run, "admit_source", lambda *a, **k: pytest.fail("admit_source ran on closed/expired grant"))
    elif case == "wrong-caller":
        host = Host(
            config=fx["config_dir"],
            cgroup="/user.slice/user-1000.slice/session-1.scope",
            cgroups=fx["cgroup_root"],
            show=fx["host"].show,
            actor_cgroup=fx["host"].actor_cgroup,
        )
    elif case == "wrong-repo":
        other_repo = tmp_path / "ungranted"
        make_source(other_repo)
        repo = other_repo
    elif case == "wrong-actor":
        argv = ("/usr/bin/false",)
    elif case == "deadline-too-high":
        deadline = 31.0
    elif case == "stale-base":
        base = fixture_git(fx["repo"], "rev-parse", "HEAD~")
    elif case == "oom-stop":
        fx["props"]["OOMPolicy"] = "stop"
    elif case == "ancestor-mem-low":
        (fx["cgroup_root"] / "user.slice" / "memory.max").write_text("1048576\n", encoding="ascii")
    elif case == "busy-lock":
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import fcntl, sys, time; f = open(sys.argv[1], 'r+b'); "
                "fcntl.flock(f, fcntl.LOCK_EX); sys.stdout.write('held\\n'); sys.stdout.flush(); time.sleep(10)",
                str(fx["grant"].lock_path),
            ],
            env={"PATH": os.defpath, "HOME": str(tmp_path)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert holder.stdout.readline() == b"held\n"
    elif case == "unfinished-run":
        from autonomy.delegation import Start

        fx["grant"].begin(
            Start(
                0, "earlier", "1" * 32, int(time.time()), Path(fx["env"]["XDG_STATE_HOME"]) / "verifiably-autonomy",
                Path(fx["env"]["XDG_CACHE_HOME"]) / "verifiably-autonomy", "repo", "true", base, 5.0,
                "band.service", fx["unit_cg"], "c" * 32, False, None, None,
            ),
            margin=10.0,
        )
        fx["grant"].mark("1" * 32)
    elif case in ("attempt-reused", "exhausted"):
        first_req = _run.DevelopmentRequest(repo, base, 5.0, ("/usr/bin/true",), None, "del-main", "att-1")
        assert _run.execute(first_req, fx["env"], diag=lambda _: None, progress=DevelopmentProgress(), actor_fds=stdio, host=host) == 3
        if case == "exhausted":
            attempt_id = "att-2"
        for child in (Path(fx["env"]["XDG_STATE_HOME"]) / "verifiably-autonomy/runs").iterdir():
            import shutil

            shutil.rmtree(child)

    before_starts = len(fx["grant"].starts()) if (fx["config_dir"] / "allowance-storage.json").exists() else 0
    try:
        req = _run.DevelopmentRequest(repo, base, deadline, argv, None, delegation_id, attempt_id)
        with pytest.raises(RunRefused) as caught:
            _run.execute(req, fx["env"], diag=lambda _: None, progress=DevelopmentProgress(), actor_fds=stdio, host=host)
        assert caught.value.code == expected_code
    finally:
        if holder is not None:
            holder.kill()
            holder.wait(timeout=5)

    runs_dir = Path(fx["env"]["XDG_STATE_HOME"]) / "verifiably-autonomy/runs"
    assert not runs_dir.exists() or list(runs_dir.iterdir()) == []
    if (fx["config_dir"] / "allowance-storage.json").exists():
        assert len(fx["grant"].starts()) == before_starts


def test_requires_delegation_from_a_user_service(tmp_path, stdio):
    from autonomy.development import _run

    fx = _build_fixture(tmp_path)
    undelegated = _run.DevelopmentRequest(fx["repo"], fx["tip"], 5.0, ("/usr/bin/true",), None)

    with pytest.raises(RunRefused) as before_revoke:
        _run.execute(undelegated, fx["env"], diag=lambda _: None, progress=DevelopmentProgress(), actor_fds=stdio, host=fx["host"])
    assert before_revoke.value.code == "delegation-required"

    fx["grant"].revoke()
    with pytest.raises(RunRefused) as after_revoke:
        _run.execute(undelegated, fx["env"], diag=lambda _: None, progress=DevelopmentProgress(), actor_fds=stdio, host=fx["host"])
    assert after_revoke.value.code == "delegation-required"
    assert not (Path(fx["env"]["XDG_STATE_HOME"]) / "verifiably-autonomy/runs").exists()

    uid = os.getuid()
    scope_host = Host(
        config=fx["config_dir"],
        cgroup=f"/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/run-42.scope",
        cgroups=fx["cgroup_root"],
        show=fx["host"].show,
        actor_cgroup=fx["host"].actor_cgroup,
    )
    status = _run.execute(undelegated, fx["env"], diag=lambda _: None, progress=DevelopmentProgress(), actor_fds=stdio, host=scope_host)
    assert status == 3  # /usr/bin/true produces no bundle -> quarantined, not refused


def test_delegation_and_attempt_go_together(tmp_path, stdio):
    from autonomy.development import _run

    fx = _build_fixture(tmp_path)
    for delegation_id, attempt_id in (("del-main", None), (None, "att-1")):
        req = _run.DevelopmentRequest(fx["repo"], fx["tip"], 5.0, ("/usr/bin/true",), None, delegation_id, attempt_id)
        with pytest.raises(RunRefused) as caught:
            _run.execute(req, fx["env"], diag=lambda _: None, progress=DevelopmentProgress(), actor_fds=stdio, host=fx["host"])
        assert caught.value.code == "development-mode-conflict"


def test_environment_cannot_choose_the_store(tmp_path, stdio):
    from autonomy.development import _delegated, _run

    fx = _build_fixture(tmp_path)
    # Create forged stores under both HOME and XDG_CONFIG_HOME with grant "forged-del".
    for cfg_root in (
        Path(fx["env"]["HOME"]) / ".config/verifiably-autonomy",
        Path(fx["env"]["XDG_CONFIG_HOME"]) / "verifiably-autonomy",
    ):
        cfg_root.mkdir(parents=True, exist_ok=True)
        forged_store = cfg_root / "forged-store"
        forged_store.mkdir(mode=0o700)
        st = forged_store.stat()
        publish_bytes(
            cfg_root / "allowance-storage.json",
            json.dumps({"version": 1, "path": str(forged_store), "device": st.st_dev, "inode": st.st_ino}).encode("utf-8"),
        )
        forged_cfg = definition(
            {
                "kind": "development-delegation.v1",
                "delegation_id": "forged-del",
                "source": "forged",
                "expires": int(time.time()) + 3600,
                "orchestrator": {"name": "band", "unit": "band.service"},
                "repositories": {"repo": {"path": str(fx["repo"]), "ref": "refs/heads/main"}},
                "actors": {"true": ["/usr/bin/true"]},
                "limits": {
                    "starts": 2,
                    "deadline_seconds": 30,
                    "writable_bytes": 96 << 20,
                    "memory_bytes": 416 << 20,
                    "tasks": 64,
                },
                "model": None,
            },
            _delegated.ceiling(Limits()),
        )
        Delegation.issue(forged_store, forged_cfg)

    forged_req = _run.DevelopmentRequest(fx["repo"], fx["tip"], 5.0, ("/usr/bin/true",), None, "forged-del", "att-1")
    with pytest.raises(RunRefused) as caught:
        _run.execute(forged_req, fx["env"], diag=lambda _: None, progress=DevelopmentProgress(), actor_fds=stdio, host=fx["host"])
    assert caught.value.code == "delegation-missing"


def test_allocation_failure_settles_not_allocated(tmp_path, stdio):
    from autonomy.development import _delegated, _run

    fx = _build_fixture(tmp_path)
    Path(fx["env"]["XDG_STATE_HOME"]).write_text("blocks mkdir", encoding="utf-8")
    req = _run.DevelopmentRequest(fx["repo"], fx["tip"], 5.0, ("/usr/bin/true",), None, "del-main", "att-1")
    with pytest.raises(RunRefused) as caught:
        _run.execute(req, fx["env"], diag=lambda _: None, progress=DevelopmentProgress(), actor_fds=stdio, host=fx["host"])
    assert caught.value.code == "allocation-failed"
    rep = _delegated.report(fx["grant"], fx["host"], attempt="att-1")
    assert rep["starts"][0]["outcome"] == "not-allocated"


def test_narrower_writable_bytes_narrows_the_pool(tmp_path):
    from autonomy.development import _delegated, _run

    probe_script = "import os, sys; v = os.statvfs('.'); sys.stdout.write(f'{v.f_blocks * v.f_frsize}\\n')"
    fx = _build_fixture(tmp_path, writable_bytes=96 << 20)
    # Add probe actor to a second grant after revoking the first
    fx["grant"].revoke()
    cfg2 = definition(
        {
            "kind": "development-delegation.v1",
            "delegation_id": "del-narrow",
            "source": "autonomy-a22882 narrow pool",
            "expires": int(time.time()) + 3600,
            "orchestrator": {"name": "band", "unit": "band.service"},
            "repositories": {"repo": {"path": str(fx["repo"]), "ref": "refs/heads/main"}},
            "actors": {"probe": ["/usr/bin/python3", "-I", "-c", probe_script]},
            "limits": {
                "starts": 2,
                "deadline_seconds": 30,
                "writable_bytes": 96 << 20,
                "memory_bytes": 416 << 20,
                "tasks": 64,
            },
            "model": None,
        },
        _delegated.ceiling(Limits()),
    )
    Delegation.issue(fx["store_dir"], cfg2)

    out_r, out_w = os.pipe()
    null = os.open(os.devnull, os.O_RDWR | os.O_CLOEXEC)
    progress = DevelopmentProgress()
    try:
        req = _run.DevelopmentRequest(
            fx["repo"], fx["tip"], 10.0, ("/usr/bin/python3", "-I", "-c", probe_script), None, "del-narrow", "att-1"
        )
        status = _run.execute(req, fx["env"], diag=lambda _: None, progress=progress, actor_fds=(null, out_w, null), host=fx["host"])
        os.close(out_w)
        out_w = -1
        reported_size = int(os.read(out_r, 128).decode("ascii").strip())
    finally:
        if out_w >= 0:
            os.close(out_w)
        os.close(out_r)
        os.close(null)

    assert status == 3  # no bundle written
    assert reported_size == 96 << 20
    assert read_json(progress.run_dir / "grant.json")["limits"]["actor_storage_bytes"] == 96 << 20


@pytest.mark.parametrize("admitted_kind", ["config", "store", "cgroups"])
def test_proof_fails_when_admitted(tmp_path, stdio, monkeypatch, admitted_kind):
    from dataclasses import replace as dc_replace
    from autonomy.development import _run, _workspace

    fx = _build_fixture(tmp_path)
    target = {
        "config": fx["config_dir"],
        "store": fx["store_dir"],
        "cgroups": Path("/sys/fs/cgroup"),
    }[admitted_kind].resolve(strict=True)

    real_check = _workspace.check_binds

    def inject_bind(spec, denied):
        mutated = dc_replace(spec, ro_binds=(*spec.ro_binds, target))
        return real_check(mutated, denied)

    monkeypatch.setattr(_workspace, "check_binds", inject_bind)
    progress = DevelopmentProgress()
    req = _run.DevelopmentRequest(fx["repo"], fx["tip"], 10.0, ("/usr/bin/true",), None, "del-main", "att-1")
    status = _run.execute(req, fx["env"], diag=lambda _: None, progress=progress, actor_fds=stdio, host=fx["host"])
    assert status == 4
    verdict = read_json(progress.run_dir / "disposition.json")
    assert verdict["disposition"] == "unwired"
    assert verdict["containment_proven"] is True
    assert [f["code"] for f in verdict["findings"]] == ["development-sandbox-unproven"]
    events = [row["event"] for row in read_journal(_lookup(fx["env"], progress.run_dir.name))]
    assert "releasing" not in events


def _lookup(env, run_id):
    from autonomy.development._records import development_places, lookup_run

    return lookup_run(development_places(env), run_id)


def _run_crash_child(fx: dict, point: str, delegation_id: str, attempt_id: str) -> subprocess.CompletedProcess:
    code = f"""
import os, sys
from pathlib import Path
from types import MappingProxyType
from autonomy.delegation import Host
from autonomy.development import _delegated, _records, _run
from autonomy.run import DevelopmentProgress, RunRefused

point = sys.argv[1]
config_dir = Path({str(fx["config_dir"])!r})
cgroup_root = Path({str(fx["cgroup_root"])!r})
unit_cg = {fx["unit_cg"]!r}
props = {dict(fx["props"])!r}
repo = Path({str(fx["repo"])!r})
tip = {fx["tip"]!r}

class ChildCg:
    def __init__(self, path): self.path = path
    def create(self, *, memory_bytes, tasks):
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "cgroup.procs").write_bytes(b"")
    def check(self, pid, *, memory_bytes, tasks): pass
    def empty(self): return True
    def kill(self): pass
    def remove(self, *, wait): return True

host = Host(
    config=config_dir,
    cgroup=unit_cg + "/main",
    cgroups=cgroup_root,
    show=lambda u: MappingProxyType(props),
    actor_cgroup=lambda u, r: ChildCg(cgroup_root / f"actor-{{r}}"),
)

if point == "after-begin":
    real_begin = _delegated.Delegation.begin
    def die_after_begin(self, start, *, margin):
        res = real_begin(self, start, margin=margin)
        os._exit(91)
    _delegated.Delegation.begin = die_after_begin
elif point == "during-allocate-mkdir":
    real_pub = _records.publish_json
    def die_before_run_json(path, val):
        if path.name == "run.json":
            os._exit(92)
        return real_pub(path, val)
    _records.publish_json = die_before_run_json
elif point == "during-allocate-run-json":
    real_append = _records.append_event
    def die_after_run_json(run_dir, event, **kw):
        res = real_append(run_dir, event, **kw)
        if event == "allocated":
            os._exit(93)
        return res
    _records.append_event = die_after_run_json
elif point == "after-mark":
    real_mark = _delegated.Delegation.mark
    def die_after_mark(self, run):
        real_mark(self, run)
        os._exit(94)
    _delegated.Delegation.mark = die_after_mark
elif point == "after-verdict-before-settle":
    real_term = _run.publish_terminal
    def die_after_verdict(*a, **kw):
        res = real_term(*a, **kw)
        os._exit(96)
    _run.publish_terminal = die_after_verdict
elif point == "store-fail-at-mark":
    def fail_mark(self, run):
        raise RunRefused("delegation-unavailable", "simulated store failure at mark")
    _delegated.Delegation.mark = fail_mark

null = os.open(os.devnull, os.O_RDWR)
actor = ({("/usr/bin/sh", "-c", ACTOR)!r} if point == "after-verdict-before-settle" else ("/usr/bin/true",))
launched = (lambda: os._exit(95)) if point == "after-gate" else None
req = _run.DevelopmentRequest(repo, tip, 15.0, actor, None, {delegation_id!r}, {attempt_id!r})
rc = _run.execute(req, os.environ, diag=lambda _: None, progress=DevelopmentProgress(), actor_fds=(null, null, null), actor_launched=launched, host=host)
raise SystemExit(rc)
"""
    return subprocess.run(
        [sys.executable, "-c", code, point],
        env=fx["env"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=45,
    )


@pytest.mark.parametrize(
    "point",
    [
        "after-begin",
        "during-allocate-mkdir",
        "during-allocate-run-json",
        "after-mark",
        "after-gate",
        "after-verdict-before-settle",
        "store-fail-at-mark",
    ],
)
def test_crash_rows_settle_or_refuse_as_specified(tmp_path, stdio, point):
    from autonomy.development import _delegated, _run

    fx = _build_fixture(tmp_path, starts=3)
    res = _run_crash_child(fx, point, "del-main", "att-1")

    if point == "store-fail-at-mark":
        assert res.returncode == 4
        rep = _delegated.report(fx["grant"], fx["host"], attempt="att-1")
        assert rep["starts"][0]["outcome"] == "unwired"
        run_dir = Path(fx["env"]["XDG_STATE_HOME"]) / "verifiably-autonomy/runs" / rep["starts"][0]["run"]
        assert not (run_dir / "base.bundle").exists()
        assert not (run_dir / "walk.json").exists()
        assert [f["code"] for f in read_json(run_dir / "disposition.json")["findings"]] == ["development-delegation-ended"]
    elif point in ("after-begin", "during-allocate-mkdir", "during-allocate-run-json"):
        assert res.returncode in (91, 92, 93)
        rep = _delegated.report(fx["grant"], fx["host"], attempt="att-1")
        assert rep["starts"][0]["outcome"] == "not-allocated"
        if point == "after-begin":
            assert rep["starts"][0]["leftover"] == []
        else:
            assert len(rep["starts"][0]["leftover"]) >= 1
    elif point in ("after-mark", "after-gate"):
        assert res.returncode in (94, 95)
        rep = _delegated.report(fx["grant"], fx["host"], attempt="att-1")
        assert rep["starts"][0]["outcome"] == "unfinished"
        for candidate_attempt in ("att-1", "att-2"):
            with pytest.raises(RunRefused) as unfinished_err:
                _run.execute(
                    _run.DevelopmentRequest(fx["repo"], fx["tip"], 5.0, ("/usr/bin/true",), None, "del-main", candidate_attempt),
                    fx["env"], diag=lambda _: None, progress=DevelopmentProgress(), actor_fds=stdio, host=fx["host"],
                )
            assert unfinished_err.value.code == "delegation-run-unfinished"
        run_id = rep["starts"][0]["run"]
        expected_close = 4 if point == "after-mark" else 3
        assert _run.close(run_id, fx["env"], diag=lambda _: None) == expected_close
    elif point == "after-verdict-before-settle":
        assert res.returncode == 96
        rep = _delegated.report(fx["grant"], fx["host"], attempt="att-1")
        assert rep["starts"][0]["outcome"] == "clean"
        assert rep["starts"][0]["disposition_sha256"] is not None

    # After recovery/settlement, att-1 can NEVER start again, and att-2 succeeds.
    with pytest.raises(RunRefused) as replay_err:
        _run.execute(
            _run.DevelopmentRequest(fx["repo"], fx["tip"], 5.0, ("/usr/bin/true",), None, "del-main", "att-1"),
            fx["env"], diag=lambda _: None, progress=DevelopmentProgress(), actor_fds=stdio, host=fx["host"],
        )
    assert replay_err.value.code == "delegation-attempt-used"

    status2 = _run.execute(
        _run.DevelopmentRequest(fx["repo"], fx["tip"], 15.0, ("/usr/bin/sh", "-c", ACTOR), None, "del-main", "att-2"),
        fx["env"], diag=lambda _: None, progress=DevelopmentProgress(), actor_fds=stdio, host=fx["host"],
    )
    assert status2 == 0


def test_a_crashed_last_start_is_unfinished(tmp_path, stdio):
    from autonomy.development import _delegated, _run

    fx = _build_fixture(tmp_path, starts=1)
    res = _run_crash_child(fx, "after-mark", "del-main", "att-1")
    assert res.returncode == 94
    rep = _delegated.report(fx["grant"], fx["host"])
    assert rep["starts"][0]["outcome"] == "unfinished"

    with pytest.raises(RunRefused) as before_close:
        _run.execute(
            _run.DevelopmentRequest(fx["repo"], fx["tip"], 5.0, ("/usr/bin/true",), None, "del-main", "att-2"),
            fx["env"], diag=lambda _: None, progress=DevelopmentProgress(), actor_fds=stdio, host=fx["host"],
        )
    assert before_close.value.code == "delegation-run-unfinished"

    assert _run.close(rep["starts"][0]["run"], fx["env"], diag=lambda _: None) == 4
    with pytest.raises(RunRefused) as after_close:
        _run.execute(
            _run.DevelopmentRequest(fx["repo"], fx["tip"], 5.0, ("/usr/bin/true",), None, "del-main", "att-2"),
            fx["env"], diag=lambda _: None, progress=DevelopmentProgress(), actor_fds=stdio, host=fx["host"],
        )
    assert after_close.value.code == "delegation-exhausted"
