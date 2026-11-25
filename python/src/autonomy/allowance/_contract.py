"""Closed fields and integer units of a host allowance."""
import hashlib
import json
import re
import uuid

DIMENSIONS = ("attempts", "input_tokens", "output_tokens", "micro_usd", "job_starts")
MAXIMUM = 2**53 - 1


class AllowanceRefused(Exception):
    def __init__(self, code, message, **data):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.data = data


def require(condition, message, code="allowance-scope"):
    if not condition:
        raise AllowanceRefused(code, message)


def keys(value, fields):
    require(type(value) is dict and set(value) == set(fields), "incorrect fields")


def integer(value, minimum=0):
    require(type(value) is int and minimum <= value <= MAXIMUM, "count outside integer bounds")
    return value


def opaque(value):
    require(type(value) is str and re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value), "invalid identifier")
    return value


def hexadecimal(value, width):
    require(type(value) is str and re.fullmatch(f"[0-9a-f]{{{width}}}", value), "invalid hexadecimal identifier")
    return value


def uid(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f-]{36}", value), "invalid UUID")
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise AllowanceRefused("allowance-scope", "invalid UUID") from None
    require(str(parsed) == value, "invalid UUID")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def limits(value):
    keys(value, DIMENSIONS)
    for count in value.values():
        integer(count)
    return value


def definition(value):
    keys(value, ("campaign_id", "source", "expires", "members", "limits", "tariff"))
    opaque(value["campaign_id"])
    require(isinstance(value["source"], str) and value["source"], "missing grant source")
    integer(value["expires"], 1)
    limits(value["limits"])
    tariff = value["tariff"]
    keys(tariff, ("model", "billing_mode", "context", "output_cap", "max_input_micro_usd_per_mtok",
                  "output_micro_usd_per_mtok", "rates_micro_usd_per_mtok"))
    for field in ("model", "billing_mode"):
        require(type(tariff[field]) is str and tariff[field], "missing tariff identity")
    for field in ("context", "output_cap", "max_input_micro_usd_per_mtok", "output_micro_usd_per_mtok"):
        integer(tariff[field], 1)
    rates = tariff["rates_micro_usd_per_mtok"]
    keys(rates, ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h"))
    for kind, rate in rates.items():
        ceiling = tariff["output_micro_usd_per_mtok"] if kind == "output" else tariff["max_input_micro_usd_per_mtok"]
        require(integer(rate) <= ceiling, "actual rate exceeds conservative reservation rate", "allowance-unpriced")
    require(type(value["members"]) is dict and value["members"], "missing grant members")
    for name, row in value["members"].items():
        opaque(name)
        keys(row, ("caller", "target", "route_digest", "limits"))
        require(row["caller"] in ("band", "analyst", "e21", "run"), "unknown grant caller")
        require(type(row["target"]) is dict, "invalid member target")
        hexadecimal(row["route_digest"], 64)
        limits(row["limits"])


def ticket(role, args):
    if role == "model":
        return str(integer(args.get("seq"), 1))
    require(role == "job", "invalid peer role")
    invocation = opaque(args.get("invocation_id"))
    phase = args.get("phase")
    require(phase in ("original", "replay"), "invalid job phase")
    return f"{invocation}/{phase}"


def debit(role, args, tariff):
    result = dict.fromkeys(DIMENSIONS, 0)
    if role == "job":
        keys(args, ("invocation_id", "phase"))
        result["job_starts"] = 1
    else:
        keys(args, ("seq", "model", "max_tokens", "billing_mode"))
        require((args["model"], args["billing_mode"]) == (tariff["model"], tariff["billing_mode"]),
                "unsupported model or billing mode", "allowance-unpriced")
        output = integer(args["max_tokens"], 1)
        require(output <= tariff["output_cap"], "max_tokens exceeds per-attempt cap", "body-refused")
        numerator = tariff["context"] * tariff["max_input_micro_usd_per_mtok"] + output * tariff["output_micro_usd_per_mtok"]
        result.update(attempts=1, input_tokens=tariff["context"], output_tokens=output,
                      micro_usd=integer((numerator + 999999) // 1000000))
    return result


def validate_report(report):
    keys(report, ("version", "provider_session_id", "settlement", "question_id", "answer_id", "submission_id", "responses"))
    require(report["version"] == "band-turn.v1" and report["settlement"] in
            (None, "accepted", "replayed", "already-settled", "unknown"), "invalid turn report")
    uid(report["provider_session_id"])
    for field in ("question_id", "answer_id"):
        if report[field] is not None:
            uid(report[field])
    if report["submission_id"] is not None:
        integer(report["submission_id"])
    require(type(report["responses"]) is list, "missing response list")
    for row in report["responses"]:
        keys(row, ("conversationId", "submissionId", "responseId", "usage"))
        integer(row["conversationId"])
        integer(row["submissionId"])
        require(isinstance(row["responseId"], str) and row["responseId"], "missing response ID")
        if row["usage"] is not None:
            keys(row["usage"], ("input", "output", "cacheRead", "cacheWrite"))
            for count in row["usage"].values():
                integer(count)
