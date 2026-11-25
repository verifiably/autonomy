"""Serialize admission until the original world and written chains are recorded."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import re
import stat

from autonomy.baseline import ADMISSION_LOCK, append_event, fsync_dir, is_publication_alias, lock, publish_json, read_events, read_record, utc_now
from autonomy.development import valid_run as valid_development_run
from autonomy.egress.helper import MODEL_URL
from autonomy.egress.route import LoadedRoute
from autonomy.membership import Finding
from autonomy.process import ProcessIdentity, ProcessSurvived
from autonomy.run import Opened, Places, Progress, RunDirs, RunRefused, RunRequest, allocate, ensure_run_parents, read_disposition
from autonomy.science_reads import ChainHead, Heads, ReadUnavailable, ScienceReader
from autonomy.science_run._config import Config, operator

_RUN_ID = re.compile(r"[0-9a-f]{32}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_RECORD_ERRORS = (OSError, ValueError, KeyError, TypeError, RecursionError)
SUPERVISOR_LOCK = "supervisor.lock"
SEAL_TIMEOUT = 30.0
START_TIMEOUT = 30.0


@dataclass(frozen=True)
class Opening:
    config: Config
    reader: ScienceReader
    heads: Heads
    written: tuple[ChainHead, ...]
    mounts: tuple[ChainHead, ...]
    toolchain: tuple[Path, ...]


def _retired(run_dir: Path, env: Mapping[str, str]) -> bool:
    try:
        record = read_record(run_dir / "run.json")
    except FileNotFoundError:
        record = None
    if record is not None and record.get("mode") == "development":
        return valid_development_run(run_dir, env)
    return read_disposition(run_dir) is not None


def _no_possible_writer(run_dir: Path, *, resolvers_reaped: bool = False) -> bool:
    events, torn = read_events(run_dir)
    names = {path.name for path in run_dir.iterdir()}
    staged = {"run.json", "baseline.json", "launch.json", "disposition.json"}
    permitted = (staged - {"disposition.json"}) | {"events.jsonl", SUPERVISOR_LOCK, "endpoint.log"}
    if any(name not in permitted and not any(is_publication_alias(name, final) for final in staged) for name in names):
        return False
    # Each resolver and endpoint records its identity before it can write.
    allowed = {"allocated", "report-unwritten"}
    if resolvers_reaped:
        allowed.add("baseline-resolving")
    if (torn and not events) or any(row.get("event") not in allowed for row in events):
        return False
    after_allocation = {"baseline.json", "launch.json", "endpoint.log"}
    has_staging = any(name in after_allocation or any(is_publication_alias(name, final) for final in after_allocation)
                      for name in names)
    if not events and has_staging:
        return False
    try:
        metadata = read_record(run_dir / "run.json")
    except FileNotFoundError:
        return not has_staging and not torn and all(row.get("event") == "report-unwritten" for row in events)
    return (
        type(metadata.get("version")) is int and metadata["version"] == 1
        and metadata.get("run") == run_dir.name and metadata.get("mode") == "science"
        and (not events or (events[0].get("event") == "allocated" and events[0].get("run") == run_dir.name
                            and events[0].get("mode") == "science"))
    )


def _roots(run_dir: Path) -> tuple[tuple[str, str, Path], ...]:
    record = read_record(run_dir / "baseline.json")
    written = record.get("written")
    if record.get("version") != 1 or record.get("run") != run_dir.name or not isinstance(written, dict) or not written:
        raise ValueError("baseline has no written roots")
    output = []
    for chain_id, row in written.items():
        if (not _RUN_ID.fullmatch(chain_id) or not isinstance(row, dict)
                or row.get("role") not in ("corpus", "store")):
            raise ValueError("invalid written chain identity")
        root = Path(row["root"])
        if root.anchor != "/" or not root.is_absolute() or ".." in root.parts or str(root) != row["root"]:
            raise ValueError("invalid written root path")
        for name in ("genesis", "tip"):
            if not isinstance(row.get(name), str) or not _DIGEST.fullmatch(row[name]):
                raise ValueError("invalid written chain digest")
        output.append((row["role"], chain_id, root))
    return tuple(output)


def _overlapping(where: Places, config: Config, reader: ScienceReader | None,
                 env: Mapping[str, str], *, until: float | None = None) -> None:
    footprint = {config.world_root, *config.corpora, *config.stores}
    known: list[tuple[Path, tuple[tuple[str, str, Path], ...]]] = []

    def refuse(run_dir: Path) -> None:
        raise RunRefused("orphaned-run", f"run {run_dir.name} may own a written chain; close it once its supervisor exits")

    for run_dir in sorted((where.state / "runs").iterdir()):
        if not _RUN_ID.fullmatch(run_dir.name):
            continue
        try:
            if not stat.S_ISDIR(run_dir.lstat().st_mode):
                refuse(run_dir)
            if _retired(run_dir, env):
                continue
            try:
                roots = _roots(run_dir)
            except _RECORD_ERRORS:
                if _no_possible_writer(run_dir):
                    continue
                raise
        except _RECORD_ERRORS:
            refuse(run_dir)
        if footprint & {root for _, _, root in roots}:
            refuse(run_dir)
        known.append((run_dir, roots))
    if not known or reader is None:
        return
    # Detached inspection cannot resolve work from an unfinished interval.
    config.verify()
    heads = reader.heads(resolve=False, until=until)
    config.verify()
    identities = {(chain.role, chain.chain_id) for chain in heads.chains}
    inspected_roots = {chain.root for chain in heads.chains}
    for run_dir, roots in known:
        if (identities & {(role, chain_id) for role, chain_id, _ in roots}
                or inspected_roots & {root for _, _, root in roots}):
            refuse(run_dir)


def _written(heads: Heads, roots: dict[str, Path]) -> tuple[ChainHead, ...]:
    found = {(head.role, head.root): head for head in heads.chains}
    try:
        return tuple(found[(role, root)] for role, root in roots.items())
    except KeyError as error:
        raise ReadUnavailable("science heads did not identify a configured written chain") from error


def _chains(chains: tuple[ChainHead, ...]) -> dict[str, object]:
    return {chain.chain_id: {"root": str(chain.root), "genesis": chain.genesis, "tip": chain.tip, "role": chain.role}
            for chain in chains}


class Admission:
    """Hold the lifetime lock through publication and the admission lock through baseline capture."""

    def __init__(self, request: RunRequest, env: Mapping[str, str], *, until: float | None = None,
                 cancelled: Callable[[], bool] | None = None) -> None:
        self.request = request
        self.until = until
        self.cancelled = cancelled
        self.env = env
        self._fd: int | None = None

    @contextmanager
    def open(self, where: Places, route: LoadedRoute | None, progress: Progress | None = None) -> Iterator[RunDirs]:
        self.config, self.reader, self.unavailable = operator(self.env)
        ensure_run_parents(where)
        with self._opening_lock(where) as admission_fd:
            if self.config is not None:
                try:
                    _overlapping(where, self.config, self.reader, self.env, until=self.until)
                except ReadUnavailable as error:
                    self.unavailable = str(error)
            if self.cancelled is not None and self.cancelled():
                raise RunRefused("admission-interrupted", "opening was stopped before allocation")
            dirs = allocate(where, progress=progress)
            for directory in (where.state, where.cache, dirs.run_dir.parent, dirs.scratch.parent, dirs.socket_dir.parent):
                fsync_dir(directory)
            with lock(dirs.run_dir / SUPERVISOR_LOCK, create=True):
                config = self.config
                meta = {
                    "version": 1, "mode": "science", "run": dirs.run_id,
                    "config": str(config.path) if config else None,
                    "config_sha256": config.digest if config else None,
                    "operations": str(config.operations) if config else None,
                    "executable": str(self.reader.executable) if self.reader else None,
                    "deadline_seconds": self.request.deadline,
                    "lease_seconds": self.request.lease, "seal_timeout_seconds": SEAL_TIMEOUT,
                }
                if route is not None and route.member is not None:
                    member = route.member
                    meta["allowance"] = {"campaign_id": member.pool.name, "member_id": member.name,
                                         "grant_digest": member.grant_digest, "storage": member.storage}
                publish_json(dirs.run_dir / "run.json", meta)
                append_event(dirs.run_dir, "allocated", mode="science", run=dirs.run_id, **ProcessIdentity.capture(os.getpid()).fields())
                self._fd = admission_fd
                try:
                    yield dirs
                finally:
                    self._fd = None

    @contextmanager
    def _opening_lock(self, where: Places) -> Iterator[int]:
        with ExitStack() as stack:
            try:
                fd = stack.enter_context(lock(where.state / ADMISSION_LOCK, create=True, until=self.until,
                                              cancelled=self.cancelled))
            except TimeoutError as error:
                raise RunRefused("admission-interrupted", str(error)) from error
            yield fd

    def capture(self, opened: Opened) -> Opening | Finding:
        if self._fd is None:
            raise RuntimeError("baseline capture requires an admitted run")
        try:
            return self._capture(opened)
        finally:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            self._fd = None

    def _capture(self, opened: Opened) -> Opening | Finding:
        config, reader = self.config, self.reader
        if self.unavailable is not None or config is None or reader is None:
            return Finding("baseline-unavailable", "science", self.unavailable or "science evidence is unavailable")
        def record(identity: ProcessIdentity) -> None:
            append_event(opened.dirs.run_dir, "baseline-resolving", **identity.fields())

        try:
            config.verify()
            heads = reader.heads(resolve=True, record=record, until=self.until)
            config.verify()
            written = _written(heads, config.written(opened.request))
            declared = {("corpus", path) for path in config.corpora} | {("store", path) for path in config.stores}
            if declared - {(head.role, head.root) for head in heads.chains}:
                raise ReadUnavailable("science heads omit configured chains")
            if len({head.chain_id for head in heads.chains}) != len(heads.chains):
                raise ReadUnavailable("chain identities cannot share a baseline key")
            toolchain = tuple(path.absolute().resolve() for path in opened.request.toolchain)
        except ProcessSurvived:
            raise
        except (ReadUnavailable, OSError, RuntimeError) as error:
            return Finding("baseline-unavailable", "science", str(error))
        if heads.world_pending or any(head.pending for head in heads.chains):
            return Finding("baseline-pending", "science", "a chain still has pending transactions after recovery")
        mounts = tuple(chain for chain in heads.chains if chain not in written)
        route = opened.route
        egress = None if route is None else {
            "route": route.name, "digest": route.digest, "upstream": route.route.upstream, "url": MODEL_URL,
        }
        publish_json(opened.dirs.run_dir / "baseline.json", {
            "version": 1, "run": opened.dirs.run_id, "opened_at": utc_now(),
            "tier": opened.request.tier.to_json(), "permit": opened.request.tier.permit.to_json(),
            "world": {"root": str(config.world_root), "id": config.world_id,
                      "genesis": heads.world_genesis, "tip": heads.world_head},
            "written": _chains(written), "mounts": _chains(mounts), "actor_argv": list(opened.request.actor_argv),
            "sandbox": {"binds": list(map(str, toolchain)), "stdio": list(opened.stdio)},
            "egress": egress, "lease": {"seconds": opened.request.lease},
        })
        return Opening(config, reader, heads, written, mounts, toolchain)
