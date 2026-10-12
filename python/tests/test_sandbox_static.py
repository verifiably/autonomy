from pathlib import Path

import pytest

from autonomy.sandbox.spec import SandboxSpec
from autonomy.sandbox.static import SandboxUnproven, check_binds


@pytest.fixture
def layout(tmp_path):
    world = tmp_path / "world"
    corpus = world / "corpus"
    ops = tmp_path / "ops"
    scratch = tmp_path / "scratch"
    tools = tmp_path / "tools"
    for d in (corpus, ops, scratch, tools):
        d.mkdir(parents=True)
    return {"world": world, "corpus": corpus, "ops": ops, "scratch": scratch, "tools": tools, "tmp": tmp_path}


def denied(layout):
    return (layout["world"], layout["corpus"], layout["ops"])


def refused(spec, layout, code="bind-overlaps-denied"):
    with pytest.raises(SandboxUnproven) as caught:
        check_binds(spec, denied(layout))
    assert caught.value.code == code
    return caught.value


def test_an_unrelated_bind_passes(layout):
    check_binds(SandboxSpec(scratch=layout["scratch"], ro_binds=(layout["tools"],)), denied(layout))


def test_a_symlink_alias_of_a_corpus_is_refused(layout):
    alias = layout["tmp"] / "alias"
    alias.symlink_to(layout["corpus"])
    refused(SandboxSpec(scratch=layout["scratch"], ro_binds=(alias,)), layout)


def test_a_parent_of_the_operations_root_is_refused(layout):
    refused(SandboxSpec(scratch=layout["scratch"], ro_binds=(layout["tmp"],)), layout)


def test_a_child_of_a_denied_root_is_refused(layout):
    inner = layout["corpus"] / "inner"
    inner.mkdir()
    refused(SandboxSpec(scratch=layout["scratch"], ro_binds=(inner,)), layout)


def test_the_root_directory_is_refused(layout):
    refused(SandboxSpec(scratch=layout["scratch"], ro_binds=(Path("/"),)), layout)


def test_a_scratch_inside_a_denied_root_is_refused(layout):
    inside = layout["ops"] / "scratch"
    inside.mkdir()
    refused(SandboxSpec(scratch=inside), layout)


def test_a_missing_bind_source_is_typed(layout):  # Review Focus 3
    refused(SandboxSpec(scratch=layout["scratch"], ro_binds=(layout["tmp"] / "nope",)), layout, code="bind-missing")


def test_a_dangling_symlink_is_typed(layout):  # Review Focus 3
    dangling = layout["tmp"] / "dangling"
    dangling.symlink_to(layout["tmp"] / "gone")
    refused(SandboxSpec(scratch=layout["scratch"], ro_binds=(dangling,)), layout, code="bind-missing")


def test_a_denied_path_that_does_not_exist_is_ignored(layout):  # Review Focus 4
    check_binds(SandboxSpec(scratch=layout["scratch"]), (*denied(layout), layout["tmp"] / "no-store-root"))


def test_socket_and_token_sources_are_checked(layout):
    token = layout["ops"] / "token"
    token.write_text("t")
    refused(SandboxSpec(scratch=layout["scratch"], token=token), layout)


def test_bind_sources_lists_every_source(layout):
    sock_dir = layout["tmp"] / "run"
    sock_dir.mkdir()
    spec = SandboxSpec(scratch=layout["scratch"], ro_binds=(layout["tools"],),
                       socket=sock_dir / "endpoint.sock", token=sock_dir / "token")
    assert spec.bind_sources() == (Path("/usr"), Path("/etc"), layout["tools"], layout["scratch"],
                                   sock_dir / "endpoint.sock", sock_dir / "token")
