import importlib.util
from pathlib import Path

import pytest

from autonomy.egress.session import EgressClosed

SCRIPT = Path(__file__).parent.parent / "scripts" / "egress_live.py"
spec = importlib.util.spec_from_file_location("egress_live", SCRIPT)
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)

LINE = {"seq": 1, "status": 200, "ended": "complete", "refused": None}
CLOSED = EgressClosed("close", 1, False)


def answered(stop="stop", error=None, text="ok"):
    message = {"role": "assistant", "stopReason": stop, "content": [{"type": "text", "text": text}]}
    if error:
        message["errorMessage"] = error
    return [{"type": "message_end", "message": message}, {"type": "agent_settled", "aborted": False}]


def test_an_answer_passes():
    assert live.verdict([LINE], answered(), 0, CLOSED) == []


@pytest.mark.parametrize(("lines", "records", "exit_code", "closed", "reason"), [
    ([LINE], answered(stop="error", error="overloaded_error"), 0, CLOSED, "stopped 'error'"),
    ([LINE], answered(stop="length"), 0, CLOSED, "stopped 'length'"),
    ([LINE], answered(error="overloaded_error"), 0, CLOSED, "overloaded_error"),
    ([LINE], answered(text=""), 0, CLOSED, "no text"),
    ([LINE], answered()[:1], 0, CLOSED, "never settled"),
    ([LINE], [{"type": "agent_settled", "aborted": True}], 0, CLOSED, "aborted"),
    ([LINE], answered(), 1, CLOSED, "exited 1"),
    ([LINE], answered(), 0, EgressClosed(None, None, False), "egress-lost"),
    ([LINE], answered(), 0, EgressClosed(None, None, True), "egress-close-timeout"),
    ([{**LINE, "status": 403, "refused": "header-refused"}], answered(), 0, CLOSED, "header-refused"),
    ([{**LINE, "ended": "upstream-error"}], answered(), 0, CLOSED, "upstream-error"),
])
def test_each_failure_is_reported(lines, records, exit_code, closed, reason):
    problems = live.verdict(lines, records, exit_code, closed)
    assert problems and any(reason in problem for problem in problems)
