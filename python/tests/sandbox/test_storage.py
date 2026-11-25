import os
import subprocess
from contextlib import closing
from dataclasses import replace

import pytest

from autonomy.sandbox.bwrap import build_argv, launch, prove_development_host
from autonomy.sandbox.spec import SandboxSpec, Storage
from autonomy.sandbox.static import SandboxUnproven
from autonomy.sandbox.storage import hold_storage

pytestmark = pytest.mark.bwrap
PAGE = os.sysconf("SC_PAGE_SIZE")
BOUND = Storage(256 * PAGE, 64)
_FILL = """
import errno, os, sys
def fill(path):
    fd = os.open(path, os.O_CREAT | os.O_WRONLY)
    total = 0
    try:
        while True:
            total += os.write(fd, bytes(4096))
    except OSError as error:
        return total, errno.errorcode[error.errno]
    finally:
        os.close(fd)
def spawn(directory):
    made = 0
    try:
        while True:
            os.close(os.open(f"{directory}/n{made}", os.O_CREAT | os.O_WRONLY))
            made += 1
    except OSError as error:
        return made, errno.errorcode[error.errno]
"""


@pytest.fixture
def spec(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return SandboxSpec(scratch=scratch, storage=BOUND, disable_nested_userns=True)


@pytest.fixture
def stdio():
    fd = os.open(os.devnull, os.O_RDWR | os.O_CLOEXEC)
    try:
        yield {"stdin": fd, "stdout": fd, "stderr": fd}
    finally:
        os.close(fd)


def inside(spec, script, *args):
    result = subprocess.run(
        build_argv(spec, ["/usr/bin/python3", "-I", "-c", _FILL + script, *map(str, args)], info_fd=None),
        env={"PATH": "/usr/bin", "HOME": str(spec.scratch)}, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.split()


@pytest.mark.parametrize("where", ["scratch", "/tmp", "/dev/shm"])
def test_filling_a_writable_mount_is_refused_at_the_bound(spec, where):
    directory = spec.scratch if where == "scratch" else where
    total, code = inside(spec, "print(*fill(sys.argv[1] + '/x'))", directory)
    assert code == "ENOSPC" and 0 < int(total) <= BOUND.bytes
    assert list(spec.scratch.iterdir()) == []


def test_the_writable_mounts_share_one_total(spec):
    first, _, second, code, third, last = inside(
        spec, "print(*fill(sys.argv[1] + '/x'), *fill('/tmp/x'), *fill('/dev/shm/x'))", spec.scratch)
    assert int(first) > 0 and (second, code, third, last) == ("0", "ENOSPC", "0", "ENOSPC")


def test_empty_files_are_refused_at_the_inode_bound(spec):
    made, code, more, again = inside(spec, "print(*spawn(sys.argv[1]), *spawn('/dev/shm'))", spec.scratch)
    assert code == again == "ENOSPC" and 0 < int(made) < BOUND.inodes and more == "0"


@pytest.mark.parametrize("where", ["/", "/dev", "/run", "/run/va"])
def test_every_other_directory_is_read_only(spec, where):
    script = """
try:
    os.mkdir(sys.argv[1] + '/made')
except OSError as error:
    print(errno.errorcode[error.errno])
"""
    assert inside(replace(spec, outputs_link=True), script, where) == ["EROFS"]


def test_device_nodes_and_terminals_still_work(spec):
    assert inside(spec, """
import pty
with open('/dev/null', 'w') as sink:
    sink.write('x')
os.close(os.open('/dev/urandom', os.O_RDONLY))
[os.close(fd) for fd in pty.openpty()]
print('usable')
""") == ["usable"]


def test_the_actor_cannot_change_its_mounts(spec):
    script = """
import ctypes
libc = ctypes.CDLL(None, use_errno=True)
def refused(result):
    return 'done' if result == 0 else errno.errorcode[ctypes.get_errno()]
print(refused(libc.mount(None, b'/tmp', None, 32, b'size=1g,nr_inodes=1000000')))
print(refused(libc.mount(None, b'/', None, 32 | 4096, None)))
print(refused(libc.mount(b'tmpfs', b'/tmp', b'tmpfs', 0, None)))
print(refused(libc.umount2(sys.argv[1].encode(), 2)))
try:
    os.unshare(os.CLONE_NEWUSER)
except OSError as error:
    print(errno.errorcode[error.errno])
"""
    *mounts, namespace = inside(spec, script, spec.scratch)
    assert mounts == ["EPERM"] * 4 and namespace in ("EPERM", "ENOSPC")


def test_held_scratch_outlives_the_namespace(spec, stdio):
    held = []
    script = "from pathlib import Path; import os; print(Path('seed').read_text()); Path('kept').write_text('work')"

    def hold(child_pid, pidfd):
        held.append(hold_storage(child_pid, spec))
        seed = os.open("seed", os.O_CREAT | os.O_WRONLY, 0o600, dir_fd=held[0])
        os.write(seed, b"seeded")
        os.close(seed)

    sandboxed = launch(spec, ["/usr/bin/python3", "-I", "-c", script], before_release=hold, track_worker=True, **stdio)
    with closing(sandboxed):
        assert sandboxed.wait(timeout=15) == 0
    try:
        usage = os.fstatvfs(held[0])
        assert (usage.f_blocks * usage.f_frsize, usage.f_files) == (BOUND.bytes, BOUND.inodes)
        fd = os.open("kept", os.O_RDONLY, dir_fd=held[0])
        assert os.read(fd, 16) == b"work"
        os.close(fd)
    finally:
        os.close(held[0])
    assert list(spec.scratch.iterdir()) == []


@pytest.mark.parametrize("flaw", ["size", "inodes", "writable-root", "unbounded-mount"])
def test_an_unproven_bound_is_refused_before_release(spec, stdio, monkeypatch, flaw):
    from autonomy.sandbox import bwrap
    real = bwrap.build_argv

    def weaken(*args, **kwargs):
        argv = real(*args, **kwargs)
        if flaw == "writable-root":
            at = max(i for i, arg in enumerate(argv) if arg == "--remount-ro")
            assert argv[at + 1] == "/"
            del argv[at:at + 2]
        elif flaw == "unbounded-mount":
            at = argv.index("--remount-ro")
            argv[at:at] = ["--tmpfs", "/run"]
        return argv

    monkeypatch.setattr(bwrap, "build_argv", weaken)
    demanded = spec
    if flaw in ("size", "inodes"):
        demanded = replace(spec, storage=replace(BOUND, **{"bytes" if flaw == "size" else "inodes": 128 * PAGE}))
    with pytest.raises(SandboxUnproven) as caught:
        launch(spec, ["/usr/bin/touch", "ran"], track_worker=True,
               before_release=lambda child, pidfd: os.close(hold_storage(child, demanded)), **stdio)
    assert caught.value.code == "storage-unproven"


def test_host_proof_requires_a_bounded_mount(monkeypatch):
    from autonomy.sandbox import storage
    prove_development_host()
    monkeypatch.setattr(storage, "_POOL", "raise SystemExit('fixture mount refusal')")
    with pytest.raises(SandboxUnproven, match="userns-unavailable.*fixture mount refusal"):
        prove_development_host()
