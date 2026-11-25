"""Read private operator policy and resolve a reference on its qualified volume."""
import os
import json
from pathlib import Path
import re

from autonomy.baseline import read_private_bytes
from . import _contract as c
from ._database import GrantUnusable, private_path
from ._store import Campaign


def parse_json(data):
    def distinct(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("invalid JSON number")

    return json.loads(data, object_pairs_hook=distinct, parse_constant=invalid_constant)


def private_config(path):
    try:
        return parse_json(read_private_bytes(path))
    except (OSError, ValueError, RecursionError) as exc:
        raise c.AllowanceRefused("allowance-unavailable", f"cannot read private {path.name}") from exc


def storage(config_dir):
    record = private_config(config_dir / "allowance-storage.json")
    try:
        c.keys(record, ("version", "path", "device", "inode"))
        root = Path(record["path"])
        private_path(root, directory=True)
        info = root.stat()
        if (record["version"], record["device"], record["inode"]) != (1, info.st_dev, info.st_ino):
            raise ValueError("qualified directory was replaced")
        # The operator attests that this directory is outside all synchronization services.
        # Check the actual mount as well; an attestation cannot qualify tmpfs or a remote mount.
        with Path("/proc/self/mountinfo").open() as mounts:
            candidates = []
            for line in mounts:
                before, after = line.split(" - ", 1)
                fields = before.split()
                point = Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[4]))
                if fields[2] == f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}" and root.is_relative_to(point):
                    candidates.append((len(point.parts), after.split()[0]))
        if not candidates or max(candidates)[1] not in ("ext4", "xfs", "btrfs"):
            raise ValueError("unsupported accounting filesystem")
        return root
    except (OSError, TypeError, ValueError, GrantUnusable, c.AllowanceRefused) as exc:
        raise c.AllowanceRefused("allowance-unavailable", "cannot verify qualified local storage") from exc


def resolve(config_dir, reference):
    if not reference:
        raise c.AllowanceRefused("allowance-missing", "select an issued campaign/member")
    parts = reference.split("/")
    c.require(len(parts) == 2, "reference must be campaign/member")
    campaign, member = map(c.opaque, parts)
    return Campaign(storage(config_dir), campaign), member
