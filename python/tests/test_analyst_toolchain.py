import json
import subprocess
from pathlib import Path

import pytest

from autonomy.analyst.toolchain import (
    ANALYST_TOOLS, PI_ANTHROPIC_MODELS, PI_VERSION, THINKING_LEVELS, AnalystRefused, check_node, check_pi,
    check_thinking, default_node_dir, default_pi_dir, epoch_record,
)

DEFAULT_ANTHROPIC_MODELS = {
    "chat:claude-haiku-5-5": {
        "id": "claude-haiku-5-5",
        "type": "chat",
        "reasoning": True,
        "thinkingLevelMap": {
            "off": None, "minimal": None, "low": "low", "medium": "medium",
            "high": "high", "xhigh": "xhigh", "max": "max",
        },
        "compat": {"supportsMidConvoEffort": True, "forceAdaptiveThinking": True},
    },
    "chat:claude-opus-5-5": {
        "id": "claude-opus-5-5",
        "type": "chat",
        "reasoning": True,
        "thinkingLevelMap": {
            "off": None, "minimal": None, "low": "low", "medium": "medium",
            "high": "high", "xhigh": "xhigh", "max": "max",
        },
        "compat": {"supportsMidConvoEffort": True, "forceAdaptiveThinking": True},
    },
    "chat:claude-fable-5-1": {
        "id": "claude-fable-5-1",
        "type": "chat",
        "reasoning": True,
        "thinkingLevelMap": {"off": None, "xhigh": "xhigh", "max": "max"},
        "compat": {"supportsMidConvoEffort": True, "forceAdaptiveThinking": True},
    },
    "chat:claude-opus-4-6": {
        "id": "claude-opus-4-6",
        "type": "chat",
        "reasoning": True,
        "thinkingLevelMap": {"max": "max"},
        "compat": {"forceAdaptiveThinking": True},
    },
    "chat:claude-haiku-4-5": {
        "id": "claude-haiku-4-5",
        "type": "chat",
        "reasoning": True,
        "compat": {"supportsStrictTools": True},
    },
}


def pi_tree(root, version=PI_VERSION, executable=True, models=None):
    (root / "node_modules/.bin").mkdir(parents=True)
    pi = root / "node_modules/.bin/pi"
    pi.write_text("#!/bin/sh\n")
    if executable:
        pi.chmod(0o755)
    lock = {"packages": {"node_modules/@earendil-works/pi-coding-agent": {"version": version}}}
    (root / "package-lock.json").write_text(json.dumps(lock))
    registry = root / PI_ANTHROPIC_MODELS
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({"anthropic-messages": DEFAULT_ANTHROPIC_MODELS if models is None else models}))
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
    lambda r: (pi_tree(r), (r / PI_ANTHROPIC_MODELS).unlink())[0],
    lambda r: (pi_tree(r), (r / PI_ANTHROPIC_MODELS).write_text("{"))[0],
    lambda r: (pi_tree(r), (r / PI_ANTHROPIC_MODELS).write_text("{}"))[0],
    lambda r: pi_tree(r, models={}),
    lambda r: pi_tree(r, models={"chat:bad": {"id": "bad", "type": "chat", "thinkingLevelMap": "bad"}}),
    lambda r: r,
])
def test_anything_but_the_pin_is_pi_mismatch(tmp_path, make):
    make(tmp_path)
    with pytest.raises(AnalystRefused) as caught:
        check_pi(tmp_path)
    assert caught.value.code == "pi-mismatch"


def test_thinking_levels_follow_pi_model_registry(tmp_path):
    assert THINKING_LEVELS == ("off", "minimal", "low", "medium", "high", "xhigh", "max")
    models = {
        **DEFAULT_ANTHROPIC_MODELS,
        "chat:plain": {"id": "plain", "type": "chat", "reasoning": False},
        "chat:aliased": {
            "id": "aliased",
            "type": "chat",
            "reasoning": True,
            "thinkingLevelMap": {"xhigh": "high"},
            "compat": {"supportsMidConvoEffort": True, "forceAdaptiveThinking": True},
        },
    }
    install = check_pi(pi_tree(tmp_path, models=models))
    expected = {
        "claude-haiku-5-5": ("low", "medium", "high", "xhigh", "max"),
        "claude-opus-5-5": ("low", "medium", "high", "xhigh", "max"),
        "claude-fable-5-1": ("low", "medium", "high", "xhigh", "max"),
        "claude-opus-4-6": ("off", "low", "medium", "high", "max"),
        "claude-haiku-4-5": ("off", "minimal", "low", "medium", "high"),
        "plain": ("off",),
        "aliased": ("low", "medium", "high"),
    }
    for model, allowed in expected.items():
        for level in allowed:
            check_thinking(install, model, level)
        for level in (*[x for x in THINKING_LEVELS if x not in allowed], "bogus", ""):
            with pytest.raises(AnalystRefused) as caught:
                check_thinking(install, model, level)
            assert caught.value.code == "thinking-unsupported"
    with pytest.raises(AnalystRefused) as caught:
        check_thinking(install, "claude-unlisted", "low")
    assert caught.value.code == "model-unknown"


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

    record = epoch_record(install, tmp_path / "node", model="claude-opus-5-5", thinking="high", run=fake_run)
    assert record["model"] == "claude-opus-5-5" and record["thinking"] == "high"
    assert record["pi"] == {"version": PI_VERSION, "lock_sha256": install.lock_sha256}
    assert record["node"].endswith("9.9") and record["bwrap"].endswith("9.9") and record["rg"].endswith("9.9")
    assert record["fd"] is None
    assert all(env == {"PATH": "/usr/bin"} for _, env in calls)
