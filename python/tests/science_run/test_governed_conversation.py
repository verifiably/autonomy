"""Offline qualification through the normal Band, Autonomy, Science and Beliefs entrypoints."""

from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import tomllib

import pytest

from egress_fixtures import MODEL, TextTurn, ToolTurn, governed_route, pi_route, tls, write_credential
from science_run.test_integration import _upstream, world
from test_analyst_check import PI_1_1_0_BETAS, toolchain

pytestmark = [pytest.mark.science_endpoint, pytest.mark.pi, pytest.mark.bwrap]


def cut_original(world, pool, member, mode):
    from autonomy.sandbox.bwrap import _pin_worker

    until = time.monotonic() + 95

    def wait_for(read):
        while time.monotonic() < until:
            value = read()
            if value:
                return value
            time.sleep(0.01)
        raise AssertionError("original job did not reach its cut")

    job = wait_for(lambda: next((r for r in pool.snapshot(member)["reservations"] if r["role"] == "job"), None))
    directory = world.runs / job["envelope"]
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    session = next(e for e in events if e["event"] == "session-open")
    ledger = Path(session["ledger_path"])
    if mode == "revoked":
        endpoint = next(e["pid"] for e in events if e["event"] == "endpoint-starting")

        def workflow_running():
            # Wait past the confinement probe's GO. At this point the real
            # Snakemake interpreter has replaced the probe in the namespace.
            todo = [endpoint]
            while todo:
                proc = Path("/proc") / str(todo.pop())
                try:
                    argv = (proc / "cmdline").read_bytes().split(b"\0")
                    if b"--snakefile" in argv and any(Path(os.fsdecode(a)).name == "snakemake" for a in argv[:3]):
                        return True
                    for children in (proc / "task").glob("*/children"):
                        todo.extend(map(int, children.read_bytes().split()))
                except (FileNotFoundError, ProcessLookupError):
                    continue
            return False

        wait_for(workflow_running)
        subprocess.run(
            [str(Path(sys.executable).with_name("autonomy")), "allowance", "revoke", pool.name],
            env=world.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=15,
        )
        return
    init = next(e["pid"] for e in events if e["event"] == "actor-launched")
    init_fd = os.pidfd_open(init)
    try:
        worker = _pin_worker(init, init_fd)
    finally:
        os.close(init_fd)
    try:
        signal.pidfd_send_signal(worker, signal.SIGSTOP)
        iid = job["request"]["invocation_id"]

        def committed():
            for raw in ledger.read_bytes().splitlines(keepends=True):
                if not raw.endswith(b"\n"):
                    continue
                row = json.loads(raw)
                if row.get("line") == "invocation-close" and row.get("invocation") == iid:
                    return row.get("outcome", {}).get("done")

        wait_for(committed)
    finally:
        signal.pidfd_send_signal(worker, signal.SIGKILL)
        os.close(worker)


def retain_qualification(report, world, case, pins):
    destination = os.environ.get("AUTONOMY_TEST_EVIDENCE")
    if not destination:
        return
    root = Path(destination) / case
    root.mkdir(mode=0o700)
    (root / "report.json").write_text(json.dumps(report, indent=2))
    (root / "synthetic-pins.json").write_text(json.dumps(pins, sort_keys=True))
    for envelope in report["envelopes"]:
        rid = envelope["envelope_id"]
        directory = world.runs / rid
        retained = root / rid
        retained.mkdir(mode=0o700)
        for filename, expected in envelope["evidence_sha256"].items():
            copy = Path(shutil.copyfile(directory / filename, retained / filename))
            assert hashlib.sha256(copy.read_bytes()).hexdigest() == expected
        events = [json.loads(line) for line in (retained / "events.jsonl").read_text().splitlines()]
        ledger = Path(next(e["ledger_path"] for e in events if e["event"] == "session-open"))
        shutil.copyfile(ledger, retained / "ledger.v1")


@pytest.mark.parametrize(
    "mode", ["immediate", "delayed-answer", "lost-first-report", "lost-worker", "revoked", "no-eligible"]
)
def test_science_action_and_operator_report(world, tls, toolchain, tmp_path, mode):
    delayed = mode in ("delayed-answer", "lost-first-report")
    band = os.environ.get("BAND_TEST_ROOT")
    if not band:
        pytest.skip("set BAND_TEST_ROOT to the Band checkout under qualification")
    band = Path(band).resolve()
    pi, node = toolchain
    source = (
        Path(
            subprocess.check_output(
                [str(world.science.with_name("python")), "-c", "import science;print(science.__path__[0])"],
                env=world.env,
                text=True,
            ).strip()
        ).parents[1]
        / "tests"
    )
    demo = source / "fixtures/analysis/demo.py"
    world.env["SCIENCE_READBACK_FIXTURE"] = str(demo)
    world.env["SCIENCE_READBACK_SHA256"] = hashlib.sha256(demo.read_bytes()).hexdigest()
    host = world.env | {"PYTHONPATH": str(source)}
    # Six entirely synthetic pins. Equal stage samples give no directional result.
    inputs = {name: tmp_path / name for name in ("matrix", "crosswalk", "dataset", "proposition", "hgnc", "ensembl")}
    for name, path in inputs.items():
        path.write_bytes(
            gzip.compress(
                b"gene\ta_NDMM\tb_NDMM\tc_NDMM\td_PD\te_PD\tf_PD\nENSG00000119403\t1\t2\t3\t1\t2\t3\n", mtime=0
            )
            if name == "matrix"
            else f"Synthetic {name} provenance\n".encode()
        )
    pins = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in inputs.items()}
    prepared = subprocess.check_output(
        [
            str(world.science.with_name("python")),
            "-c",
            """import json, runpy, sys
from pathlib import Path
demo = runpy.run_path(sys.argv[1])
paths = {k: Path(v) for k, v in json.loads(sys.argv[3]).items()}
world = demo["create_phf19"](Path(sys.argv[2]), paths, input_digests=json.loads(sys.argv[4]))
target = demo["prepare"](world)
if sys.argv[5] == "no-eligible":
    _, session, _, invoke, record = demo["_commands"](world)
    try:
        inputs = world.authoring_inputs()["run"] | {"spec": target["spec"], "dataset": target["dataset"]}
        original = record(invoke("run", inputs), "run")
        invoke("assess", {"run": original})
    finally:
        session.close()
print(json.dumps([str(world.config), str(world.code), target]))
""",
            str(demo),
            str(world.root / "research"),
            json.dumps({k: str(v) for k, v in inputs.items()}),
            json.dumps(pins),
            mode,
        ],
        env=host,
        text=True,
        timeout=120,
    )
    config_path, code, target = json.loads(prepared.splitlines()[-1])
    world.env["SCIENCE_CONFIG"] = config_path
    bundle = shutil.copytree(code, tmp_path / "workflow")
    config = Path(world.env["XDG_CONFIG_HOME"]) / "verifiably-autonomy"
    config.mkdir(parents=True, exist_ok=True)

    def action(command, inputs):
        return ToolTurn("science_action", {"command": command, "inputs": inputs})

    def previous(command, field):
        def reply(body):
            contents = (
                b["content"]
                for msg in reversed(body["messages"])
                if isinstance(msg["content"], list)
                for b in reversed(msg["content"])
                if b["type"] == "tool_result"
            )
            for content in contents:
                text = content if isinstance(content, str) else content[0]["text"]
                if text.startswith("{"):
                    match = re.search(field + ":[A-Za-z0-9_-]+", json.loads(text).get("text", ""))
                    if match:
                        result_id = match.group()
                        break
            else:
                raise AssertionError("model context is missing the returned Science record")
            inputs = {field: result_id}
            if command == "verify":
                inputs["entrypoint"] = target["workflow"]["entrypoint"]
            return action(command, inputs)

        return reply

    with _upstream(tls, "script") as upstream:
        upstream.script = [
            action("next", {}),
            action(
                "run",
                {k: target[k] for k in ("spec", "dataset")}
                | {k: target["workflow"][k] for k in ("entrypoint", "targets")},
            ),
            previous("assess", "run"),
            previous("verify", "assessment"),
            action("belief", {"proposition": target["proposition"]}),
            TextTurn("Finished."),
        ]
        if mode == "no-eligible":
            upstream.script = [action("next", {}), TextTurn("No eligible work.")]
        if delayed:
            upstream.script.insert(
                3,
                ToolTurn(
                    "ask_question",
                    {
                        "items": [
                            {
                                "id": "verify",
                                "header": "Verify",
                                "prompt": "Verify the bound assessment?",
                                "type": "boolean",
                            }
                        ]
                    },
                ),
            )
        doc = pi_route(
            credential=write_credential(config / "credentials/fixture", "local-fixture-key"),
            upstream=upstream.origin,
            ca_file=tls.cert,
        )
        doc["header_tokens"]["anthropic-beta"].extend(PI_1_1_0_BETAS)
        route = governed_route(config, "fixture", doc, caller="band", target=target)
        reference = tomllib.loads(route.read_text())["allowance"]
        executable = str(Path(sys.executable).with_name("autonomy"))
        host_executable = executable
        if mode == "lost-first-report":
            wrapper = tmp_path / "lose-first-output"
            marker = tmp_path / "lost-output"
            wrapper.write_text(
                "#!/usr/bin/python3\nimport os,sys\nfrom pathlib import Path\n"
                + f"m=Path({str(marker)!r})\nexe={executable!r}\n"
                + "if sys.argv[1]=='run' and not m.exists():\n m.touch(); os.dup2(os.open(os.devnull,os.O_WRONLY),1)\n"
                + "os.execv(exe,[exe,*sys.argv[1:]])\n"
            )
            wrapper.chmod(0o700)
            host_executable = str(wrapper)
        launch = {
            "kind": "autonomy",
            "executable": host_executable,
            "tier": "mints",
            "routes": ["run=run", "act-report=run", "assessment=corpus-write", "verification=corpus-write"],
            "modelRoute": "fixture",
            "deadlineSeconds": 120,
            "leaseSeconds": 20,
            "toolchain": [],
            "env": world.env,
            "research": {
                "allowance": reference,
                "maxTokens": 2048,
                "workflow": str(bundle),
                "expires": int(time.time()) + 3600,
            },
        }
        brief = tmp_path / "brief.json"
        brief.write_text(
            json.dumps(
                {
                    "brief": "Complete the specified local scientific action.",
                    "definition": {
                        "schema": 1,
                        "modelId": MODEL,
                        "piInstall": str(pi.dir),
                        "launch": launch,
                        "context": {"project": None, "taskId": None},
                        "extensions": [],
                    },
                }
            )
        )
        if mode in ("lost-worker", "revoked"):
            from autonomy.allowance import Campaign

            pool = Campaign(config.parent / "allowance-state", reference.split("/")[0])
            with ThreadPoolExecutor(max_workers=1) as driver:
                cut = driver.submit(cut_original, world, pool, "member", mode)
                first = subprocess.run(
                    [
                        str(node / "bin/node"),
                        str(band / "src/cli.ts"),
                        "science-action",
                        "start",
                        str(tmp_path / "conversation"),
                        str(brief),
                    ],
                    env=world.env,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                cut.result()
            if mode == "revoked":
                report = json.loads(
                    subprocess.check_output([executable, "allowance", "report", reference], env=world.env)
                )
                retain_qualification(report, world, mode, pins)
                assert report["closed"] == "revoked" and report["job_starts"] == 1, report
                science = report["envelopes"][0]["science"]
                assert science["stop"] == "allowance-closed" and science["seal_cause"] == "stop", science
                assert science["jobs"][0]["status"] == "run-cancelled", science
                return
            assert json.loads(first.stdout)["report"] is None, first
            snapshot = pool.snapshot("member")
            assert snapshot["provider_session_id"] and len(snapshot["envelopes"]) == 1
            assert len([j for j in snapshot["reservations"] if j["role"] == "job"]) == 1
            upstream.script[2:] = [TextTurn("Acknowledged the recovered original run.")]
            resumed = subprocess.run(
                [
                    str(node / "bin/node"),
                    str(band / "src/cli.ts"),
                    "science-action",
                    "resume",
                    str(tmp_path / "conversation"),
                ],
                env=world.env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=180,
            )
            assert resumed.returncode == 0, (resumed.stderr, resumed.stdout)
            assert any(b"Recorded Science outcomes" in r.body for r in upstream.seen), [
                r.body[-300:] for r in upstream.seen
            ]
            report = json.loads(
                subprocess.check_output([executable, "allowance", "report", reference], env=world.env)
            )
            assert len(report["envelopes"]) == 2 and report["job_starts"] == 1, report
            retain_qualification(report, world, mode, pins)
            return
        result = subprocess.run(
            [
                str(node / "bin/node"),
                str(band / "src/cli.ts"),
                "science-action",
                "start",
                str(tmp_path / "conversation"),
                str(brief),
            ],
            env=world.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=200,
        )
        assert result.returncode == 0, (result.stderr, result.stdout)
        if delayed:
            directory = tmp_path / "conversation"
            first = json.loads(result.stdout)
            assert first["receipt"]["disposition"] == "clean"
            if mode == "lost-first-report":
                assert first["report"] is None
                events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
                assert next(e for e in events if e["type"] == "turn-recovered")["report"]["question"]
                assert (
                    next(e for e in events if e["type"] == "research-receipt")["receipt"]["envelope_id"]
                    == first["runId"]
                )
            else:
                assert first["report"]["question"]
            old_count = len(upstream.seen)
            cli = [str(node / "bin/node"), str(band / "src/cli.ts"), "science-action"]
            refused = subprocess.run(
                [*cli, "resume", str(directory)],
                env=world.env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert refused.returncode != 0 and len(upstream.seen) == old_count
            relay = tmp_path / "fixture-inbox"
            relay.write_text(
                "#!/usr/bin/python3\n"
                + """import json,sys
op=sys.argv[2]
qid=json.load(open(sys.argv[4]))["id"] if op=="ask" else sys.argv[3]
answer={"answerId":"3d86cb66-6c46-499d-a75f-e7aa9a64ec87","outcome":"answered","values":{"verify":{"type":"boolean","value":True}}}
print(json.dumps({"entry":{"id":qid,"state":"answered","kind":"question","answer":{"body":answer}}}))
"""
            )
            relay.chmod(0o700)
            for expected in ("delivered", "no-question"):
                deliver = subprocess.run(
                    [*cli, "deliver", str(directory), str(relay)],
                    env=world.env,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                assert deliver.returncode == 0, deliver.stderr
                assert json.loads(deliver.stdout)["state"] == expected, deliver.stdout
        report = json.loads(
            subprocess.check_output([executable, "allowance", "report", reference], env=world.env, text=True)
        )
        retain_qualification(report, world, mode, pins)
        assert report["accounting_complete"], report
        if mode == "no-eligible":
            assert report["action_outcome"] == "nothing needed" and report["next_decision"] is None, report
            assert report["job_starts"] == 0 and report["attempts"] == 2
            assert not report["envelopes"][0]["science"]["records"]
            return
        assert report["attempts"] == 6 + delayed and report["job_starts"] == 2, report
        assert [j["status"] for e in report["envelopes"] for j in e["science"]["jobs"]] == ["completed", "completed"]
        assert report["envelopes"][0]["science"]["disposition"] == "clean"
        assert report["scientific_outcome"]["verdict"] == "passed", report
        assert report["scientific_outcome"]["outcome"] == "inconclusive"
        assert report["scientific_outcome"]["belief"]["kind"] == "NoBelief"
        assert report["scientific_outcome"]["belief"]["reason"] == "no-directional-outcome"
        assert report["action_outcome"] == "proved" and report["envelopes"][0]["science"]["selection"] == "ready"
        assert report["next_decision"] is None
        final_context = upstream.seen[-1].body
        outcome = report["scientific_outcome"]
        for field in ("assessment", "verification"):
            assert outcome[field].encode() in final_context
        for field in ("key", "kind", "reason"):
            assert f"{field}: {outcome['belief'][field]}".encode() in final_context
        readback = subprocess.check_output(
            [str(world.science.with_name("python")), str(demo), "readback", config_path], env=host, text=True
        )
        assert "verification" in readback and "assessment" in readback
