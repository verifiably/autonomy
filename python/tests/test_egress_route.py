import copy
import hashlib
import os
from pathlib import Path

import pytest

from egress_fixtures import pi_route, to_toml, write_credential, write_route
from autonomy.egress.errors import RouteRefused
from autonomy.egress.route import (
    always_dropped, check_credential, egress_denied, load_route, parse_route,
)


@pytest.fixture
def config(tmp_path):
    return tmp_path / "config"


@pytest.fixture
def credential(config):
    return write_credential(config / "credentials" / "anthropic")


def parse(doc: dict):
    return parse_route(to_toml(doc).encode())


def test_the_pi_route_parses(credential):
    route = parse(pi_route(credential=credential))
    assert route.api == "anthropic-messages"
    assert (route.host, route.port, route.upstream, route.authority) == (
        "api.anthropic.com", 443, "https://api.anthropic.com", "api.anthropic.com",
    )
    op = route.operation("POST", "/v1/messages", "beta=true")
    assert op is not None and op.models == {"claude-haiku-5-5"}
    assert route.operation("POST", "/v1/messages", "") is None
    assert route.operation("GET", "/v1/messages", "beta=true") is None
    assert route.header_tokens["anthropic-version"] == {"2023-06-01"}
    assert route.credential_header == "x-api-key"
    assert route.describe() == "POST /v1/messages?beta=true"


def test_a_port_shows_in_the_origin_and_authority(credential):
    route = parse(pi_route(credential=credential, upstream="https://localhost:8443"))
    assert (route.upstream, route.authority) == ("https://localhost:8443", "localhost:8443")


def _without(key):
    def change(doc):
        del doc[key]
    return change


def _op(**fields):
    def change(doc):
        doc["operations"][0].update(fields)
    return change


def _set(**fields):
    def change(doc):
        doc.update(fields)
    return change


INVALID = {
    "unknown dialect": _set(api="openai-chat"),
    "a dialect that is not a string": _set(api=["anthropic-messages"]),
    "an unmatched IPv6 bracket": _set(upstream="https://[::1"),
    "a port out of range": _set(upstream="https://api.anthropic.com:99999"),
    "a credential path with NUL": lambda doc: doc["credential"].update({"file": "/home/u/cred\x00x"}),
    "http upstream": _set(upstream="http://api.anthropic.com"),
    "upstream with a path": _set(upstream="https://api.anthropic.com/v1"),
    "upstream with userinfo": _set(upstream="https://u:p@api.anthropic.com"),
    "upstream with a query": _set(upstream="https://api.anthropic.com?x=1"),
    "no operations": _set(operations=[]),
    "operation without models": _op(models=[]),
    "operation without fields": _op(fields=[]),
    "fields without model": _op(fields=["messages"]),
    "operation without block types": _op(block_types=[]),
    "an undefined block type": _op(block_types=["text", "search_result"]),
    "an undefined source type": _op(source_types=["base64", "s3"]),
    "a lower-case method": _op(method="post"),
    "a path without a slash": _op(path="v1/messages"),
    "a path with a query": _op(path="/v1/messages?beta=true"),
    "forwarding x-api-key": _set(forward_headers=["x-api-key"]),
    "forwarding Transfer-Encoding": _set(forward_headers=["Transfer-Encoding"]),
    "forwarding an x-forwarded header": _set(forward_headers=["X-Forwarded-Host"]),
    "forwarding a header twice by case": _set(forward_headers=["accept", "Accept"]),
    "a beta header without tokens": lambda doc: doc["header_tokens"].pop("anthropic-beta"),
    "tokens for an unforwarded header": lambda doc: doc["header_tokens"].update({"x-probe": ["a"]}),
    "an empty token list": lambda doc: doc["header_tokens"].update({"anthropic-beta": []}),
    "an unknown top-level key": _set(timeout=5),
    "an unknown operation key": _op(cost=1),
    "a credential header outside the two": lambda doc: doc["credential"].update({"header": "cookie"}),
    "a relative credential path": lambda doc: doc["credential"].update({"file": "credentials/anthropic"}),
    "a relative ca_file": _set(ca_file="ca.pem"),
    "a zero body limit": _set(max_request_bytes=0),
    "a boolean body limit": _set(max_request_bytes=True),
    "a missing credential table": _without("credential"),
    "a repeated operation": lambda doc: doc["operations"].append(copy.deepcopy(doc["operations"][0])),
}


@pytest.mark.parametrize("case", sorted(INVALID))
def test_an_invalid_route_is_refused(case, credential):
    doc = pi_route(credential=credential)
    INVALID[case](doc)
    with pytest.raises(RouteRefused) as caught:
        parse(doc)
    assert caught.value.code == "route-invalid"


def test_bytes_that_are_not_toml_are_invalid():
    with pytest.raises(RouteRefused) as caught:
        parse_route(b"api = \n")
    assert caught.value.code == "route-invalid"


@pytest.mark.parametrize("name", ["Host", "x-forwarded-for", "SET-COOKIE", "Connection", "expect"])
def test_always_dropped_ignores_case(name):
    assert always_dropped(name)


def test_load_route_reads_digests_and_checks_the_credential(config, credential):
    path = write_route(config, "anthropic", pi_route(credential=credential))
    loaded = load_route(config, "anthropic")
    assert loaded.name == "anthropic"
    assert loaded.path == path.resolve()
    assert loaded.data == path.read_bytes()
    assert loaded.digest == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("name", ["missing", "../anthropic", "Anthropic", ""])
def test_an_unknown_route_name(config, credential, name):
    write_route(config, "anthropic", pi_route(credential=credential))
    with pytest.raises(RouteRefused) as caught:
        load_route(config, name)
    assert caught.value.code == "route-unknown"


def _refused(path: Path) -> str:
    with pytest.raises(RouteRefused) as caught:
        check_credential(path)
    assert caught.value.code == "credential-unavailable"
    return caught.value.message


def test_a_missing_credential(tmp_path):
    assert "missing" in _refused(tmp_path / "nope")


def test_a_directory_credential(tmp_path):
    assert "not a regular file" in _refused(tmp_path)


def test_a_symlinked_credential(tmp_path, credential):
    link = tmp_path / "link"
    link.symlink_to(credential)
    assert "symlink" in _refused(link)


def test_a_group_readable_credential(credential):
    os.chmod(credential, 0o640)
    assert "group or other" in _refused(credential)


def test_a_hard_linked_credential(tmp_path, credential):
    os.link(credential, tmp_path / "second-name")
    assert "2 links" in _refused(credential)


def test_a_credential_owned_by_someone_else():
    assert "owned by uid 0" in _refused(Path("/etc/passwd"))


def test_a_route_whose_credential_fails_is_refused_at_load(config, credential):
    os.chmod(credential, 0o644)
    write_route(config, "anthropic", pi_route(credential=credential))
    with pytest.raises(RouteRefused) as caught:
        load_route(config, "anthropic")
    assert caught.value.code == "credential-unavailable"


def test_the_denied_entries(config, credential):
    write_route(config, "anthropic", pi_route(credential=credential))
    loaded = load_route(config, "anthropic")
    assert egress_denied(config, loaded) == (
        config.resolve(), loaded.path, credential.resolve(),
    )


def test_a_toolchain_bind_holding_the_credential_fails_the_static_check(config, credential):  # E22
    from autonomy.sandbox.spec import SandboxSpec
    from autonomy.sandbox.static import SandboxUnproven, check_binds

    write_route(config, "anthropic", pi_route(credential=credential))
    loaded = load_route(config, "anthropic")
    scratch = config.parent / "scratch"
    scratch.mkdir()
    with pytest.raises(SandboxUnproven) as caught:
        check_binds(SandboxSpec(scratch=scratch, ro_binds=(credential.parent,)), egress_denied(config, loaded))
    assert caught.value.code == "bind-overlaps-denied"
