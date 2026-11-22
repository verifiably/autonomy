"""Science actor admission, supervision and recovery."""

from collections.abc import Callable, Mapping
from pathlib import Path

from autonomy.membership import Finding
from autonomy.run import Diag, Opened, Progress, RunRequest, RunResult, execute as run_reported
from autonomy.science_run._admission import Admission
from autonomy.science_run._recovery import collect, control
from autonomy.science_run._supervisor import Stop, supervise

__all__ = ["control", "execute"]


def execute(
    request: RunRequest, env: Mapping[str, str], *, diag: Diag, progress: Progress,
    actor_launched: Callable[[Path], None],
) -> int:
    with Stop(request.deadline) as stop:
        admission = Admission(request, env, until=stop.deadline, cancelled=stop.requested)

        def steps(opened: Opened) -> RunResult:
            opening = admission.capture(opened)
            if isinstance(opening, Finding):
                return RunResult((opening,), {}, None)
            findings = supervise(opened, opening, stop, env, actor_launched=actor_launched)
            return collect(opened.dirs.run_dir, env, findings)

        return run_reported(request, env, steps, diag=diag, progress=progress, open_run=admission.open)
