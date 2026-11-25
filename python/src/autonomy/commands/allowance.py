"""Operator commands for issuing, revoking and recording evidence against a grant."""
import argparse
import json
import os
import sys

from autonomy.allowance import AllowanceRefused, Campaign
from autonomy.allowance._configuration import parse_json, private_config, resolve, storage
from autonomy.allowance._contract import opaque
from autonomy.baseline import write_all
from autonomy.run import config_root


def add_parser(commands):
    group = commands.add_parser("allowance", help="manage operator grants for metered work")
    ops = group.add_subparsers(dest="operation", required=True, parser_class=commands._parser_class)
    ops.add_parser("issue", help="issue a new campaign from named operator configuration").add_argument("name")
    ops.add_parser("revoke", help="permanently close a campaign").add_argument("campaign")
    turn = ops.add_parser("record-turn", help="attach one validated Band turn on stdin")
    turn.add_argument("reference")
    turn.add_argument("--conversation-id", required=True)
    turn.add_argument("--envelope", required=True)


def execute(args: argparse.Namespace):
    config = config_root(os.environ)
    try:
        if args.operation == "issue":
            grant = private_config(config / "allowances" / (opaque(args.name) + ".json"))
            root = storage(config)
            campaign = Campaign.issue(root, grant)
            receipt = campaign.receipt()
        elif args.operation == "revoke":
            receipt = Campaign(storage(config), args.campaign).revoke()
        else:
            pool, member = resolve(config, args.reference)
            data = sys.stdin.buffer.read(1_048_577)
            if len(data) > 1_048_576:
                raise ValueError("oversized turn report")
            report = parse_json(data)
            receipt = pool.record_turn(member, args.envelope, args.conversation_id, report)
        write_all(1, (json.dumps(receipt, allow_nan=False) + "\n").encode())
        return 0
    except (ValueError, RecursionError):
        write_all(2, b"autonomy: allowance-scope: invalid JSON document\n")
        return 2
    except AllowanceRefused as exc:
        write_all(2, f"autonomy: {exc}\n".encode())
        return 2
