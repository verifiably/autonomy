import hashlib
import os
import socket
import stat
import time

import pytest

from autonomy.analyst.release import check_release_dir, release
from autonomy.analyst.toolchain import AnalystRefused


def outputs_with(tmp_path, plant):
    out = tmp_path / "scratch/outputs"
    out.mkdir(parents=True)
    (out / "result.txt").write_text("result\n")
    (out / "figs").mkdir()
    (out / "figs/a.svg").write_text("<svg/>")
    plant(out)
    dest = tmp_path / "release"
    dest.mkdir()
    return out, dest


def test_regular_files_and_directories_are_released_with_hashes(tmp_path):
    out, dest = outputs_with(tmp_path, lambda o: None)
    report = release(out, dest)
    assert sorted(e["path"] for e in report.released) == ["figs/a.svg", "result.txt"]
    assert (dest / "figs/a.svg").read_text() == "<svg/>" and stat.S_IMODE((dest / "figs").stat().st_mode) == 0o700
    entry = next(e for e in report.released if e["path"] == "result.txt")
    assert entry["sha256"] == hashlib.sha256(b"result\n").hexdigest() and entry["size"] == 7
    assert report.refused == []


def test_a_symlink_to_a_host_file_is_refused_and_not_copied(tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("K")
    out, dest = outputs_with(tmp_path, lambda o: (o / "link").symlink_to(secret))
    report = release(out, dest)
    assert {"path": "link", "reason": "symlink"} in report.refused and not (dest / "link").exists()
    assert not any("K" in p.read_text() for p in dest.rglob("*") if p.is_file())


def test_a_fifo_does_not_stall_and_is_refused(tmp_path):
    out, dest = outputs_with(tmp_path, lambda o: os.mkfifo(o / "pipe"))
    start = time.monotonic()
    report = release(out, dest)
    assert time.monotonic() - start < 5 and {"path": "pipe", "reason": "fifo"} in report.refused


def test_a_hard_linked_file_and_a_socket_are_refused(tmp_path):
    def plant(o):
        os.link(o / "result.txt", o / "twin")
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(o / "sock"))
        s.close()

    out, dest = outputs_with(tmp_path, plant)
    report = release(out, dest)
    reasons = {e["path"]: e["reason"] for e in report.refused}
    assert reasons == {"twin": "hardlinked", "result.txt": "hardlinked", "sock": "socket"}


def test_a_release_never_overwrites(tmp_path):  # Review Focus 3
    out, dest = outputs_with(tmp_path, lambda o: None)
    (dest / "result.txt").write_text("already here")
    report = release(out, dest)
    assert {"path": "result.txt", "reason": "collision"} in report.refused
    assert (dest / "result.txt").read_text() == "already here"


def test_the_report_is_json(tmp_path):
    out, dest = outputs_with(tmp_path, lambda o: None)
    data = release(out, dest).to_json()
    assert set(data) == {"released", "refused"}


@pytest.mark.parametrize("make", [
    lambda t: t / "absent",
    lambda t: (t / "file").write_text("") or t / "file",
    lambda t: ((t / "full").mkdir(), (t / "full/x").write_text(""))[0] or t / "full",
    lambda t: ((t / "real").mkdir(), (t / "lnk").symlink_to(t / "real"))[0] or t / "lnk",
])
def test_an_unusable_release_directory_is_refused(tmp_path, make):
    with pytest.raises(AnalystRefused) as caught:
        check_release_dir(make(tmp_path), forbidden=())
    assert caught.value.code == "release-unusable"


def test_a_release_directory_inside_or_around_a_forbidden_path_is_refused(tmp_path):
    (tmp_path / "in/rel").mkdir(parents=True)
    (tmp_path / "rel2").mkdir()
    (tmp_path / "empty").mkdir()
    # inside a forbidden path; equal to one; containing a forbidden path that does not exist yet (a denied
    # path need not exist: releasing there would create it)
    for candidate, forbidden in ((tmp_path / "in/rel", tmp_path / "in"), (tmp_path / "in/rel", tmp_path / "in/rel"),
                                 (tmp_path / "empty", tmp_path / "empty/key.json")):
        with pytest.raises(AnalystRefused) as caught:
            check_release_dir(candidate, forbidden=[forbidden])
        assert caught.value.code == "release-unusable", (candidate, forbidden)
    assert check_release_dir(tmp_path / "rel2", forbidden=[tmp_path / "in"]) == (tmp_path / "rel2").resolve()
