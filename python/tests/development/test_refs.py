import os
from pathlib import Path

import pytest

from autonomy.run import RunRefused
from development.test_workspace import fixture_git, make_source


@pytest.fixture
def refs():
    from autonomy.development import _refs

    return _refs


def test_reads_loose_and_packed_and_loose_wins_over_packed(refs, tmp_path):
    repo = tmp_path / "repo"
    base, other = make_source(repo)
    main_tip = fixture_git(repo, "rev-parse", "refs/heads/main")
    assert refs.branch_tip(repo, "refs/heads/main") == main_tip

    fixture_git(repo, "pack-refs", "--all")
    assert not (repo / ".git/refs/heads/main").exists()
    assert refs.branch_tip(repo, "refs/heads/main") == main_tip
    assert refs.branch_tip(repo, "refs/heads/unrelated") == other

    (repo / ".git/refs/heads").mkdir(parents=True, exist_ok=True)
    (repo / ".git/refs/heads/main").write_text(base + "\n", encoding="ascii")
    assert refs.branch_tip(repo, "refs/heads/main") == base


def test_reads_sha256_loose_and_packed_tips(refs, tmp_path):
    repo = tmp_path / "repo256"
    _, other = make_source(repo, object_format="sha256")
    assert len(other) == 64
    assert refs.branch_tip(repo, "refs/heads/unrelated") == other
    fixture_git(repo, "pack-refs", "--all")
    assert refs.branch_tip(repo, "refs/heads/unrelated") == other


def test_packed_refs_handles_comments_and_peeled_tag_lines(refs, tmp_path):
    repo = tmp_path / "repo"
    base, _ = make_source(repo)
    fixture_git(repo, "tag", "-a", "-m", "annotated", "v1", base)
    fixture_git(repo, "pack-refs", "--all")
    packed = (repo / ".git/packed-refs").read_text(encoding="ascii")
    assert packed.startswith("# pack-refs") and "\n^" in packed
    main_tip = fixture_git(repo, "rev-parse", "refs/heads/main")
    assert refs.branch_tip(repo, "refs/heads/main") == main_tip


@pytest.mark.parametrize(
    "case",
    [
        "symbolic",
        "reftable",
        "symlink-repo",
        "symlink-dotgit",
        "symlink-heads",
        "symlink-leaf",
        "symlink-packed",
        "missing-no-packed",
        "missing-with-packed",
        "directory-at-ref",
        "oversize-packed",
        "bad-ref-syntax",
        "malformed-loose",
    ],
)
def test_branch_tip_refuses_unsupported_or_damaged_refs(refs, tmp_path, case):
    repo = tmp_path / "repo"
    base, _ = make_source(repo)
    target_repo = repo
    target_ref = "refs/heads/main"

    if case == "symbolic":
        (repo / ".git/refs/heads/main").write_text("ref: refs/heads/unrelated\n", encoding="ascii")
    elif case == "reftable":
        (repo / ".git/reftable").mkdir()
    elif case == "symlink-repo":
        link = tmp_path / "repo-link"
        link.symlink_to(repo)
        target_repo = link
    elif case == "symlink-dotgit":
        real_git = tmp_path / "real-git"
        (repo / ".git").rename(real_git)
        (repo / ".git").symlink_to(real_git)
    elif case == "symlink-heads":
        fixture_git(repo, "pack-refs", "--all")
        real_heads = tmp_path / "real-heads"
        (repo / ".git/refs/heads").rename(real_heads)
        (repo / ".git/refs/heads").symlink_to(real_heads)
    elif case == "symlink-leaf":
        other_file = tmp_path / "oid-file"
        other_file.write_text(base + "\n", encoding="ascii")
        (repo / ".git/refs/heads/main").unlink()
        (repo / ".git/refs/heads/main").symlink_to(other_file)
    elif case == "symlink-packed":
        fixture_git(repo, "pack-refs", "--all")
        real_packed = tmp_path / "real-packed"
        (repo / ".git/packed-refs").rename(real_packed)
        (repo / ".git/packed-refs").symlink_to(real_packed)
    elif case == "missing-no-packed":
        (repo / ".git/packed-refs").unlink(missing_ok=True)
        target_ref = "refs/heads/absent"
    elif case == "missing-with-packed":
        fixture_git(repo, "pack-refs", "--all")
        target_ref = "refs/heads/absent"
    elif case == "directory-at-ref":
        fixture_git(repo, "update-ref", "refs/heads/group/topic", base)
        target_ref = "refs/heads/group"
    elif case == "oversize-packed":
        fixture_git(repo, "pack-refs", "--all")
        os.truncate(repo / ".git/packed-refs", (32 << 20) + 1)
    elif case == "bad-ref-syntax":
        target_ref = "refs/tags/v1"
    elif case == "malformed-loose":
        (repo / ".git/refs/heads/main").write_text("not-an-oid\n", encoding="ascii")

    with pytest.raises(RunRefused) as caught:
        refs.branch_tip(target_repo, target_ref)
    assert caught.value.code == "delegation-base"
