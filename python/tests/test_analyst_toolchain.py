import json
import subprocess
from pathlib import Path

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
    (root / "bin/node").write_text("#!/bin/sh\n")
    (root / "bin/node").chmod(0o755)
    for name in extra:
        (root / "bin" / name).write_text("")
    return root


def test_the_tool_list_is_the_checked_set():
    assert ANALYST_TOOLS == ("read", "bash", "grep", "find", "ls", "write")


def test_a_pinned_install_passes(tmp_path):
    install = check_pi(pi_tree(tmp_path))
    assert install.version == PI_VERSION and install.executable == tmp_path.resolve() / "node_modules/.bin/pi"
    assert len(install.lock_sha256) == 64
    link = tmp_path.parent / f"{tmp_path.name}-link"
    link.symlink_to(tmp_path)
    assert check_pi(link).dir == tmp_path.resolve()


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
    link = tmp_path / "link"
    link.symlink_to(node_tree(tmp_path / "real"))
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
