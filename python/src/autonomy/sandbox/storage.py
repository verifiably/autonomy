"""The bounded pool behind every directory an actor can write (docs/envelope.md).

A tmpfs `size` bounds file pages only: empty files and directories cost kernel memory
and no pages. bubblewrap sets no inode limit, so a trusted stage in front of it mounts
one tmpfs with both limits, in a user and mount namespace of its own, over the scratch
path. The sandbox binds its scratch, `/tmp` and `/dev/shm` from that one pool and
remounts `/` and `/dev` read-only, so the pool's limits are the actor's total. The host
never sees the mount, and it goes with the last process or descriptor holding it.

tmpfs charges a POSIX ACL (up to 64 KiB, two per directory, inherited by every new entry)
to neither limit and to no cgroup, and has no option against them. The same stage
installs a seccomp filter that refuses every way to set an extended attribute."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterable
from pathlib import Path

from autonomy.sandbox.spec import SandboxSpec, Storage
from autonomy.sandbox.static import SandboxUnproven

__all__ = ["hold_storage", "pool_binds", "pool_command"]

_SCRATCH, _TMP, _SHM = "scratch", "tmp", "shm"

_POOL = """
import ctypes, errno, os, struct, sys
scratch, size, inodes = sys.argv[1:4]
end = sys.argv.index("--")
directories, command = sys.argv[4:end], sys.argv[end + 1:]
uid, gid = os.getuid(), os.getgid()
os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNS)
for name, text in (("setgroups", "deny"), ("uid_map", f"{uid} {uid} 1"), ("gid_map", f"{gid} {gid} 1")):
    with open(f"/proc/self/{name}", "w") as stream:
        stream.write(text)
libc = ctypes.CDLL(None, use_errno=True)
def check(result, what):
    if result:
        raise OSError(ctypes.get_errno(), f"cannot {what}: {os.strerror(ctypes.get_errno())}")
class Program(ctypes.Structure):
    _fields_ = [("length", ctypes.c_ushort), ("code", ctypes.c_void_p)]
def install_filter():
    # AUDIT_ARCH, then setxattr, lsetxattr and fsetxattr in that machine's table.
    arch, xattr = {"x86_64": (0xC000003E, (188, 189, 190)), "aarch64": (0xC00000B7, (5, 6, 7))}[os.uname().machine]
    SETXATTRAT, IO_URING_SETUP, X32 = 463, 425, 0x40000000
    LOAD, EQUAL, AT_LEAST, RETURN, ERRNO, ALLOW = 0x20, 0x15, 0x35, 0x06, 0x00050000, 0x7FFF0000
    # Another call table would have other numbers: refuse it whole.
    rules = [(LOAD, 0, 0, 4), (EQUAL, 1, 0, arch), (RETURN, 0, 0, ERRNO | errno.ENOSYS),
             (LOAD, 0, 0, 0), (AT_LEAST, 0, 1, X32), (RETURN, 0, 0, ERRNO | errno.ENOSYS)]
    refused = [(number, errno.EOPNOTSUPP) for number in (*xattr, SETXATTRAT)]
    for number, code in (*refused, (IO_URING_SETUP, errno.EPERM)):
        rules += [(EQUAL, 0, 1, number), (RETURN, 0, 0, ERRNO | code)]
    rules.append((RETURN, 0, 0, ALLOW))
    code = ctypes.create_string_buffer(b"".join(struct.pack("HBBI", *rule) for rule in rules))
    program = Program(len(rules), ctypes.addressof(code))
    PR_SET_SECCOMP, PR_SET_NO_NEW_PRIVS, FILTER = 22, 38, 2
    check(libc.prctl(PR_SET_NO_NEW_PRIVS, *map(ctypes.c_ulong, (1, 0, 0, 0))), "set no_new_privs")
    check(libc.prctl(PR_SET_SECCOMP, ctypes.c_ulong(FILTER), ctypes.byref(program)), "install the attribute filter")
MS_NOSUID, MS_NODEV = 2, 4
options = f"size={size},nr_inodes={inodes},mode=0700".encode()
check(libc.mount(b"tmpfs", os.fsencode(scratch), b"tmpfs", MS_NOSUID | MS_NODEV, options), "mount the bounded pool")
for directory in directories:
    os.makedirs(os.path.join(scratch, directory), 0o700, exist_ok=True)
install_filter()
os.execvp(command[0], command)
"""
"""Run under `/usr/bin/python3 -I`, exec'd in place so the process bubblewrap dies with
stays the caller's own child. The mount reaches no other namespace: one owned by a new
user namespace receives the host's mounts as slaves (mount_namespaces(7))."""


def pool_command(scratch: Path, storage: Storage, directories: Iterable[Path] = ()) -> list[str]:
    """The argv to put in front of a command that must see the pool at `scratch`.
    `directories` are the paths under scratch the command needs at its start."""
    made = (str(Path(_SCRATCH) / path.relative_to(scratch)) for path in directories)
    return ["/usr/bin/python3", "-I", "-c", _POOL, str(scratch), str(storage.bytes), str(storage.inodes),
            _SCRATCH, _TMP, _SHM, *made, "--"]


def pool_binds(scratch: Path) -> tuple[tuple[str, str], ...]:
    """`(source, destination)` for each writable bind, the sources being in the pool."""
    return ((str(scratch / _TMP), "/tmp"), (str(scratch / _SHM), "/dev/shm"), (str(scratch / _SCRATCH), str(scratch)))


def _filters(pid: int | str) -> int:
    status = Path(f"/proc/{pid}/status").read_text()
    return int(next(line.split()[1] for line in status.splitlines() if line.startswith("Seccomp_filters:")))


def _check_mounts(init: int, root: str, pool: str) -> None:
    for line in Path(f"/proc/{init}/mountinfo").read_text().splitlines():
        mount, _, source = line.partition(" - ")
        _, _, device, _, point, options, *_ = mount.split(" ")
        if "rw" not in options.split(",") or device == pool or source.split(" ")[0] in ("proc", "devpts"):
            continue
        # bubblewrap binds the host's device nodes one by one.
        if point.startswith("/dev/") and stat.S_ISCHR(os.stat(root + point).st_mode):
            continue
        raise SandboxUnproven("storage-unproven", point, "the actor could write to a mount outside the bounded pool")


def hold_storage(init: int, spec: SandboxSpec) -> int:
    """Prove the bound on a namespace whose gate is still held, and return a descriptor
    on its scratch. The descriptor keeps the pool readable after the namespace ends; the
    caller closes it. The sandbox must be past its setup, which a pinned worker shows
    (`launch(track_worker=True)`)."""
    if spec.storage is None:
        raise SandboxUnproven("storage-unproven", str(spec.scratch), "the sandbox declares no storage bound")
    root = f"/proc/{init}/root"
    try:
        fd = os.open(f"{root}{spec.scratch}", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            usage = os.fstatvfs(fd)
            found = Storage(usage.f_blocks * usage.f_frsize, usage.f_files)
            if found != spec.storage:
                raise SandboxUnproven("storage-unproven", str(spec.scratch), f"scratch has {found}, not {spec.storage}")
            device = os.fstat(fd).st_dev
            _check_mounts(init, root, f"{os.major(device)}:{os.minor(device)}")
            if _filters(init) <= _filters("self"):
                raise SandboxUnproven("storage-unproven", str(spec.scratch), "the namespace lacks the attribute filter")
        except BaseException:
            os.close(fd)
            raise
    except (OSError, ValueError, StopIteration) as caught:
        raise SandboxUnproven("storage-unproven", str(spec.scratch), f"cannot read the actor's mounts: {caught}") from caught
    return fd
