"""Row E25: the model-free confined command launch check (envelope design decision 14,
autonomy-375479). Requires bubblewrap (`bwrap`) and unprivileged user namespaces, and
needs neither `pi` nor `node` so it runs both locally and in `.github/workflows/test.yml`."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import secrets
import shutil
import socket
import stat
from pathlib import Path

import pytest

from autonomy.analyst import CommandRequest, Progress, command_env, execute_command
from autonomy.sandbox.bwrap import launch, preflight
from autonomy.sandbox.spec import SandboxSpec

pytestmark = [pytest.mark.bwrap]


def sentinel() -> str:
    return secrets.token_hex(8)


@dataclasses.dataclass
class E25Fixture:
    root: Path
    suffix: str
    k: str
    s: str
    w: str
    a: str
    d: str
    m: str
    hashes: dict[str, str]

    @property
    def key(self) -> Path:
        return self.root / "key"

    @property
    def source(self) -> Path:
        return self.root / "source"

    @property
    def world(self) -> Path:
        return self.root / "world"

    @property
    def bundle(self) -> Path:
        return self.root / "bundle"

    @property
    def private_dir(self) -> Path:
        return self.root / "private"

    @property
    def code_dir(self) -> Path:
        return self.root / "code"

    @property
    def disjoint_file(self) -> Path:
        return self.private_dir / f"disjoint-{self.suffix}.json"

    @property
    def manifest_file(self) -> Path:
        return self.private_dir / f"manifest-{self.suffix}.json"

    @property
    def allowed_file(self) -> Path:
        return self.bundle / f"allowed-{self.suffix}.tsv"

    @property
    def entry_script(self) -> Path:
        return self.code_dir / "entry.py"

    def files(self) -> dict[str, Path]:
        return {
            "K": self.key / f"private-key-{self.suffix}.json",
            "S": self.source / f"series-{self.suffix}.txt",
            "W": self.world / f"world-{self.suffix}.toml",
            "A": self.allowed_file,
            "D": self.disjoint_file,
            "M": self.manifest_file,
        }

    def forbidden_sentinels(self) -> dict[str, str]:
        return {"K": self.k, "S": self.s, "W": self.w, "M": self.m}


ENTRY_SCRIPT_SOURCE = """\
import errno
import json
import os
import socket
import sys
from pathlib import Path

cfg = json.loads(Path(sys.argv[1]).read_text())

# 1. Read allowed directory input (A) and single-file input (D), and verify cwd == code_dir
assert Path.cwd() == Path(cfg["code_dir"]).resolve(), f"cwd {Path.cwd()} != {cfg['code_dir']}"
a_text = Path(cfg["allowed_file"]).read_text()
d_text = Path(cfg["disjoint_file"]).read_text()
assert cfg["sentinel_a"] in a_text
assert cfg["sentinel_d"] in d_text

# 2. Writes to declared inputs fail with EROFS; unlink on directory-bound files fails with EROFS
#    and unlink on a single-file bind mount point fails with EBUSY.
for ro_path in (cfg["allowed_file"], cfg["disjoint_file"], cfg["entry_script"]):
    try:
        with open(ro_path, "a") as handle:
            handle.write("mutated\\n")
    except OSError as caught:
        assert caught.errno == errno.EROFS, f"expected EROFS writing {ro_path}, got {caught.errno}"
    else:
        raise AssertionError(f"writing {ro_path} unexpectedly succeeded")

for dir_bound in (cfg["allowed_file"], cfg["entry_script"]):
    try:
        os.unlink(dir_bound)
    except OSError as caught:
        assert caught.errno == errno.EROFS, f"expected EROFS unlinking {dir_bound}, got {caught.errno}"
    else:
        raise AssertionError(f"unlinking {dir_bound} unexpectedly succeeded")

try:
    os.unlink(cfg["disjoint_file"])
except OSError as caught:
    assert caught.errno == errno.EBUSY, f"expected EBUSY unlinking single-file mount {cfg['disjoint_file']}, got {caught.errno}"
else:
    raise AssertionError("unlinking single-file mount unexpectedly succeeded")

# 3. Denied roots, sibling file in private/, <state>, <config>, --release, and /proc/1/root paths fail with ENOENT
for absent in cfg["absent_paths"]:
    for candidate in (absent, f"/proc/1/root{absent}"):
        try:
            os.lstat(candidate)
        except OSError as caught:
            assert caught.errno == errno.ENOENT, f"expected ENOENT on lstat({candidate}), got {caught.errno}"
        else:
            raise AssertionError(f"lstat({candidate}) unexpectedly succeeded")
        try:
            open(candidate, "rb").close()
        except OSError as caught:
            assert caught.errno == errno.ENOENT, f"expected ENOENT on open({candidate}), got {caught.errno}"
        else:
            raise AssertionError(f"open({candidate}) unexpectedly succeeded")

# 4. Outbound IPv4, IPv6, loopback (4780 + host listener), and host abstract AF_UNIX all fail
allowed_net_errnos = {errno.ENETUNREACH, errno.EAFNOSUPPORT, errno.ECONNREFUSED, errno.EADDRNOTAVAIL}
for host, port in [("192.0.2.1", 443), ("2001:db8::1", 443), ("127.0.0.1", 4780), ("127.0.0.1", cfg["host_port"])]:
    try:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect((host, port))
    except OSError as caught:
        assert caught.errno in allowed_net_errnos, f"unexpected errno {caught.errno} connecting to {host}:{port}"
    else:
        raise AssertionError(f"connect to {host}:{port} unexpectedly succeeded")

try:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as unix_sock:
        unix_sock.settimeout(2.0)
        unix_sock.connect("\\0" + cfg["abstract_name"])
except OSError as caught:
    assert caught.errno in {errno.ECONNREFUSED, errno.ENOENT}, f"unexpected errno {caught.errno} on abstract AF_UNIX"
else:
    raise AssertionError("abstract AF_UNIX connect unexpectedly succeeded")

# 5. Process tree and environment have no pi, node, proxy, or VERIFIABLY_MODEL_URL
assert "VERIFIABLY_MODEL_URL" not in os.environ
assert os.environ.get("LC_ALL") == "C.UTF-8"
assert os.environ.get("LANG") == "C.UTF-8"
assert os.environ.get("VERIFIABLY_SCRATCH") and Path(os.environ["VERIFIABLY_SCRATCH"]).is_dir()
assert os.environ.get("VERIFIABLY_OUTPUTS") == str(Path(os.environ["VERIFIABLY_SCRATCH"]) / "outputs")
for entry in Path("/proc").iterdir():
    if not entry.name.isdigit():
        continue
    try:
        cmdline = (entry / "cmdline").read_bytes().decode("utf-8", "replace")
    except OSError:
        continue
    for forbidden_proc in ("/pi", "node", "egress"):
        assert forbidden_proc not in cmdline, f"unexpected process {cmdline!r} in sandbox /proc"

# 6. Write outputs via both /run/va/outputs and $VERIFIABLY_OUTPUTS
Path("/run/va/outputs/result.txt").write_text("released-from-fixed-path\\n")
nested = Path(os.environ["VERIFIABLY_OUTPUTS"]) / "sub/nested.txt"
nested.parent.mkdir(parents=True, exist_ok=True)
nested.write_text("released-from-env-path\\n")

print("ok")
print("diagnostic-stderr-line", file=sys.stderr)
"""


def make_e25_fixture(parent: Path, *, state_dir: Path, config_dir: Path, release_dir: Path, host_port: int, abstract_name: str) -> E25Fixture:
    f = E25Fixture(
        root=parent,
        suffix=secrets.token_hex(4),
        k=sentinel(),
        s=sentinel(),
        w=sentinel(),
        a=sentinel(),
        d=sentinel(),
        m=sentinel(),
        hashes={},
    )
    contents = {
        "K": json.dumps({"private_key": f.k}) + "\n",
        "S": f"t\tvalue\n1\t{f.s}\n",
        "W": f'name = "{f.w}"\n',
        "A": f"t\tvalue\n1\t{f.a}\n",
        "D": json.dumps({"disjoint_cohort": f.d}) + "\n",
        "M": json.dumps({"manifest_secret": f.m}) + "\n",
    }
    for letter, path in f.files().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents[letter])
    f.code_dir.mkdir(parents=True, exist_ok=True)
    f.entry_script.write_text(ENTRY_SCRIPT_SOURCE)
    cfg_path = f.code_dir / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "code_dir": str(f.code_dir.resolve()),
                "allowed_file": str(f.allowed_file.resolve()),
                "disjoint_file": str(f.disjoint_file.resolve()),
                "entry_script": str(f.entry_script.resolve()),
                "sentinel_a": f.a,
                "sentinel_d": f.d,
                "host_port": host_port,
                "abstract_name": abstract_name,
                "absent_paths": [
                    str(f.files()["K"].resolve()),
                    str(f.files()["S"].resolve()),
                    str(f.files()["W"].resolve()),
                    str(f.manifest_file.resolve()),
                    str(state_dir.resolve(strict=False)),
                    str(config_dir.resolve(strict=False)),
                    str(release_dir.resolve(strict=False)),
                ],
            }
        )
        + "\n"
    )
    for path in [*f.files().values(), f.entry_script, cfg_path]:
        f.hashes[str(path.relative_to(parent))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return f


def _regular_files(root: Path):
    stack = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)]
    paths = [Path(root)]
    while stack:
        fd, base = stack.pop(), paths.pop()
        try:
            with os.scandir(fd) as entries:
                names = [e.name for e in entries]
            for name in names:
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISDIR(info.st_mode):
                    stack.append(os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd))
                    paths.append(base / name)
                elif stat.S_ISREG(info.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
                    try:
                        with open(child, "rb", closefd=False) as handle:
                            yield base / name, handle.read()
                    finally:
                        os.close(child)
        finally:
            os.close(fd)


def test_e25_confined_command_denies_private_paths_and_network_and_releases_outputs(tmp_path):
    for name in ("home", "release", "config/verifiably-autonomy"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "PATH": "/usr/bin",
    }
    state_dir = tmp_path / "state/verifiably-autonomy"
    config_dir = tmp_path / "config/verifiably-autonomy"
    release_dir = tmp_path / "release"

    tcp_listener = socket.create_server(("127.0.0.1", 0))
    host_port = tcp_listener.getsockname()[1]
    abstract_name = f"autonomy-e25-{secrets.token_hex(6)}"
    unix_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    unix_listener.bind("\0" + abstract_name)
    unix_listener.listen(1)

    report_r, report_w = os.pipe()
    try:
        f = make_e25_fixture(
            tmp_path / "fixture",
            state_dir=state_dir,
            config_dir=config_dir,
            release_dir=release_dir,
            host_port=host_port,
            abstract_name=abstract_name,
        )
        request = CommandRequest(
            inputs=(f.bundle, f.disjoint_file, f.code_dir),
            denied=(f.key, f.source, f.world),
            release_dir=release_dir,
            argv=("/usr/bin/python3", "-I", str(f.entry_script), str(f.code_dir / "config.json")),
            workdir=f.code_dir,
            report_fd=report_w,
        )
        progress = Progress()
        diags: list[str] = []
        code = execute_command(request, env, diag=diags.append, progress=progress)
        assert code == 0, (progress.run_dir / "stderr.log").read_text() if progress.run_dir else diags

        raw_report = b""
        while chunk := os.read(report_r, 65536):
            raw_report += chunk
        report_lines = [json.loads(line) for line in raw_report.decode().splitlines()]
        assert len(report_lines) == 2
        assert report_lines[0]["run_dir"] == str(progress.run_dir)
        assert report_lines[1] == {
            "run": progress.run_dir.name,
            "exit": 0,
            "command_exit": 0,
            "released": 2,
            "refused": 0,
        }

        run_dir = progress.run_dir
        assert (release_dir / "result.txt").read_text() == "released-from-fixed-path\n"
        assert (release_dir / "sub/nested.txt").read_text() == "released-from-env-path\n"
        release_doc = json.loads((run_dir / "release.json").read_text())
        released_by_path = {entry["path"]: entry["sha256"] for entry in release_doc["released"]}
        assert released_by_path == {
            "result.txt": hashlib.sha256(b"released-from-fixed-path\n").hexdigest(),
            "sub/nested.txt": hashlib.sha256(b"released-from-env-path\n").hexdigest(),
        }

        assert (run_dir / "stdout.log").read_bytes() == b"ok\n"
        assert (run_dir / "stderr.log").read_bytes() == b"diagnostic-stderr-line\n"
        for required in ("epoch.json", "walk.json", "release.json", "events.jsonl", "stdout.log", "stderr.log", "launcher.log"):
            assert (run_dir / required).is_file(), required
        assert not (run_dir / "egress.jsonl").exists()
        assert not (run_dir / "proxy.log").exists()

        # Verify all host fixture files are byte-for-byte unchanged and no new files appeared in f.root
        for relative, digest in f.hashes.items():
            path = f.root / relative
            assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest, relative
        for path, _ in _regular_files(f.root):
            assert str(path.relative_to(f.root)) in f.hashes

        # Verify forbidden sentinels (K, S, W, M) never appear in stdout, stderr, release, run_dir, or scratch
        for tree in (release_dir, run_dir, progress.scratch):
            for path, data in _regular_files(tree):
                for letter, value in f.forbidden_sentinels().items():
                    assert value.encode() not in data, f"sentinel {letter} leaked into {path}"
    finally:
        os.close(report_r)
        tcp_listener.close()
        unix_listener.close()


def test_e25_changing_file_or_directory_input_bytes_changes_recorded_digest(tmp_path):
    for name in ("home", "r1", "r2", "r3", "bundle", "private", "code", "key"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "PATH": "/usr/bin",
    }
    (tmp_path / "key/secret").write_text("k")
    (tmp_path / "bundle/data.tsv").write_text("x\t1\n")
    disjoint = tmp_path / "private/disjoint.json"
    disjoint.write_text('{"v": 1}\n')
    entry = tmp_path / "code/entry.py"
    entry.write_text("print('v1')\n")

    def run_once(rel: Path) -> tuple[dict, dict]:
        req = CommandRequest(
            inputs=(tmp_path / "bundle", disjoint, tmp_path / "code"),
            denied=(tmp_path / "key",),
            release_dir=rel,
            argv=("/usr/bin/python3", "-I", str(entry)),
            workdir=tmp_path / "code",
        )
        prog = Progress()
        assert execute_command(req, env, diag=lambda _: None, progress=prog) == 0
        return (
            json.loads((prog.run_dir / "epoch.json").read_text()),
            json.loads((prog.run_dir / "walk.json").read_text()),
        )

    epoch1, walk1 = run_once(tmp_path / "r1")
    assert epoch1["inputs"] == walk1["inputs"]
    by_path1 = {item["path"]: item["sha256"] for item in epoch1["inputs"]}

    # Mutate single-file input bytes -> file input sha256 changes while argv_sha256 and executable.sha256 stay identical
    disjoint.write_text('{"v": 2}\n')
    epoch2, walk2 = run_once(tmp_path / "r2")
    assert epoch2["inputs"] == walk2["inputs"]
    by_path2 = {item["path"]: item["sha256"] for item in epoch2["inputs"]}
    assert by_path2[str(disjoint.resolve())] != by_path1[str(disjoint.resolve())]
    assert by_path2[str((tmp_path / "code").resolve())] == by_path1[str((tmp_path / "code").resolve())]
    assert epoch2["argv_sha256"] == epoch1["argv_sha256"]
    assert epoch2["executable"]["sha256"] == epoch1["executable"]["sha256"]

    # Mutate script inside code/ directory input -> directory input sha256 changes
    entry.write_text("print('v2')\n")
    epoch3, walk3 = run_once(tmp_path / "r3")
    assert epoch3["inputs"] == walk3["inputs"]
    by_path3 = {item["path"]: item["sha256"] for item in epoch3["inputs"]}
    assert by_path3[str((tmp_path / "code").resolve())] != by_path2[str((tmp_path / "code").resolve())]


def test_e25_virtualenv_with_recreated_directory_symlink_preserves_sys_prefix(tmp_path):
    for name in ("home", "release", "code", "scratch_neg/home", "scratch_neg/outputs"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "PATH": "/usr/bin",
    }
    real_py = tmp_path / "uv/cpython-3.13.12"
    (real_py / "bin").mkdir(parents=True)
    py_bin = real_py / "bin/python3"
    shutil.copy2("/usr/bin/python3", py_bin)
    py_bin.chmod(0o755)
    # Create standard library symlink to /usr/lib so copied binary finds encodings under -E -s
    for lib_name in ("lib", "lib64"):
        if Path(f"/usr/{lib_name}").is_dir():
            (real_py / lib_name).symlink_to(f"/usr/{lib_name}")

    link_py = tmp_path / "uv/cpython-3.13"
    link_py.symlink_to(real_py)

    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin/python").symlink_to(link_py / "bin/python3")
    (venv / "pyvenv.cfg").write_text(f"home = {link_py / 'bin'}\ninclude-system-site-packages = false\n")

    script = tmp_path / "code/check_venv.py"
    script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "Path('/run/va/outputs/venv.txt').write_text(sys.prefix + '\\n')\n"
    )
    request = CommandRequest(
        inputs=(venv, real_py, tmp_path / "code"),
        denied=(),
        release_dir=tmp_path / "release",
        argv=(str(venv / "bin/python"), "-E", "-s", str(script)),
        workdir=tmp_path / "code",
    )
    progress = Progress()
    code = execute_command(request, env, diag=lambda _: None, progress=progress)
    assert code == 0, (progress.run_dir / "stderr.log").read_text()
    assert (tmp_path / "release/venv.txt").read_text().strip() == str(venv.resolve())

    # Negative control: launching without the recreated symlink in SandboxSpec fails to exec venv/bin/python
    preflight()
    neg_scratch = (tmp_path / "scratch_neg").resolve()
    spec_without_symlink = SandboxSpec(
        scratch=neg_scratch,
        ro_binds=(venv.resolve(), real_py.resolve(), (tmp_path / "code").resolve()),
        symlinks=(),
        chdir=(tmp_path / "code").resolve(),
        outputs_link=True,
        env=command_env(neg_scratch),
    )
    null_fd = os.open(os.devnull, os.O_RDONLY | os.O_CLOEXEC)
    err_r, err_w = os.pipe()
    try:
        actor = launch(spec_without_symlink, [str(venv.resolve() / "bin/python"), "-E", "-s", str(script)], stdin=null_fd, stdout=err_w, stderr=err_w)
        try:
            status = actor.wait(timeout=10.0)
        finally:
            actor.close()
        assert status != 0
    finally:
        os.close(null_fd)
        os.close(err_w)
        os.close(err_r)


def test_e25_negative_controls_detect_exposed_sibling_or_parent(tmp_path):
    for name in ("home", "r_sibling", "r_parent", "private", "key", "code"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "PATH": "/usr/bin",
    }
    disjoint = tmp_path / "private/disjoint.json"
    disjoint.write_text('{"d": 1}\n')
    manifest = tmp_path / "private/manifest.json"
    manifest.write_text("SENTINEL_M\n")
    secret_k = tmp_path / "key/secret.json"
    secret_k.write_text("SENTINEL_K\n")

    probe_script = tmp_path / "code/probe.py"
    probe_script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "p = Path(sys.argv[1])\n"
        "sys.exit(0 if p.exists() and sys.argv[2] in p.read_text() else 1)\n"
    )

    # 1. Binding private/ directory instead of single file disjoint.json exposes sibling manifest.json (exit 0 instead of ENOENT)
    req_sibling = CommandRequest(
        inputs=(tmp_path / "private", tmp_path / "code"),
        denied=(tmp_path / "key",),
        release_dir=tmp_path / "r_sibling",
        argv=("/usr/bin/python3", "-I", str(probe_script), str(manifest.resolve()), "SENTINEL_M"),
    )
    assert execute_command(req_sibling, env, diag=lambda _: None, progress=Progress()) == 0

    # 2. Binding parent directory with denied=() exposes key/secret.json
    fixture_root = tmp_path / "fixture_parent"
    (fixture_root / "key").mkdir(parents=True)
    k_path = fixture_root / "key/secret.json"
    k_path.write_text("SENTINEL_K\n")
    req_parent = CommandRequest(
        inputs=(fixture_root, tmp_path / "code"),
        denied=(),
        release_dir=tmp_path / "r_parent",
        argv=("/usr/bin/python3", "-I", str(probe_script), str(k_path.resolve()), "SENTINEL_K"),
    )
    assert execute_command(req_parent, env, diag=lambda _: None, progress=Progress()) == 0
