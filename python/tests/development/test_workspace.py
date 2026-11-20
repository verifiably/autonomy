import hashlib
import os
import subprocess
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from autonomy.development._records import DevelopmentAborted, allocate_run, development_places
from autonomy.run import RunRefused

pytestmark = pytest.mark.bwrap


def fixture_git(repo: Path, *args: str) -> str:
    home = repo.parent / "fixture-home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": "/usr/bin", "HOME": str(home), "LC_ALL": "C",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }
    return subprocess.run(
        ["/usr/bin/git", "-C", str(repo), *args],
        env=env, stdin=subprocess.DEVNULL, check=True, capture_output=True, text=True, timeout=12,
    ).stdout.strip()


def make_source(directory: Path, object_format="sha1"):
    directory.mkdir()
    fixture_git(directory, "init", "--template=", "-b", "main", f"--object-format={object_format}")
    assert Path(fixture_git(directory, "rev-parse", "--show-toplevel")) == directory
    assert Path(fixture_git(directory, "rev-parse", "--absolute-git-dir")).is_relative_to(directory)
    for title in ("base", "later"):
        (directory / "sample").write_text(title)
        fixture_git(directory, "add", "sample")
        fixture_git(directory, "commit", "-m", title)
    base = fixture_git(directory, "rev-parse", "HEAD~")
    fixture_git(directory, "switch", "-c", "unrelated", base)
    (directory / "other").write_text("out of scope")
    fixture_git(directory, "add", "other")
    fixture_git(directory, "commit", "-m", "unrelated")
    other = fixture_git(directory, "rev-parse", "HEAD")
    return base, other


def snapshot(repo: Path):
    return {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in repo.rglob("*") if p.is_file()}


@pytest.fixture
def workspace():
    from autonomy.development import _workspace
    return _workspace


@pytest.fixture
def fixture_source(tmp_path):
    repo = tmp_path / "origin"
    base, other = make_source(repo)
    return repo, base, other


@pytest.fixture
def places(tmp_path):
    return development_places({
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
    })


def test_admits_non_tip_commit_without_source_config(workspace, fixture_source):
    repo, base, _other = fixture_source
    (repo / ".git/config").write_text("[malformed")
    before = snapshot(repo)
    result = workspace.admit_source(repo, base, limits=workspace.Limits())
    assert (result.oid, result.objects, result.repository) == (base, repo / ".git/objects", repo)
    assert snapshot(repo) == before


@pytest.mark.parametrize(("object_format", "pack"), [("sha1", False), ("sha1", True), ("sha256", True)])
def test_exports_only_pinned_reachable_objects(workspace, places, tmp_path, object_format, pack):
    repo = tmp_path / "source"
    base, other = make_source(repo, object_format)
    if pack:
        fixture_git(repo, "repack", "-ad")
    closure = set(fixture_git(repo, "rev-list", "--objects", "--no-object-names", base).splitlines())
    before = snapshot(repo)
    limits = workspace.Limits()
    source = workspace.admit_source(repo, base, limits=limits)
    with allocate_run(places, repository=repo, base=base, deadline_seconds=30) as run:
        prepared = workspace.prepare_workspace(run, source, config=places.config, limits=limits)
        seeded = run.scratch / "repo"
        assert fixture_git(seeded, "rev-parse", "HEAD") == base
        assert fixture_git(seeded, "bundle", "list-heads", str(run.run_dir / "base.bundle")) == f"{base} refs/heads/base"
        exported = set(fixture_git(seeded, "cat-file", "--batch-check=%(objectname)", "--batch-all-objects").splitlines())
        assert exported == closure
        assert other not in exported
        assert prepared.base_sha256 == hashlib.sha256((run.run_dir / "base.bundle").read_bytes()).hexdigest()
    assert snapshot(repo) == before


def test_rejects_incomplete_source_and_external_object_storage(workspace, fixture_source, tmp_path):
    repo, base, _ = fixture_source
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    fixture_git(incomplete, "init", "--template=")
    assert Path(fixture_git(incomplete, "rev-parse", "--absolute-git-dir")).is_relative_to(incomplete)
    (incomplete / ".git/objects/info/alternates").write_text(str(repo / ".git/objects") + "\n")
    with pytest.raises(RunRefused, match="development-base-invalid"):
        workspace.admit_source(incomplete, base, limits=workspace.Limits())
    with pytest.raises(RunRefused, match="development-base-invalid"):
        workspace.admit_source(repo, "abc", limits=workspace.Limits())
    with pytest.raises(RunRefused, match="development-repository-invalid"):
        workspace.admit_source(tmp_path / "missing", base, limits=workspace.Limits())


def test_prepare_fails_closed_on_export_or_resource_refusal(workspace, places, fixture_source):
    repo, base, _ = fixture_source
    limits = workspace.Limits()
    source = workspace.admit_source(repo, base, limits=limits)
    with allocate_run(places, repository=repo, base=base, deadline_seconds=30) as run:
        with pytest.raises(DevelopmentAborted, match="development-workspace-unproven"):
            workspace.prepare_workspace(run, source, config=places.config, limits=replace(limits, base_bytes=10))
        assert not (run.run_dir / "base.bundle").exists()


def test_materializes_disjoint_scratch_and_denies_the_source(workspace, places, fixture_source):
    from autonomy.sandbox.bwrap import build_argv
    repo, base, _ = fixture_source
    limits = workspace.Limits()
    source = workspace.admit_source(repo, base, limits=limits)
    with allocate_run(places, repository=repo, base=base, deadline_seconds=30) as run:
        prepared = workspace.prepare_workspace(run, source, config=places.config, limits=limits)
        assert {entry.name for entry in run.scratch.iterdir()} == {"repo", "home", "agent", "sessions", "outputs"}
        assert fixture_git(run.scratch / "repo", "remote") == ""
        assert not (run.scratch / "repo/.git/hooks").exists()
        assert not (run.scratch / "repo/.git/objects/info/alternates").exists()
        argv = build_argv(prepared.spec, ["/usr/bin/python3", "-I", "-c",
            "import os,sys; assert not os.path.lexists(sys.argv[1]); print(os.environ['VERIFIABLY_DEVELOPMENT_BASE'])",
            str(repo)], info_fd=None)
        probe = subprocess.run(argv, env={"PATH": os.defpath, "HOME": str(run.scratch / "home")},
                               capture_output=True, text=True, timeout=15, check=True)
        assert probe.stdout.strip() == base


def test_walk_checks_the_prepared_scratch_for_aliases(workspace, places, fixture_source, monkeypatch):
    repo, base, _ = fixture_source
    limits = workspace.Limits()
    source = workspace.admit_source(repo, base, limits=limits)
    real = workspace.walk

    def create_alias(user_trees, system_trees, denied, *, until):
        scratch = Path(user_trees[0])
        os.link(repo / "sample", scratch / "alias")
        try:
            return real(user_trees, system_trees, denied, until=until)
        finally:
            (scratch / "alias").unlink()

    with allocate_run(places, repository=repo, base=base, deadline_seconds=30) as run:
        monkeypatch.setattr(workspace, "walk", create_alias)
        with pytest.raises(DevelopmentAborted, match="development-sandbox-unproven"):
            workspace.prepare_workspace(run, source, config=places.config, limits=limits)
        assert not (run.run_dir / "walk.json").exists()


def test_preparation_refuses_source_directory_replaced_at_launch(workspace, places, fixture_source, monkeypatch):
    repo, base, _ = fixture_source
    limits = workspace.Limits()
    source = workspace.admit_source(repo, base, limits=limits)
    run_worker = workspace.run_worker
    original = source.objects / "pack"

    def replace_directory(*args, **kwargs):
        original.rename(original.with_name("original-pack"))
        original.mkdir()
        # Model a path resolving differently after the host pinned its
        # identity. The mounted identity must still match the witness.
        replacement = os.open(original, os.O_DIRECTORY | os.O_RDONLY)
        try:
            kwargs["source_mounts"] = tuple(
                replace(mount, fd=replacement) if mount.destination == "/source-objects/pack" else mount
                for mount in kwargs["source_mounts"]
            )
            return run_worker(*args, **kwargs)
        finally:
            os.close(replacement)

    # The genuine base remains locally available. The failure must be the
    # changed directory identity, independent of whether Git could proceed.
    with allocate_run(places, repository=repo, base=base, deadline_seconds=30) as run:
        monkeypatch.setattr(workspace, "run_worker", replace_directory)
        with pytest.raises(DevelopmentAborted, match="development-workspace-unproven.*source object directory changed"):
            workspace.prepare_workspace(run, source, config=places.config, limits=limits)
        assert not (run.run_dir / "base.bundle").exists()


def test_source_enumeration_cannot_outlive_preparation_deadline(workspace, fixture_source, monkeypatch):
    repo, base, _ = fixture_source
    now = 0.0
    scandir = os.scandir

    @contextmanager
    def slow_entries(directory):
        def elapsed(entries):
            nonlocal now
            for entry in entries:
                now += 0.25
                yield entry

        with scandir(directory) as entries:
            yield elapsed(entries)

    monkeypatch.setattr(workspace.time, "monotonic", lambda: now)
    monkeypatch.setattr(workspace.os, "scandir", slow_entries)

    def must_not_start(*args, **kwargs):
        pytest.fail("source enumeration ran past the preparation budget")

    monkeypatch.setattr(workspace, "run_worker", must_not_start)
    with pytest.raises(RunRefused, match="development-repository-invalid.*source inspection.*deadline"):
        workspace.admit_source(repo, base, limits=replace(workspace.Limits(), prepare_seconds=1))
