import os
from dataclasses import replace

import pytest

from autonomy.development._records import DevelopmentAborted, allocate_run, development_places, file_digest, read_json
from autonomy.development._workspace import Limits, PreparedWorkspace, SourceBase
from autonomy.sandbox.spec import SandboxSpec
from development.test_workspace import fixture_git, make_source

pytestmark = pytest.mark.bwrap
REF = "refs/heads/development"


@pytest.fixture
def candidate():
    from autonomy.development import _candidate
    return _candidate


@pytest.fixture(scope="module", params=["sha1", "sha256"])
def bundles(tmp_path_factory, request):
    root = tmp_path_factory.mktemp("candidate")
    repo = root / "repo"
    base, other = make_source(repo, request.param)
    fixture_git(repo, "update-ref", "refs/heads/base", base)
    fixture_git(repo, "switch", "-c", "development", base)
    for text in ("one", "two"):
        (repo / "sample").write_text(text)
        fixture_git(repo, "commit", "-am", text)
    tip = fixture_git(repo, "rev-parse", "HEAD")
    assert tip != other
    base_bundle = root / "base.bundle"
    bundle = root / "fixture.bundle"
    fixture_git(repo, "bundle", "create", str(base_bundle), "refs/heads/base")
    fixture_git(repo, "bundle", "create", str(bundle), f"{base}..{REF}")
    return repo, request.param, base, tip, base_bundle.read_bytes(), bundle.read_bytes()


@pytest.fixture
def attempt(tmp_path, bundles):
    repo, fmt, base, tip, base_bundle, bundle = bundles
    directories = development_places({"HOME": str(tmp_path)})
    with allocate_run(directories, repository=repo, base=base, deadline_seconds=5) as run:
        objects = repo / ".git/objects"
        info = objects.stat()
        source = SourceBase(repo, objects, base, fmt, 0, (info.st_dev, info.st_ino))
        path = run.run_dir / "base.bundle"
        path.write_bytes(base_bundle)
        out = run.scratch / "outputs"
        out.mkdir()
        workspace = PreparedWorkspace(SandboxSpec(run.scratch), file_digest(path), (), "0" * 64)
        yield run, source, workspace, out / "candidate.bundle", bundle, tip


def refused(candidate, attempt, code, *, limits=Limits()):
    run, source, workspace, *_ = attempt
    with pytest.raises(DevelopmentAborted) as caught:
        candidate.validate_candidate(run, source, workspace, limits=limits)
    assert caught.value.finding.code == code
    assert not (run.run_dir / "candidate.json").exists()
    assert not (run.run_dir / "candidate.bundle").exists()


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink", "hardlink", "fifo", "oversized"])
def test_only_declared_regular_single_link_file_can_transfer(candidate, attempt, kind):
    _, _, _, path, bundle, _ = attempt
    other = path.with_name("undeclared")
    other.write_bytes(bundle)
    if kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        path.symlink_to(other)
    elif kind == "hardlink":
        os.link(other, path)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "oversized":
        path.write_bytes(b"long")
    refused(candidate, attempt, "development-bundle-missing" if kind == "missing" else "development-bundle-refused",
            limits=replace(Limits(), candidate_bytes=2))
    assert other.read_bytes() == bundle


@pytest.mark.parametrize("mutation", ["double-ref", "double-base", "extra-ref", "wrong-base", "wrong-ref", "filter"])
def test_header_requires_literal_multiplicity_and_matching_base(candidate, attempt, mutation):
    _, source, _, path, bundle, _ = attempt
    header, pack = bundle.split(b"\n\n", 1)
    lines = header.split(b"\n")
    before_ref, ref = lines[:-1], lines[-1]
    if mutation == "double-ref":
        lines.append(ref)
    elif mutation == "double-base":
        lines = [*before_ref, before_ref[-1], ref]
    elif mutation == "extra-ref":
        lines.append(ref.split()[0] + b" HEAD")
    elif mutation == "wrong-base":
        lines = [*before_ref[:-1], before_ref[-1].replace(source.oid.encode(), b"0" * len(source.oid)), ref]
    elif mutation == "wrong-ref":
        lines[-1] = ref.replace(REF.encode(), b"refs/heads/other")
    else:
        lines = [b"# v3 git bundle", b"@filter=blob:none", *lines[1:]]
    path.write_bytes(b"\n".join(lines) + b"\n\n" + pack)
    refused(candidate, attempt, "development-bundle-header-invalid")


def test_confined_receiver_checks_git_and_ancestry(candidate, attempt):
    run, source, workspace, path, bundle, tip = attempt
    path.write_bytes(bundle)
    result = candidate.validate_candidate(run, source, workspace, limits=Limits())
    assert result.tip == tip
    receipt_digest = candidate.publish_candidate(run, result, grant_sha256="2" * 64, base=source.oid)
    receipt = read_json(run.run_dir / "candidate.json")
    assert receipt_digest == file_digest(run.run_dir / "candidate.json")
    assert receipt["bundle_sha256"] == file_digest(run.run_dir / "candidate.bundle")
    assert receipt["base_sha256"] == workspace.base_sha256
    assert (run.run_dir / "candidate.bundle").read_bytes() == bundle
    assert not (run.run_dir / "disposition.json").exists()


@pytest.mark.parametrize("damage", ["truncated", "base-as-tip", "fsck"])
def test_confined_receiver_refuses_unproven_git_history(candidate, attempt, damage, monkeypatch):
    _, source, _, path, bundle, tip = attempt
    if damage == "truncated":
        bundle = bundle[:-10]
    elif damage == "base-as-tip":
        bundle = bundle.replace(tip.encode() + b" " + REF.encode(), source.oid.encode() + b" " + REF.encode(), 1)
    else:
        def strict_refusal(*args, **kwargs):
            raise candidate.GitFailed("git fsck --strict: fixture object check refused")
        monkeypatch.setattr(candidate, "run_worker", strict_refusal)
    path.write_bytes(bundle)
    refused(candidate, attempt, "development-bundle-validation-failed")


def test_receiver_refuses_resource_overflow(candidate, attempt):
    _, _, _, path, bundle, _ = attempt
    path.write_bytes(bundle)
    refused(candidate, attempt, "development-bundle-validation-failed",
            limits=replace(Limits(), receiver_storage_bytes=4096))


@pytest.mark.parametrize("fails", ["artifact", "receipt"])
def test_receipt_cannot_publish_before_artifact_durability(candidate, attempt, monkeypatch, fails):
    run, source, workspace, path, bundle, _ = attempt
    path.write_bytes(bundle)
    result = candidate.validate_candidate(run, source, workspace, limits=Limits())

    def fail(*args, **kwargs):
        raise OSError("fixture storage failure")

    monkeypatch.setattr(candidate, "fsync_dir" if fails == "artifact" else "publish_json", fail)
    with pytest.raises(DevelopmentAborted) as caught:
        candidate.publish_candidate(run, result, grant_sha256="2" * 64, base=source.oid)
    assert caught.value.finding.code == "development-candidate-unrecorded"
    assert not (run.run_dir / "candidate.json").exists()
