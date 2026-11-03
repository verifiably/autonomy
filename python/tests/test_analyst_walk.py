import json
import os
import subprocess
from pathlib import Path

import pytest

import autonomy
from autonomy.analyst.walk import collect_denied_inodes, mount_points, unescape_mountinfo, walk, walk_tree
from autonomy.sandbox.static import SandboxUnproven, system_symlinks

MOUNTINFO = (
    "36 25 0:32 / /mnt/with\\040space rw,relatime - tmpfs tmpfs rw\n"
    "37 25 8:1 /sub /mnt/bind\\011tab rw - ext4 /dev/sda1 rw\n"
)


def test_mountinfo_unescapes_octal_sequences(tmp_path):  # Review Focus 5
    assert unescape_mountinfo("a\\040b\\011c\\012d\\134e") == "a b\tc\nd\\e"
    info = tmp_path / "mountinfo"
    info.write_text(MOUNTINFO)
    assert mount_points(info) == (Path("/mnt/with space"), Path("/mnt/bind\ttab"))


def test_a_clean_tree_passes_and_is_counted(tmp_path):
    (tmp_path / "in/a").mkdir(parents=True)
    (tmp_path / "in/a/f").write_text("x")
    report = walk_tree(tmp_path / "in", frozenset(), hardlinks=True, mounts=())
    assert report.entries == 2 and report.skipped == []


def test_a_hard_link_to_a_denied_file_is_refused_as_hardlink(tmp_path):
    (tmp_path / "in").mkdir()
    (tmp_path / "key").mkdir()
    (tmp_path / "key/k").write_text("s")
    os.link(tmp_path / "key/k", tmp_path / "in/k2")
    with pytest.raises(SandboxUnproven) as caught:
        walk([tmp_path / "in"], [], [tmp_path / "key"])
    assert caught.value.code == "walk-hardlink"


def test_a_hard_linked_file_in_a_system_tree_passes_but_an_alias_does_not(tmp_path):
    (tmp_path / "sys").mkdir()
    (tmp_path / "sys/a").write_text("x")
    os.link(tmp_path / "sys/a", tmp_path / "sys/b")
    walk([], [tmp_path / "sys"], [])  # packaging hard links are fine in /usr and /etc
    (tmp_path / "key").mkdir()
    (tmp_path / "key/k").write_text("s")
    os.link(tmp_path / "key/k", tmp_path / "sys/k")
    with pytest.raises(SandboxUnproven) as caught:
        walk([], [tmp_path / "sys"], [tmp_path / "key"])
    assert caught.value.code == "walk-alias"


def test_a_symlink_to_a_denied_file_passes(tmp_path):
    (tmp_path / "in").mkdir()
    (tmp_path / "key").mkdir()
    (tmp_path / "key/k").write_text("s")
    (tmp_path / "in/link").symlink_to(tmp_path / "key/k")
    walk([tmp_path / "in"], [], [tmp_path / "key"])


def test_a_denied_file_contributes_its_own_inode(tmp_path):  # Review Focus 2
    (tmp_path / "in").mkdir()
    key = tmp_path / "key.json"
    key.write_text("s")
    assert collect_denied_inodes([key]) == frozenset({(key.stat().st_dev, key.stat().st_ino)})
    os.link(key, tmp_path / "in/alias")
    with pytest.raises(SandboxUnproven) as caught:
        walk([], [tmp_path / "in"], [key])  # as a system tree, so the alias rule fires, not hardlink
    assert caught.value.code == "walk-alias"


def test_a_missing_denied_path_is_skipped(tmp_path):
    assert collect_denied_inodes([tmp_path / "absent"]) == frozenset()


@pytest.mark.skipif(os.getuid() == 0, reason="root ignores directory modes")
def test_an_unlistable_denied_directory_is_refused(tmp_path):
    d = tmp_path / "key/private"
    d.mkdir(parents=True)
    (d / "k").write_text("s")
    d.chmod(0o000)
    try:
        with pytest.raises(SandboxUnproven) as caught:
            collect_denied_inodes([tmp_path / "key"])
        assert caught.value.code == "denied-unlistable"
    finally:
        d.chmod(0o700)


@pytest.mark.skipif(os.getuid() == 0, reason="root ignores directory modes")
def test_search_without_list_fails_and_neither_is_skipped(tmp_path):
    (tmp_path / "in").mkdir()
    only_x = tmp_path / "in/x"
    only_x.mkdir()
    only_x.chmod(0o100)
    try:
        with pytest.raises(SandboxUnproven) as caught:
            walk_tree(tmp_path / "in", frozenset(), hardlinks=True, mounts=())
        assert caught.value.code == "walk-unlistable"
    finally:
        only_x.chmod(0o700)
    only_x.rmdir()
    neither = tmp_path / "in/n"
    neither.mkdir()
    neither.chmod(0o000)
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


# E23's submount arms run inside a bwrap namespace the test builds: a same-filesystem
# bind needs a mount namespace, and the walk reads that namespace's mountinfo.
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
    links = [arg for target, link in system_symlinks() for arg in ("--symlink", target, link)]
    argv = ["bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr", *links, "--proc", "/proc",
            "--ro-bind", PACKAGE_PARENT, PACKAGE_PARENT, "--bind", str(tmp_path), str(tmp_path), *mount_args,
            "--", "/usr/bin/python3", "-I", "-c", SNIPPET, PACKAGE_PARENT, str(tmp_path / "in")]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
                            env={"PATH": "/usr/bin"})
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


def test_regular_file_input_walk_and_digest(tmp_path):
    from autonomy.analyst.walk import walk, walk_tree

    f = tmp_path / "disjoint.json"
    f.write_text('{"cohort": 1}\n')
    denied = tmp_path / "denied"
    denied.mkdir()
    (denied / "secret").write_text("k")

    report = walk([f], [], [denied], digest_inputs=[f])
    assert len(report.inputs) == 1
    digest = report.inputs[0]
    assert digest.path == str(f) and digest.kind == "file" and digest.files == 1
    assert digest.bytes == len('{"cohort": 1}\n') and len(digest.sha256) == 64
    assert report.to_json()["inputs"] == [digest.to_json()]

    # Changing bytes changes the digest
    f.write_text('{"cohort": 2}\n')
    report2 = walk([f], [], [denied], digest_inputs=[f])
    assert report2.inputs[0].sha256 != digest.sha256

    # Hard-linked regular-file input is refused walk-hardlink before hashing
    hard = tmp_path / "hard.json"
    os.link(f, hard)
    with pytest.raises(SandboxUnproven) as caught:
        walk([f], [], [denied], digest_inputs=[f])
    assert caught.value.code == "walk-hardlink"
    hard.unlink()

    # Regular-file input whose inode is under denied is refused walk-alias
    with pytest.raises(SandboxUnproven) as caught:
        walk([denied / "secret"], [], [denied], digest_inputs=[denied / "secret"])
    assert caught.value.code == "walk-alias"

    # Regular-file input that is itself a mount point in mountinfo is refused walk-submount
    with pytest.raises(SandboxUnproven) as caught:
        walk_tree(f, frozenset(), hardlinks=True, mounts=(f,), digest=True)
    assert caught.value.code == "walk-submount"


def test_directory_input_digest_covers_symlinks_and_empty_dirs_without_following_links(tmp_path):
    from autonomy.analyst.walk import walk

    bundle = tmp_path / "bundle"
    (bundle / "empty_sub").mkdir(parents=True)
    (bundle / "a.tsv").write_text("x\t1\n")
    denied = tmp_path / "denied"
    denied.mkdir()
    secret = denied / "secret.txt"
    secret.write_text("top-secret")
    # Dangling/denied symlink inside bundle is hashed by link target without following
    (bundle / "dangling").symlink_to(secret)

    r1 = walk([bundle], [], [denied], digest_inputs=[bundle]).inputs[0]
    assert r1.kind == "directory" and r1.files == 1 and r1.bytes == 4

    # Mutating file bytes changes directory sha256
    (bundle / "a.tsv").write_text("x\t2\n")
    r2 = walk([bundle], [], [denied], digest_inputs=[bundle]).inputs[0]
    assert r2.sha256 != r1.sha256

    # Renaming an empty subdirectory changes directory sha256
    (bundle / "empty_sub").rename(bundle / "empty_sub_2")
    r3 = walk([bundle], [], [denied], digest_inputs=[bundle]).inputs[0]
    assert r3.sha256 != r2.sha256

    # Retargeting symlink changes directory sha256
    (bundle / "dangling").unlink()
    (bundle / "dangling").symlink_to(tmp_path / "other")
    r4 = walk([bundle], [], [denied], digest_inputs=[bundle]).inputs[0]
    assert r4.sha256 != r3.sha256


def test_fifo_inside_declared_directory_input_is_refused_walk_special(tmp_path):
    from autonomy.analyst.walk import walk

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    os.mkfifo(bundle / "pipe")
    with pytest.raises(SandboxUnproven) as caught:
        walk([bundle], [], [], digest_inputs=[bundle])
    assert caught.value.code == "walk-special"

