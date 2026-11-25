"""Project the operator's bound target into the Science launch contract."""
import re
from pathlib import PurePosixPath

from autonomy.allowance import _contract as c

COMMANDS = ("next", "run", "assess", "verify", "belief")
ROUTES = {"run": "run", "act-report": "run", "assessment": "corpus-write", "verification": "corpus-write"}


def _relative(path):
    c.require(type(path) is str and path and not PurePosixPath(path).is_absolute()
              and all(p not in ("", ".", "..") for p in path.split("/")), "invalid workflow path")


def research_action(member, world, written, routes):
    target = {k: v for k, v in member.target.items() if k != "worker"}
    c.keys(target, ("world_id", "corpus_id", "proposition", "spec", "dataset", "workflow"))
    c.require(target["world_id"] == world and [(h.role, h.chain_id) for h in written] == [("corpus", target["corpus_id"])]
              and routes == ROUTES, "research world, written corpus or permit differs")
    for field, prefix in (("proposition", "proposition:"), ("spec", "analysis-spec:"), ("dataset", "dataset:")):
        value = target[field]
        c.require(type(value) is str and value.startswith(prefix) and len(value) > len(prefix), "invalid bound " + field)
    workflow = target["workflow"]
    c.keys(workflow, ("tree_digest", "entrypoint", "targets", "cores"))
    c.require(type(workflow["tree_digest"]) is str and re.fullmatch("sha256-tree:[a-f0-9]{64}", workflow["tree_digest"]),
              "invalid workflow tree digest")
    _relative(workflow["entrypoint"])
    c.integer(workflow["cores"], 1)
    c.require(type(workflow["targets"]) is list and workflow["targets"], "missing workflow targets")
    for path in workflow["targets"]:
        _relative(path)
    return {"campaign_id": member.pool.name, "member_id": member.name, "conversation_id": member.conversation_id,
            "commands": list(COMMANDS), **{k: target[k] for k in ("proposition", "spec", "dataset", "workflow")}}
