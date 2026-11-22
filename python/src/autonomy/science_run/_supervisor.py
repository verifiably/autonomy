"""Open, release and stop one science actor in the envelope."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import select
import signal
import subprocess
import threading
import time

from autonomy.analyst.walk import walk
from autonomy.baseline import append_event, publish_json
from autonomy.egress.errors import EgressUnproven
from autonomy.egress.helper import MODEL_URL
from autonomy.egress.route import all_egress_denied, egress_denied
from autonomy.egress.session import CLOSE_TIMEOUT, EgressSession, check_proxy, proxy_binds, unproven
from autonomy.endpoint import Control, Endpoint, EndpointError, Launch, check_seal
from autonomy.membership import Finding
from autonomy.process import ProcessIdentity, exited, send_signal
from autonomy.run import Opened
from autonomy.sandbox import bwrap
from autonomy.sandbox.spec import IN_SANDBOX_SOCKET, IN_SANDBOX_TOKEN, SYSTEM_RO, SandboxSpec
from autonomy.sandbox.static import SandboxUnproven, check_binds
from autonomy.science_reads import ChainHead, ReadUnavailable
from autonomy.science_run._admission import Opening, SEAL_TIMEOUT, START_TIMEOUT

_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
_CLOSE_MARGIN = 5.0
_TERM_GRACE = 10.0


class Stop:
    def __init__(self, seconds: float, *, now: Callable[[], float] = time.monotonic) -> None:
        self.now = now
        self.deadline = now() + seconds
        self._cause: str | None = None
        self._previous = {}

    def _signal(self, number: int, _frame) -> None:
        if self._cause is None:
            self._cause = signal.Signals(number).name.lower()

    def __enter__(self) -> Stop:
        for signum in _SIGNALS:
            self._previous[signum] = signal.signal(signum, self._signal)
        return self

    def __exit__(self, *_exception) -> None:
        for signum, previous in self._previous.items():
            signal.signal(signum, previous)

    def cause(self) -> str | None:
        if self._cause is None and self.now() >= self.deadline:
            self._cause = "deadline"
        return self._cause

    def requested(self) -> bool:
        return self._cause is not None or self.now() >= self.deadline

    def remaining(self, ceiling: float) -> float:
        return min(ceiling, max(0, self.deadline - self.now()))


class Heartbeat:
    def __init__(self, control: Control, period: float, *, stop: Stop) -> None:
        self.control = control
        self.run_stop = stop
        self.period = period
        self.proxy: EgressSession | None = None
        self.failed = threading.Event()
        self.stopping = threading.Event()
        self._worker = threading.Thread(target=self._run, name="science-heartbeat")

    def __enter__(self) -> Heartbeat:
        self._worker.start()
        return self

    def __exit__(self, *_exception) -> None:
        self.stop()
        self._worker.join()

    def stop(self) -> None:
        self.stopping.set()

    def _run(self) -> None:
        while not self.run_stop.requested():
            delay = min(self.run_stop.remaining(self.period), max(0, self.control.expires - time.monotonic()))
            if self.stopping.wait(delay) or self.run_stop.requested():
                return
            try:
                self.control.renew()
                proxy = self.proxy
                if proxy is not None and not self.stopping.is_set():
                    proxy.renew()
            except (EndpointError, OSError, EOFError):
                if not self.stopping.is_set():
                    self.failed.set()
                return


class _StopBeforeRelease(Exception):
    pass


def _check_gate(stop: Stop, endpoint: Endpoint, heartbeat: Heartbeat, proxy: EgressSession | None) -> None:
    if (cause := stop.cause()) is not None:
        raise _StopBeforeRelease(cause)
    if heartbeat.failed.is_set() or exited(endpoint.pidfd) or time.monotonic() >= endpoint.control.expires:
        raise EndpointError("endpoint lease or process lost before gate release")
    if proxy is not None and proxy.exited():
        raise EgressUnproven("proxy-unlistening", "proxy exited before gate release")


def _checked_heads(opening: Opening, run_dir: Path) -> None:
    try:
        opening.config.verify()
        after = opening.reader.heads(resolve=False)
        opening.config.verify()
    except ReadUnavailable as error:
        raise EndpointError(str(error), code="read-unavailable") from error
    table = {(chain.role, chain.chain_id): chain for chain in after.chains}
    world_changed = (after.world_genesis != opening.heads.world_genesis or after.world_head != opening.heads.world_head
                     or bool(after.world_pending))
    chains_changed = any(table.get((chain.role, chain.chain_id)) != chain for chain in opening.written)
    if world_changed or chains_changed:
        raced_tips = {}
        for chain in opening.written:
            observed = table.get((chain.role, chain.chain_id))
            if (observed is not None and (observed.root, observed.genesis) == (chain.root, chain.genesis)
                    and observed.tip != chain.tip):
                raced_tips[chain.chain_id] = observed.tip
        detail = "world changed" if world_changed else "written chain changed"
        append_event(run_dir, "baseline-raced", tips=raced_tips, detail=detail)
        raise EndpointError(f"{detail} before the endpoint took its claim", code="baseline-raced")


def _prove(opened: Opened, opening: Opening, endpoint: Endpoint, stop: Stop) -> tuple[SandboxSpec, tuple[Path, ...]]:
    scratch = opened.dirs.scratch
    home = scratch / "home"
    home.mkdir(mode=0o700)
    env = {
        "HOME": str(home), "LANG": "C.UTF-8", "VERIFIABLY_SCRATCH": str(scratch),
        "VERIFIABLY_ENDPOINT": str(IN_SANDBOX_SOCKET), "VERIFIABLY_TOKEN_FILE": str(IN_SANDBOX_TOKEN),
    }
    route = opened.route
    route_denied = all_egress_denied(opened.places.config)
    if route is not None:
        env["VERIFIABLY_MODEL_URL"] = MODEL_URL
        route_denied += egress_denied(opened.places.config, route)
        if route.route.ca_file is not None:
            route_denied += (route.route.ca_file,)
    denied = tuple(dict.fromkeys((
        *opening.config.denied, *(chain.root for chain in opening.heads.chains),
        opened.places.state.resolve(), *route_denied,
    )))
    spec = SandboxSpec(scratch=scratch, ro_binds=opening.toolchain, socket=endpoint.actor_socket,
                       token=endpoint.token, env=env)
    bwrap.preflight()
    check_binds(spec, denied)
    if route is not None:
        check_proxy(proxy_binds(route.route), denied)
    result = walk((scratch, *opening.toolchain), SYSTEM_RO, denied, until=stop.deadline)
    publish_json(opened.dirs.run_dir / "walk.json", result.to_json())
    bwrap.probe(spec, denied, timeout=stop.remaining(60))
    append_event(opened.dirs.run_dir, "proved", walk_seconds=result.seconds)
    return spec, denied


def _wait(actor: bwrap.Sandboxed, endpoint: Endpoint, proxy: EgressSession | None, stop: Stop,
          heartbeat: Heartbeat) -> str:
    poll = select.poll()
    poll.register(actor.pidfd, select.POLLIN)
    poll.register(endpoint.pidfd, select.POLLIN)
    if proxy is not None:
        poll.register(proxy.pidfd, select.POLLIN)
    while True:
        if (cause := stop.cause()) is not None:
            return cause
        if heartbeat.failed.is_set():
            return "renew-refused"
        ready = dict(poll.poll(int(stop.remaining(0.2) * 1000)))
        if endpoint.pidfd in ready:
            return "endpoint-exit"
        if proxy is not None and proxy.pidfd in ready:
            return "proxy-exit"
        if actor.pidfd in ready or actor.process.poll() is not None:
            return "actor-exit"


def _stop_actor(actor: bwrap.Sandboxed, run_dir: Path) -> None:
    try:
        if not exited(actor.pidfd):
            send_signal(actor.pidfd, signal.SIGTERM)
            if not exited(actor.pidfd, _TERM_GRACE):
                send_signal(actor.pidfd, signal.SIGKILL)
                if not exited(actor.pidfd, _CLOSE_MARGIN):
                    raise RuntimeError("actor namespace survived its shutdown")
        try:
            status = actor.wait(timeout=_CLOSE_MARGIN)
        except subprocess.TimeoutExpired:
            actor.process.kill()
            status = actor.wait(timeout=_CLOSE_MARGIN)
        append_event(run_dir, "actor-exit", status=status)
    finally:
        os.close(actor.pidfd)
        actor.pidfd = -1


def _seal(endpoint: Endpoint, run_dir: Path, written: tuple[ChainHead, ...]) -> tuple[Finding, ...]:
    deadline = time.monotonic() + endpoint.seal_timeout + _CLOSE_MARGIN
    code: str | None = None
    unacknowledged = False
    try:
        row = endpoint.control.seal(deadline)
        if row["type"] in ("seal-timeout", "seal-failed"):
            if set(row) != {"type", "version"}:
                raise EndpointError("malformed endpoint seal failure", code="seal-failed")
            code = row["type"]
        else:
            seal = check_seal({k: v for k, v in row.items() if k not in ("type", "version")}, written)
            append_event(run_dir, "sealed", seal=seal)
    except TimeoutError:
        code = "seal-timeout"
    except EndpointError:
        code = "seal-failed"
    except (EOFError, ConnectionError):
        # The journal and a file-only seal are inspected after confirming death.
        unacknowledged = True
    finally:
        try:
            if code is not None:
                append_event(run_dir, code)
        finally:
            remaining = max(0, deadline - time.monotonic())
            endpoint.close(grace=remaining if unacknowledged else min(_CLOSE_MARGIN, remaining))
    return () if code is None else (Finding(code, "endpoint", "the endpoint did not prove seal persistence"),)


def _close_proxy(proxy: EgressSession) -> tuple[Finding, ...]:
    deadline = time.monotonic() + CLOSE_TIMEOUT
    proxy.send_close()
    return proxy.wait_close(deadline).findings()


def finish(run_dir: Path, endpoint: Endpoint, proxy: EgressSession | None, actor: bwrap.Sandboxed | None,
           written: tuple[ChainHead, ...], cause: str) -> tuple[Finding, ...]:
    journal_error: BaseException | None = None
    try:
        append_event(run_dir, "close-start", cause=cause)
        append_event(run_dir, "seal-request")
    except BaseException as error:
        journal_error = error
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="science-close") as workers:
        sealing = workers.submit(_seal, endpoint, run_dir, written)
        egress = workers.submit(_close_proxy, proxy) if proxy is not None else None
        try:
            findings = sealing.result()
        finally:
            if actor is not None:
                _stop_actor(actor, run_dir)
        settled = egress.result() if egress is not None else ()
    if journal_error is not None:
        raise journal_error
    return findings + settled


def supervise(opened: Opened, opening: Opening, stop: Stop, env: Mapping[str, str], *,
              actor_launched: Callable[[Path], None]) -> tuple[Finding, ...]:
    if (cause := stop.cause()) is not None:
        return (Finding("run-stopped-before-release", "supervisor", cause),)
    launch = Launch(opened.dirs, opening.reader.executable, opening.config.path, opening.config.operations,
                    opened.request.tier.permit, opening.written, opened.request.lease, SEAL_TIMEOUT)
    run_dir = opened.dirs.run_dir
    try:
        opening.config.verify()
        endpoint = Endpoint.start(launch, env, timeout=stop.remaining(START_TIMEOUT))
    except (EndpointError, ReadUnavailable) as error:
        code = error.code if isinstance(error, EndpointError) else "endpoint-unavailable"
        return (Finding(code, "endpoint", str(error)),)
    actor = None
    proxy = None
    try:
        with Heartbeat(endpoint.control, opened.request.lease / 3, stop=stop) as heartbeat:
            findings: tuple[Finding, ...] = ()
            cause = "startup-failure"
            try:
                _checked_heads(opening, run_dir)
                _check_gate(stop, endpoint, heartbeat, None)
                spec, denied = _prove(opened, opening, endpoint, stop)
                _check_gate(stop, endpoint, heartbeat, None)
                if opened.route is not None:
                    proxy = EgressSession.start(opened.route, run_dir, lease=opened.request.lease, denied=denied)
                    heartbeat.proxy = proxy
                    proxy.renew()

                def bind(pid: int, pidfd: int) -> None:
                    _check_gate(stop, endpoint, heartbeat, proxy)
                    endpoint.bind(pid, pidfd)
                    if proxy is not None:
                        proxy.attach(pid, pidfd)
                    append_event(run_dir, "actor-releasing", **ProcessIdentity.capture(pid).fields())
                    _check_gate(stop, endpoint, heartbeat, proxy)

                actor = bwrap.launch(spec, opened.request.actor_argv, stdin=0, stdout=1, stderr=2,
                                     before_release=bind)
                actor_launched(run_dir)
                append_event(run_dir, "actor-launched", pid=actor.child_pid)
                cause = _wait(actor, endpoint, proxy, stop, heartbeat)
            except _StopBeforeRelease as error:
                cause = str(error)
                findings = (Finding("run-stopped-before-release", "supervisor", cause),)
            except EndpointError as error:
                findings = (Finding(error.code, "endpoint", str(error)),)
            except EgressUnproven as error:
                findings = (unproven(error),)
            except SandboxUnproven as error:
                findings = (Finding("sandbox-unproven", error.code, str(error)),)
            finally:
                heartbeat.stop()
                completion = finish(run_dir, endpoint, proxy, actor, opening.written, cause)
        return findings + completion
    finally:
        try:
            endpoint.close(grace=0)
        finally:
            try:
                if actor is not None and actor.pidfd >= 0:
                    _stop_actor(actor, run_dir)
            finally:
                if proxy is not None and proxy.pidfd >= 0:
                    proxy.kill()
