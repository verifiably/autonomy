"""The egress refusals (envelope design decision 13), one shape for each audience."""

from __future__ import annotations


class _Coded(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class RouteRefused(_Coded):
    """Step 2: the model route or its credential file cannot be used
    (`route-unknown`, `route-invalid`, `credential-unavailable`). The run exits 2."""


class EgressUnproven(_Coded):
    """The proxy or its listener could not be established or proven. The run is
    `unwired` (`egress-unproven`, with this code as its ref), and the actor is never
    released."""


class Refused(_Coded):
    """A request the proxy refuses, answered `403` with this code."""
