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
        scratch_fd = os.open(run.scratch, os.O_RDONLY | os.O_DIRECTORY)
        try:
            yield run, source, workspace, scratch_fd, out / "candidate.bundle", bundle, tip
        finally:
            os.close(scratch_fd)


def refused(candidate, attempt, code, *, limits=Limits()):
    run, source, workspace, scratch_fd, *_ = attempt
    with pytest.raises(DevelopmentAborted) as caught:
        candidate.validate_candidate(run, source, workspace, scratch_fd, limits=limits)
    assert caught.value.finding.code == code
    assert not (run.run_dir / "candidate.json").exists()
    assert not (run.run_dir / "candidate.bundle").exists()


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink", "hardlink", "fifo", "oversized"])
def test_only_declared_regular_single_link_file_can_transfer(candidate, attempt, kind):
    *_, path, bundle, _ = attempt
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
    _, source, _, _, path, bundle, _ = attempt
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
    run, source, workspace, scratch_fd, path, bundle, tip = attempt
    path.write_bytes(bundle)
    result = candidate.validate_candidate(run, source, workspace, scratch_fd, limits=Limits())
    assert result.tip == tip
    receipt_digest = candidate.publish_candidate(run, result, grant_sha256="2" * 64, base=source.oid)
    receipt = read_json(run.run_dir / "candidate.json")
    assert receipt["version"] == 2
    assert receipt_digest == file_digest(run.run_dir / "candidate.json")
    assert receipt["bundle_sha256"] == file_digest(run.run_dir / "candidate.bundle")
    assert receipt["base_sha256"] == workspace.base_sha256
    assert (run.run_dir / "candidate.bundle").read_bytes() == bundle
    assert not (run.run_dir / "disposition.json").exists()


@pytest.mark.parametrize("damage", ["truncated", "base-as-tip", "fsck"])
def test_confined_receiver_refuses_unproven_git_history(candidate, attempt, damage, monkeypatch):
    _, source, _, _, path, bundle, tip = attempt
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
    *_, path, bundle, _ = attempt
    path.write_bytes(bundle)
    refused(candidate, attempt, "development-bundle-validation-failed",
            limits=replace(Limits(), receiver_storage_bytes=4096))


@pytest.mark.parametrize("fails", ["artifact", "receipt"])
def test_receipt_cannot_publish_before_artifact_durability(candidate, attempt, monkeypatch, fails):
    run, source, workspace, scratch_fd, path, bundle, _ = attempt
    path.write_bytes(bundle)
    result = candidate.validate_candidate(run, source, workspace, scratch_fd, limits=Limits())

    def fail(*args, **kwargs):
        raise OSError("fixture storage failure")

    monkeypatch.setattr(candidate, "fsync_dir" if fails == "artifact" else "publish_json", fail)
    with pytest.raises(DevelopmentAborted) as caught:
        candidate.publish_candidate(run, result, grant_sha256="2" * 64, base=source.oid)
    assert caught.value.finding.code == "development-candidate-unrecorded"
    assert not (run.run_dir / "candidate.json").exists()


DECLARATION = b'{"version": 1, "reason": "the derived file is already current"}'


def declare(attempt, data=DECLARATION):
    *_, path, _, _ = attempt
    declaration = path.with_name("no-candidate.json")
    declaration.write_bytes(data)
    return declaration


def test_declared_no_candidate_releases_the_declaration(candidate, attempt):
    run, source, workspace, scratch_fd, *_ = attempt
    declare(attempt)
    result = candidate.validate_candidate(run, source, workspace, scratch_fd, limits=Limits())
    assert isinstance(result, candidate.DeclaredNoCandidate)
    digest = candidate.publish_no_candidate(run, result)
    assert (run.run_dir / "no-candidate.json").read_bytes() == DECLARATION
    assert digest == file_digest(run.run_dir / "no-candidate.json")
    assert not (run.run_dir / "candidate.json").exists()
    assert not (run.run_dir / "candidate.bundle").exists()
    assert not (run.run_dir / "disposition.json").exists()


@pytest.mark.parametrize("bundle_kind", ["valid", "refused"])
def test_a_declaration_beside_a_bundle_is_a_conflict(candidate, attempt, bundle_kind):
    *_, path, bundle, _ = attempt
    if bundle_kind == "valid":
        path.write_bytes(bundle)
    else:
        path.mkdir()
    declare(attempt)
    refused(candidate, attempt, "development-no-candidate-conflict")
    assert not (attempt[0].run_dir / "no-candidate.json").exists()


@pytest.mark.parametrize("data", [
    b"not json",
    b"[]",
    b'{"version": 2, "reason": "r"}',
    b'{"version": true, "reason": "r"}',
    b'{"version": 1}',
    b'{"version": 1, "reason": ""}',
    b'{"version": 1, "reason": "   "}',
    b'{"version": 1, "reason": 1}',
    b'{"version": 1, "reason": "r", "extra": 1}',
    b'{"version": 1, "reason": "r", "reason": "s"}',
    b'{"version": 1, "reason": "' + b"x" * 501 + b'"}',
    b'{"version": 1, "reason": "' + b"x" * 5000 + b'"}',
    b'\xff\xfe',
])
def test_an_invalid_declaration_is_quarantined(candidate, attempt, data):
    declare(attempt, data)
    refused(candidate, attempt, "development-no-candidate-invalid")
    assert not (attempt[0].run_dir / "no-candidate.json").exists()


@pytest.mark.parametrize("kind", ["directory", "symlink", "hardlink"])
def test_a_declaration_must_be_a_single_link_regular_file(candidate, attempt, kind):
    *_, path, _, _ = attempt
    declaration = path.with_name("no-candidate.json")
    other = path.with_name("undeclared")
    other.write_bytes(DECLARATION)
    if kind == "directory":
        declaration.mkdir()
    elif kind == "symlink":
        declaration.symlink_to(other)
    else:
        os.link(other, declaration)
    refused(candidate, attempt, "development-no-candidate-invalid")
