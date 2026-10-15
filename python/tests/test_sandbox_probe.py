import os
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


def test_a_probe_timeout_is_typed(layout, monkeypatch):
    def hung(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 60)

    monkeypatch.setattr(subprocess, "run", hung)
    with pytest.raises(SandboxUnproven) as caught:
        probe(SandboxSpec(scratch=layout["scratch"]), (layout["corpus"],))
    assert caught.value.code == "probe-failed"
    with pytest.raises(SandboxUnproven) as caught:
        preflight(which=lambda _: "/usr/bin/bwrap")
    assert caught.value.code == "userns-unavailable"


def test_non_utf8_probe_output_is_typed(layout, monkeypatch):
    path = str(layout["corpus"].resolve())

    def garbled(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=b"\xff\xfe " + path.encode() + b"\n", stderr=b"")

    monkeypatch.setattr(subprocess, "run", garbled)
    with pytest.raises(SandboxUnproven) as caught:
        probe(SandboxSpec(scratch=layout["scratch"]), (layout["corpus"],))
    assert caught.value.code == "probe-reachable"


@pytest.mark.bwrap
def test_the_preflight_and_the_probe_never_inherit_stdin(layout, monkeypatch):
    calls: list[dict] = []
    real = subprocess.run

    def recording(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording)
    prove(SandboxSpec(scratch=layout["scratch"]), (layout["corpus"],))
    assert len(calls) == 2
    assert all(call.get("stdin") is subprocess.DEVNULL for call in calls)


def test_a_child_that_inherits_stdin_consumes_the_callers_bytes():
    for stdin, left in ((None, b""), (subprocess.DEVNULL, b"early\n")):
        read_end, write_end = os.pipe()
        os.write(write_end, b"early\n")
        os.close(write_end)
        try:
            subprocess.run(["/usr/bin/head", "-c", "6"], stdin=read_end if stdin is None else stdin, stdout=subprocess.DEVNULL)
            assert os.read(read_end, 64) == left
        finally:
            os.close(read_end)
