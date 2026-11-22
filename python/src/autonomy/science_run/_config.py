"""The published science configuration fields used by the supervisor."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import shutil
import tomllib

from autonomy.run import RunRefused, RunRequest
from autonomy.science_reads import ReadUnavailable, ScienceReader, has_handle


@dataclass(frozen=True)
class Config:
    path: Path
    digest: str
    world_root: Path
    world_id: str
    write_root: Path
    corpora: tuple[Path, ...]
    store_root: Path
    stores: tuple[Path, ...]
    operations: Path
    denied: tuple[Path, ...]

    def written(self, request: RunRequest) -> dict[str, Path]:
        roots = {"corpus": self.write_root}
        permit = request.tier.permit
        if "holdings-observation" in permit.kinds and "holdings" in permit.act_families:
            roots["store"] = self.store_root
        return roots

    def verify(self) -> None:
        try:
            unchanged = hashlib.sha256(self.path.read_bytes()).hexdigest() == self.digest
        except OSError as error:
            raise ReadUnavailable("science config is unavailable") from error
        if not unchanged:
            raise ReadUnavailable("science config changed during admission")


def read_config(path: Path) -> Config:
    path = path.resolve(strict=True)
    data = path.read_bytes()
    values = tomllib.loads(data.decode())

    def resolve(value: object) -> Path:
        if not isinstance(value, str) or not value or "\0" in value:
            raise ValueError("invalid path in science config")
        return (path.parent / value).resolve()

    def paths(key: str, *, optional: bool = False) -> tuple[Path, ...]:
        if optional and key not in values:
            return ()
        items = values[key]
        if not isinstance(items, list):
            raise ValueError(f"{key} must be a path list")
        return tuple(resolve(item) for item in items)

    corpora = paths("corpus_roots")
    if "write_root" in values:
        write_root = resolve(values["write_root"])
        if write_root not in corpora:
            raise RunRefused("write-root-unknown", "science write_root is outside its configured corpora")
    elif len(corpora) == 1:
        write_root, = corpora
    else:
        raise ValueError("science must name one write root")
    world = resolve(values["world_root"])
    world_id = values["world_id"]
    if not isinstance(world_id, str) or not re.fullmatch(r"[0-9a-f]{32}", world_id):
        raise ValueError("invalid configured science world ID")
    operations = resolve(values["operations_root"])
    store = resolve(values["store_root"])
    stores = (store, *paths("read_store_roots", optional=True))
    extra = tuple(resolve(values[key]) for key in ("sharing_root", "service_socket") if key in values)
    return Config(path, hashlib.sha256(data).hexdigest(), world, world_id, write_root, corpora, store, stores,
                  operations, (path, world, operations, *corpora, *stores, *extra))


def operator(env: Mapping[str, str]) -> tuple[Config | None, ScienceReader | None, str | None]:
    if has_handle(env):
        return None, None, "operator evidence unavailable with a science handle"
    try:
        value = env.get("SCIENCE_CONFIG")
        if not value:
            raise ValueError("SCIENCE_CONFIG is required")
        config = read_config(Path(value))
    except (OSError, ValueError, KeyError, RuntimeError):
        return None, None, "science configuration is unavailable"
    executable = shutil.which("science", path=env.get("PATH", ""))
    if executable is None:
        return config, None, "science executable is unavailable"
    try:
        path = Path(executable).resolve(strict=True)
    except OSError:
        return config, None, "science executable is unavailable"
    return config, ScienceReader(path, config.path, env=env), None
