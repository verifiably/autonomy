import dataclasses
import os
import subprocess
from pathlib import Path

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
    spec = SandboxSpec(scratch=layout["scratch"], env={"A": "1"})
    argv = build_argv(spec, ["/usr/bin/true"], info_fd=7)
    assert argv[:3] == ["bwrap", "--unshare-all", "--die-with-parent"]
    for flag in ("--new-session", "--clearenv"):
        assert flag in argv
    assert argv[argv.index("--info-fd") + 1] == "7"
    assert argv[-2:] == ["--", "/usr/bin/true"]
    scratch = str(layout["scratch"])
    assert ["--bind", scratch, scratch] == argv[argv.index("--bind"):argv.index("--bind") + 3]
    assert argv[argv.index("--chdir") + 1] == scratch


def test_no_sandbox_shares_the_host_network(layout):
    spec = SandboxSpec(scratch=layout["scratch"])
    assert "--share-net" not in build_argv(spec, ["/usr/bin/true"], info_fd=None)
    # Plan A's `host` mode is removed (decision 13): the spec has no network field at all.
    assert "network" not in {f.name for f in dataclasses.fields(SandboxSpec)}


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
        return subprocess.CompletedProcess(argv, 0, stdout=b"\xff\xfe " + path.encode() + b"\nENETUNREACH net:192.0.2.1\nENETUNREACH net:2001:db8::1\n", stderr=b"")

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


@pytest.mark.bwrap
def test_the_probe_reports_both_addresses_unreachable(layout, monkeypatch):
    seen = {}
    real_run = subprocess.run

    def spy(argv, **kwargs):
        result = real_run(argv, **kwargs)
        seen["stdout"] = result.stdout.decode()
        return result

    monkeypatch.setattr(subprocess, "run", spy)
    probe(SandboxSpec(scratch=layout["scratch"]), [])
    lines = seen["stdout"].splitlines()
    assert lines[-2] == "ENETUNREACH net:192.0.2.1"
    assert lines[-1].split()[0] in ("ENETUNREACH", "EAFNOSUPPORT")
    assert lines[-1].split()[1] == "net:2001:db8::1"


def _has_default_route() -> bool:
    lines = Path("/proc/net/route").read_text().splitlines()[1:]
    return any(line.split()[1] == "00000000" for line in lines)


@pytest.mark.bwrap
@pytest.mark.skipif(not _has_default_route(), reason="the negative needs an IPv4 default route on the host")
def test_a_sandbox_sharing_the_host_network_fails_the_probe(layout, monkeypatch):
    # Negative: a test hook that adds --share-net (decision 13's removed mode). With a
    # default route, 192.0.2.1 times out or connects instead of ENETUNREACH.
    from autonomy.sandbox import bwrap

    real = bwrap.build_argv

    def shared(spec, argv, *, info_fd):
        args = real(spec, argv, info_fd=info_fd)
        return [args[0], args[1], "--share-net", *args[2:]]

    monkeypatch.setattr(bwrap, "build_argv", shared)
    with pytest.raises(SandboxUnproven) as caught:
        bwrap.probe(SandboxSpec(scratch=layout["scratch"]), [])
    assert caught.value.code == "probe-network"
    assert caught.value.path == "net:192.0.2.1"
