import subprocess

import pytest

from autonomy.sandbox.bwrap import build_argv, preflight, probe, prove
from autonomy.sandbox.spec import SandboxSpec
from autonomy.sandbox.static import SandboxUnproven


@pytest.fixture
def layout(tmp_path):
    corpus = tmp_path / "corpus root"  # a space, so the probe's parsing is exercised
    ops = tmp_path / "ops"
    scratch = tmp_path / "scratch"
    for d in (corpus, ops, scratch):
        d.mkdir()
    return {"corpus": corpus, "ops": ops, "scratch": scratch, "tmp": tmp_path}


def test_argv_shape(layout):
    spec = SandboxSpec(scratch=layout["scratch"], network="host", env={"A": "1"})
    argv = build_argv(spec, ["/usr/bin/true"], info_fd=7)
    assert argv[:3] == ["bwrap", "--unshare-all", "--share-net"]
    for flag in ("--die-with-parent", "--new-session", "--clearenv"):
        assert flag in argv
    assert argv[argv.index("--info-fd") + 1] == "7"
    assert "--block-fd" not in argv
    held = build_argv(spec, ["/usr/bin/true"], info_fd=7, block_fd=8)
    assert held[held.index("--block-fd") + 1] == "8"
    assert argv[-2:] == ["--", "/usr/bin/true"]
    scratch = str(layout["scratch"])
    assert ["--bind", scratch, scratch] == argv[argv.index("--bind"):argv.index("--bind") + 3]
    assert argv[argv.index("--chdir") + 1] == scratch


def test_no_network_unless_asked(layout):
    assert "--share-net" not in build_argv(SandboxSpec(scratch=layout["scratch"]), ["/usr/bin/true"], info_fd=None)


def test_a_missing_bwrap_is_typed_before_anything_runs(layout):
    with pytest.raises(SandboxUnproven) as caught:
        prove(SandboxSpec(scratch=layout["scratch"]), (layout["corpus"],), which=lambda _: None)
    assert caught.value.code == "bwrap-missing"


@pytest.mark.bwrap
def test_preflight_passes_on_this_host():
    preflight()


@pytest.mark.bwrap
def test_the_probe_passes_when_nothing_denied_is_bound(layout):
    prove(SandboxSpec(scratch=layout["scratch"]), (layout["corpus"], layout["ops"]))


@pytest.mark.bwrap
def test_a_planted_bind_fails_the_probe(layout):
    # bypass the static check to prove the probe is a second, independent proof
    spec = SandboxSpec(scratch=layout["scratch"], ro_binds=(layout["corpus"],))
    with pytest.raises(SandboxUnproven) as caught:
        probe(spec, (layout["corpus"], layout["ops"]))
    assert caught.value.code == "probe-reachable"
    assert caught.value.path == str(layout["corpus"])


@pytest.mark.bwrap
def test_prove_stops_a_planted_bind_at_the_static_check(layout):
    spec = SandboxSpec(scratch=layout["scratch"], ro_binds=(layout["corpus"],))
    with pytest.raises(SandboxUnproven) as caught:
        prove(spec, (layout["corpus"],))
    assert caught.value.code == "bind-overlaps-denied"


@pytest.mark.bwrap
def test_a_denied_path_that_does_not_exist_passes_the_probe(layout):  # Review Focus 4
    prove(SandboxSpec(scratch=layout["scratch"]), (layout["tmp"] / "no-store-root",))


@pytest.mark.bwrap
def test_the_actor_sees_its_scratch_at_its_host_path(layout):
    (layout["scratch"] / "hello").write_text("hi")
    argv = build_argv(SandboxSpec(scratch=layout["scratch"]), ["/usr/bin/cat", "hello"], info_fd=None)
    out = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=True)
    assert out.stdout == "hi"
