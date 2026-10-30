"""The front door's wiring: which recipes run, which the test policy skips, and what
the hooks pay for. Each test runs the real justfile, hook and vendored tt in an
isolated Git repository whose commands are replaced by markers, so a test proves
the routing without running the suite it routes."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

COMMANDS = dict(check_hygiene_cmd="python3 marker.py hygiene", fast_cmd="python3 marker.py fast",
                test_cmd="python3 marker.py suite", one_cmd="python3 marker.py focused")

ALLOWED_GIT = {"GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
               "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"}

MARKER = """\
import json, os, pathlib, sys
with pathlib.Path(__file__).with_name("markers").open("a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
sys.exit(7 if os.environ.get("FAIL_TARGET") == sys.argv[1] else 0)
"""

PUSHED, ABSENT = "a" * 40, "0" * 40


def refs(ref: str) -> str:
    return f"{ref} {PUSHED} {ref} {ABSENT}\n"


class FrontDoor:
    def __init__(self, base: Path):
        self.root = base / "code"
        self.root.mkdir()
        home = base / "home"
        home.mkdir()
        tools = []
        for name in ("just", "git", "python3", "sh"):
            found = shutil.which(name)
            if found is None:
                pytest.fail(f"the front-door tests need {name} on PATH")
            tools.append(str(Path(found).parent))
        self.env = {"PATH": os.pathsep.join([*dict.fromkeys(tools), os.defpath]),
                    "HOME": str(home), "USER": "fixture",
                    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                    "TT_LOG": str(base / "runs.jsonl")}
        self.git("init", "-q")
        assert self.git("rev-parse", "--show-toplevel") == str(self.root)
        assert Path(self.git("rev-parse", "--absolute-git-dir")).is_relative_to(self.root)
        text = (REPO / "justfile").read_text()
        for key, value in COMMANDS.items():
            text, count = re.subn(rf'(?m)^{key} := ".*"$', f'{key} := "{value}"', text)
            assert count == 1, f"justfile has no single {key} line"
        (self.root / "justfile").write_text(text)
        for path in ("tools/tt", ".githooks/pre-push"):
            (self.root / path).parent.mkdir(exist_ok=True)
            shutil.copy2(REPO / path, self.root / path)
        (self.root / "tasks").mkdir()
        (self.root / "tasks/.config.toml").write_text('prefix = "autonomy"\n')
        (self.root / "marker.py").write_text(MARKER)
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.root), *args], env=self.env, text=True,
                              capture_output=True, check=True).stdout.strip()

    def policy(self, enabled: bool, targets: list[str]) -> None:
        (self.root / ".tt.toml").write_text(f"automatic_broad = {str(enabled).lower()}\n"
                                            f"broad_targets = {json.dumps(targets)}\n")

    def recipe(self, name: str, *args: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(["just", name, *args], cwd=self.root, env={**self.env, **env},
                              text=True, capture_output=True)

    def push(self, remote: str, refs: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(["sh", ".githooks/pre-push", remote, "/fixture/remote"], input=refs,
                              cwd=self.root, env={**self.env, **env}, text=True, capture_output=True)

    def markers(self) -> list[list[str]]:
        path = self.root / "markers"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def rows(self) -> list[dict]:
        path = Path(self.env["TT_LOG"])
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def pairs(self) -> list[tuple[str, str]]:
        return [(row["target"], row["execution"]) for row in self.rows()]


@pytest.fixture
def front_door(tmp_path):
    return FrontDoor(tmp_path.resolve())


def test_the_fixture_environment_holds_no_force_or_hosted_marker(front_door):
    assert not {"TT_FORCE", "GITHUB_ACTIONS", "CI"} & front_door.env.keys()
    assert not any(k.startswith("GIT_") and k not in ALLOWED_GIT for k in front_door.env)


def test_recipes_follow_the_shared_shape(front_door):
    result = subprocess.run(["just", "--summary"], cwd=front_door.root, env=front_door.env,
                            text=True, capture_output=True, check=True)
    assert set(result.stdout.split()) == {
        "test-fast", "test-one", "test", "test-full", "live-egress", "check", "check-hygiene", "gate",
        "docs", "work-link", "setup", "hook-pre-commit", "hook-pre-commit-docs", "hook-pre-push",
        "hook-pre-push-fast"}


def test_setup_syncs_from_the_frozen_lock(front_door):
    result = subprocess.run(["just", "--justfile", str(REPO / "justfile"), "--evaluate", "setup_cmd"],
                            cwd=REPO, env=front_door.env, text=True, capture_output=True, check=True)
    assert result.stdout == "just work-link python/.venv && cd python && uv sync --frozen"


def test_policy_off_push_runs_hygiene_once_and_records_the_suite_skip(front_door):
    front_door.policy(False, ["test", "test-fast"])
    result = front_door.recipe("hook-pre-push")
    assert result.returncode == 0, result.stderr
    assert front_door.markers() == [["hygiene"]]
    assert front_door.pairs() == [("hook-pre-push", "ran"), ("test", "skipped")]


def test_policy_off_covered_push_skips_the_fast_suite(front_door):
    front_door.policy(False, ["test", "test-fast"])
    result = front_door.recipe("hook-pre-push-fast")
    assert result.returncode == 0, result.stderr
    assert front_door.markers() == [["hygiene"]]
    assert front_door.pairs() == [("hook-pre-push-fast", "ran"), ("test-fast", "skipped")]


def test_policy_on_push_runs_hygiene_then_the_suite(front_door):
    front_door.policy(True, ["test", "test-fast"])
    result = front_door.recipe("hook-pre-push")
    assert result.returncode == 0, result.stderr
    assert front_door.markers() == [["hygiene"], ["suite"]]
    assert [(r["target"], r["execution_reason"]) for r in front_door.rows()] == [
        ("hook-pre-push", "default"), ("test", "policy-enabled")]


def test_hygiene_failure_stops_before_the_suite(front_door):
    front_door.policy(True, ["test", "test-fast"])
    result = front_door.recipe("hook-pre-push", FAIL_TARGET="hygiene")
    assert result.returncode == 7, result.stderr
    assert [r["target"] for r in front_door.rows()] == ["hook-pre-push"]


def test_a_suite_failure_is_the_push_status(front_door):
    front_door.policy(True, ["test", "test-fast"])
    result = front_door.recipe("hook-pre-push-fast", FAIL_TARGET="fast")
    assert result.returncode == 7, result.stderr
    assert front_door.markers() == [["hygiene"], ["fast"]]


def test_commit_hooks_keep_hygiene_under_policy_off(front_door):
    front_door.policy(False, ["test", "test-fast"])
    for name in ("hook-pre-commit", "hook-pre-commit-docs"):
        result = front_door.recipe(name)
        assert result.returncode == 0, result.stderr
    assert front_door.markers() == [["hygiene"], ["hygiene"]]
    assert all(r["execution"] == "ran" for r in front_door.rows())


def test_full_alias_records_one_forced_run_and_preserves_failure(front_door):
    front_door.policy(False, ["test", "test-fast"])
    result = front_door.recipe("test-full", FAIL_TARGET="suite")
    assert result.returncode == 7, result.stderr
    assert front_door.markers() == [["suite"]]
    assert [(r["target"], r["execution_reason"], r["exit"]) for r in front_door.rows()] == [
        ("test", "forced", 7)]


def test_focused_route_runs_and_forwards_each_argument_under_policy_off(front_door):
    front_door.policy(False, ["test", "test-fast"])
    result = front_door.recipe("test-one", "a b", "$x", "*")
    assert result.returncode == 0, result.stderr
    assert front_door.markers() == [["focused", "a b", "$x", "*"]]
    assert front_door.pairs() == [("test-one", "ran")]


def test_a_hosted_nested_suite_without_force_fails_loudly(front_door):
    front_door.policy(False, ["test", "test-fast"])
    result = front_door.recipe("hook-pre-push-fast", GITHUB_ACTIONS="true")
    assert result.returncode == 2, result.stderr
    assert "TT_FORCE=1" in result.stderr
    assert front_door.markers() == [["hygiene"]]
    assert not any(r["execution"] == "skipped" for r in front_door.rows())


def test_a_hosted_forced_nested_suite_runs(front_door):
    front_door.policy(False, ["test", "test-fast"])
    result = front_door.recipe("hook-pre-push-fast", GITHUB_ACTIONS="true", TT_FORCE="1")
    assert result.returncode == 0, result.stderr
    assert front_door.markers() == [["hygiene"], ["fast"]]


def test_uncovered_push_warns_without_running_the_suite(front_door):
    front_door.policy(False, ["test", "test-fast"])
    result = front_door.push("backup", refs("refs/heads/x"))
    assert result.returncode == 0, result.stderr
    assert "remote full-suite coverage" in result.stderr
    assert front_door.markers() == [["hygiene"]]
