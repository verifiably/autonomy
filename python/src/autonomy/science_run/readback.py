"""Retain detached scientific readback after the envelope and its writer have closed."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

from autonomy.allowance import AllowanceRefused
from autonomy.baseline import decode_object, publish_json, read_events, read_record
from autonomy.endpoint import EndpointError
from autonomy.ledger import Ledger, load_ledger
from autonomy.science_reads import ReadUnavailable
from autonomy.science_run._recovery import _session, trusted_seal
from autonomy.science_run.history import history


__all__ = ["capture"]


def capture(opened, opening, result, env):
    member = opened.route.member if opened.route else None
    if not member or member.caller != "band" or result.findings:
        return
    directory = opened.dirs.run_dir
    try:
        opening.config.verify()
        events, torn = read_events(directory)
        session = _session(events, opening.config.operations)
        if not session or torn:
            return
        ledger = load_ledger(session.ledger_path, session.session_id)
        if not isinstance(ledger, Ledger) or ledger.incomplete:
            return
        seal = trusted_seal(directory, opening.written, session, ledger, events)
        if seal is None or seal != read_record(directory / "seal.json"):
            return
        local = {
            address
            for act in ledger.acts
            if act.entry in result.members.get(act.corpus, [])
            for _, address in act.records
        }
        checks = [address for address in local if address.startswith("verification:")]
        if len(checks) != 1:
            return
        prior = history(
            member.pool,
            member.name,
            directory.parent,
            member.conversation_id,
            member.provider_session_id,
            current=directory.name,
        )
        known = local | {
            address
            for row in prior["envelopes"]
            for inv in row["invocations"]
            for act in inv["acts"]
            for _, address in act["records"]
        }
        assessments = [address for address in known if address.startswith("assessment:")]
        if len(assessments) != 1:
            raise ValueError("ambiguous assessment")
        target = member.target
        fixture = Path(env["SCIENCE_READBACK_FIXTURE"]).resolve(strict=True)
        script = fixture.read_bytes()
        if hashlib.sha256(script).hexdigest() != env["SCIENCE_READBACK_SHA256"]:
            raise ValueError("operator readback fixture differs from its qualified revision")
        read = subprocess.run(
            [
                str(opening.reader.executable.with_name("python")),
                "-c",
                "import sys; sys.argv=sys.argv[1:]; exec(compile(sys.stdin.buffer.read(),sys.argv[0],'exec'),"
                "{'__name__':'__main__','__file__':sys.argv[0]})",
                str(fixture),
                "readback",
                str(opening.config.path),
                "--proposition",
                target["proposition"],
                "--assessment",
                assessments[0],
                "--verification",
                checks[0],
            ],
            env={k: env[k] for k in ("PATH", "HOME", "LANG") if k in env} | {"PYTHONPATH": str(fixture.parents[2])},
            input=script,
            capture_output=True,
            check=True,
            timeout=30,
        )
        value = decode_object(read.stdout)
        if (
            value["version"] != "research-readback.v1"
            or value["verification"] != checks[0]
            or value["assessment"] != assessments[0]
            or value["run"] not in known
            or any(value[key] != target[key] for key in ("world_id", "corpus_id", "spec", "proposition"))
        ):
            raise ValueError("detached readback does not match admitted records")
        publish_json(directory / "readback.json", value)
    except (
        AllowanceRefused,
        EndpointError,
        ReadUnavailable,
        KeyError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        publish_json(directory / "readback-error.json", {"failure": type(exc).__name__})
