"""Live actor cgroup creation, verification, killing and removal under a delegated user unit."""
import secrets
import subprocess
import sys
import textwrap

import pytest

from user_manager import in_delegated_unit, stop_unit, unit_env, user_manager  # noqa: F401

pytestmark = pytest.mark.user_manager


def test_actor_cgroup_lifecycle_in_delegated_unit(user_manager, tmp_path):
    unit = f"autonomy-cgroup-{secrets.token_hex(8)}.service"
    script = textwrap.dedent(
        r"""
        import os, subprocess, sys, time
        import pytest
        from autonomy.delegation import actor_cgroup, check_unit, current_host, identify

        unit = sys.argv[1]
        host = current_host()
        caller = identify(host, unit)
        check_unit(host, caller, peak=64 * (1 << 20), tasks=16)

        cg = actor_cgroup(host.cgroups, caller.cgroup, "a" * 32)
        assert cg.empty()
        assert cg.remove(wait=0.5) is True

        mem = 64 * (1 << 20)
        tasks = 16
        cg.create(memory_bytes=mem, tasks=tasks)
        assert cg.empty()

        with pytest.raises(ValueError):
            cg.check(os.getpid(), memory_bytes=mem, tasks=tasks)

        sleeper = subprocess.Popen(
            [
                "/usr/bin/python3",
                "-I",
                "-c",
                "import os, sys, time; open(sys.argv[1], 'w').write('0\\n'); print('joined', flush=True); time.sleep(60)",
                str(cg.path / "cgroup.procs"),
            ],
            env={"PATH": "/usr/bin", "LC_ALL": "C"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert sleeper.stdout.readline().strip() == "joined"
            assert not cg.empty()
            cg.check(sleeper.pid, memory_bytes=mem, tasks=tasks)
            with pytest.raises(ValueError):
                cg.check(sleeper.pid, memory_bytes=mem + 4096, tasks=tasks)
            with pytest.raises(ValueError):
                cg.check(sleeper.pid, memory_bytes=mem, tasks=tasks + 1)
            assert cg.remove(wait=5.0) is True
            sleeper.wait(timeout=5.0)
            assert not cg.path.exists()
            assert cg.empty()
        finally:
            if sleeper.poll() is None:
                sleeper.kill()
                sleeper.wait(timeout=5)
        """
    )
    try:
        result = subprocess.run(
            in_delegated_unit([sys.executable, "-c", script, unit], unit=unit),
            env=unit_env(tmp_path),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        stop_unit(unit, tmp_path)
    assert result.returncode == 0, result.stderr + result.stdout
