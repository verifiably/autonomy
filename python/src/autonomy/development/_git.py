"""Fixed Git operations in confined, resource-bounded helper processes."""

from __future__ import annotations

import json
import os
import re
import resource
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path("/work")
_HOME = _ROOT / "home"
_SOURCE = Path("/source-objects")
_EXPORT = Path("/export")


class GitFailed(Exception):
    """The isolated Git operation could not produce its promised result."""

    def __init__(self, detail: str, *, input_invalid: bool = False) -> None:
        super().__init__(detail)
        self.input_invalid = input_invalid


class SourceViewInvalid(GitFailed):
    """The mounted object view could not be matched to the held source."""


@dataclass(frozen=True)
class PinnedObjectDirectory:
    fd: int
    destination: str
    device: int
    inode: int


def git_environment(home: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/bin", "HOME": str(home), "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_ATTR_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0",
        "TMPDIR": str(home.parent / "tmp"),
    }


def run_worker(
    action: str, operands: tuple[str, ...], *, until: float, memory_bytes: int, storage_bytes: int,
    read_only: tuple[tuple[Path, str], ...] = (), export: Path | None = None,
    source_mounts: tuple[PinnedObjectDirectory, ...] = (),
) -> str:
    # Import only in the host orchestrator. The worker itself is an isolated
    # standard-library script and sees no checkout or Python package tree.
    from autonomy.sandbox.spec import SYSTEM_RO
    from autonomy.sandbox.static import system_symlinks

    argv = [
        "bwrap", "--unshare-all", "--unshare-user", "--disable-userns",
        "--die-with-parent", "--new-session", "--clearenv", "--dev", "/dev",
        "--size", str(storage_bytes), "--tmpfs", str(_ROOT), "--chdir", str(_ROOT),
    ]
    for path in SYSTEM_RO:
        argv.extend(("--ro-bind", str(path), str(path)))
    for target, link in system_symlinks():
        argv.extend(("--symlink", target, link))
    for path, destination in read_only:
        argv.extend(("--ro-bind", str(path), destination))
    for mount in source_mounts:
        argv.extend(("--ro-bind", f"/proc/self/fd/{mount.fd}", mount.destination))
    if export is not None:
        argv.extend(("--bind", str(export), str(_EXPORT)))
    witnesses = json.dumps([(mount.destination, mount.device, mount.inode) for mount in source_mounts])
    argv.extend((
        "--ro-bind", str(Path(__file__).resolve()), "/git-worker.py", "--remount-ro", "/",
        "--", "/usr/bin/python3", "-I", "/git-worker.py", str(memory_bytes), action, witnesses, *operands,
    ))
    remaining = until - time.monotonic()
    if remaining <= 0:
        raise GitFailed("Git helper deadline expired")
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, errors="replace", timeout=remaining,
            stdin=subprocess.DEVNULL, env={"PATH": "/usr/bin", "LC_ALL": "C"},
            pass_fds=tuple(mount.fd for mount in source_mounts),
        )
    except (OSError, subprocess.TimeoutExpired) as caught:
        raise GitFailed(f"isolated Git helper could not run: {caught}") from caught
    if result.returncode:
        detail = result.stderr.strip() or f"Git helper exited {result.returncode}"
        if result.returncode == 3:
            raise SourceViewInvalid(detail)
        raise GitFailed(detail, input_invalid=result.returncode == 2)
    return result.stdout.strip()


def _git(cwd: Path, *args: str, objects: Path | None = None) -> str:
    env = git_environment(_HOME)
    if objects is not None:
        env["GIT_OBJECT_DIRECTORY"] = str(objects)
    result = subprocess.run(
        ["/usr/bin/git", "-c", "protocol.allow=never", "-c", "protocol.file.allow=always",
         "-c", "pack.threads=1", "-C", str(cwd), *args],
        capture_output=True, text=True, errors="replace", env=env, stdin=subprocess.DEVNULL,
    )
    if result.returncode:
        raise GitFailed(f"git {args[0]}: {result.stderr.strip()[:3000] or result.returncode}")
    return result.stdout.strip()


def _init(path: Path, object_format: str, *, bare: bool) -> None:
    path.mkdir()
    _git(path, "init", "--template=", f"--object-format={object_format}", *(("--bare",) if bare else ()))


def _base_reader(object_format: str, base: str) -> Path:
    reader = _ROOT / "reader"
    _init(reader, object_format, bare=True)
    try:
        kind = _git(reader, "cat-file", "-t", base, objects=_SOURCE)
    except GitFailed as caught:
        raise GitFailed(f"base {base} is unavailable in the local object store", input_invalid=True) from caught
    if kind != "commit":
        raise GitFailed(f"base {base} is not a commit", input_invalid=True)
    return reader


def _fetch(repo: Path, bundle: Path, ref: str) -> None:
    _git(repo, "bundle", "verify", str(bundle))
    _git(repo, "-c", "fetch.fsckObjects=true", "fetch", "--no-auto-maintenance", "--no-tags",
         "--no-recurse-submodules", "--no-write-fetch-head", str(bundle), f"{ref}:{ref}")
    _git(repo, "fsck", "--strict", "--full")


def _prepare(object_format: str, base: str, base_bytes: str, base_ref: str, actor_ref: str) -> None:
    reader = _base_reader(object_format, base)
    bundle = _ROOT / "base.bundle"
    _git(reader, "update-ref", base_ref, base, objects=_SOURCE)
    _git(reader, "bundle", "create", str(bundle), base_ref, objects=_SOURCE)
    if bundle.stat().st_size > int(base_bytes):
        raise GitFailed("base bundle exceeds the recorded byte limit")
    receiver = _ROOT / "receiver"
    _init(receiver, object_format, bare=True)
    _fetch(receiver, bundle, base_ref)
    listed = _git(receiver, "bundle", "list-heads", str(bundle))
    if listed != f"{base} {base_ref}":
        raise GitFailed("base bundle advertised a different base")
    repo = _ROOT / "repo"
    _init(repo, object_format, bare=False)
    shutil.rmtree(repo / ".git/objects")
    (receiver / "objects").rename(repo / ".git/objects")
    _git(repo, "symbolic-ref", "HEAD", actor_ref)
    _git(repo, "reset", "--hard", base)
    shutil.copytree(repo, _EXPORT / "repo", symlinks=True)
    shutil.copyfile(bundle, _EXPORT / "base.bundle")



def _candidate_header(bundle: Path, object_format: str, base: str, ref: str) -> str:
    def invalid(detail: str) -> GitFailed:
        return GitFailed(detail, input_invalid=True)

    hexadecimal = re.compile(rb"[0-9a-f]{" + str(len(base)).encode() + rb"}")
    with bundle.open("rb") as stream:
        version = stream.readline(128)
        if version not in (b"# v2 git bundle\n", b"# v3 git bundle\n"):
            raise invalid("unsupported bundle header")
        format_line = None
        prerequisite = None
        tip = None
        for line in stream:
            if line == b"\n":
                break
            if not line.endswith(b"\n"):
                raise invalid("incomplete bundle header")
            entry = line[:-1]
            if entry.startswith(b"@"):
                if (version != b"# v3 git bundle\n" or prerequisite is not None or tip is not None
                        or format_line is not None or entry != b"@object-format=" + object_format.encode()):
                    raise invalid("unsupported or repeated bundle capability")
                format_line = entry
                continue
            oid, space, value = entry.partition(b" ")
            if not space:
                raise invalid("bundle header entry lacks its delimiter")
            if oid.startswith(b"-"):
                if prerequisite is not None or tip is not None or oid[1:] != base.encode():
                    raise invalid("bundle must have exactly the pinned base as prerequisite")
                prerequisite = oid
            else:
                if tip is not None or value != ref.encode() or not hexadecimal.fullmatch(oid):
                    raise invalid("bundle must advertise exactly the declared branch")
                tip = oid
        else:
            raise invalid("bundle header terminator is missing")
        if prerequisite is None or tip is None or (object_format != "sha1" and format_line is None):
            raise invalid("bundle header lacks its base, branch or object format")
        return tip.decode()


def _validate(object_format: str, base: str, base_ref: str, actor_ref: str) -> str:
    bundle = Path("/candidate.bundle")
    tip = _candidate_header(bundle, object_format, base, actor_ref)
    receiver = _ROOT / "receiver"
    _init(receiver, object_format, bare=True)
    _fetch(receiver, Path("/base.bundle"), base_ref)
    if _git(receiver, "rev-parse", base_ref) != base:
        raise GitFailed("receiver base differs from the approved commit")
    _fetch(receiver, bundle, actor_ref)
    if _git(receiver, "rev-parse", actor_ref) != tip or tip == base:
        raise GitFailed("imported tip does not extend the approved base")
    _git(receiver, "merge-base", "--is-ancestor", base, tip)
    return tip


def _check_source_view(mounts: str) -> None:
    for path, device, inode in json.loads(mounts):
        try:
            info = os.stat(path, follow_symlinks=False)
            if (info.st_dev, info.st_ino) != (device, inode):
                raise SourceViewInvalid("source object directory changed before the helper opened it")
            with os.scandir(path) as entries:
                for entry in entries:
                    if not entry.is_file(follow_symlinks=False) or entry.name.endswith(".promisor"):
                        raise SourceViewInvalid("source object storage contains an unsupported entry")
        except OSError as caught:
            raise SourceViewInvalid(f"cannot inspect the mounted source object directory: {caught}") from caught


def _main(memory: str, action: str, mounts: str, operands: list[str]) -> None:
    resource.setrlimit(resource.RLIMIT_AS, (int(memory), int(memory)))
    _HOME.mkdir(mode=0o700)
    (_ROOT / "tmp").mkdir(mode=0o700)
    if action in ("admit", "prepare"):
        _check_source_view(mounts)
    if action == "admit":
        _base_reader(*operands)
    elif action == "prepare":
        _prepare(*operands)
    elif action == "validate":
        print(_validate(*operands))
    else:
        raise ValueError(f"unknown Git helper operation: {action}")


if __name__ == "__main__":
    try:
        _main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
    except SourceViewInvalid as error:
        print(str(error), file=sys.stderr)
        sys.exit(3)
    except GitFailed as error:
        print(str(error), file=sys.stderr)
        sys.exit(2 if error.input_invalid else 1)
    except (OSError, ValueError) as error:
        print(f"Git helper: {error}", file=sys.stderr)
        sys.exit(1)
