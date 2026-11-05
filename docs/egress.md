# Model Egress Proxy and Route Contract

Type: protocol, data model; document types 1. Currently unversioned.

The model egress proxy mediates all network communication between confined actor workloads and upstream model providers. The actor sandbox holds no raw network connectivity, while the proxy process enforces cryptographic, syntactic, and policy boundaries over outbound requests.

## Custody boundary

The egress boundary separates untrusted actor execution from operator credentials and upstream network access:
- **Actor Loopback Interface:** The actor sandbox is isolated in private user, mount, IPC, PID, network, and UTS namespaces possessing only a loopback device. It reaches model services strictly via `MODEL_URL = "http://127.0.0.1:4780"` using a static placeholder token (`"placeholder"`).
- **Proxy Sandbox Process:** The proxy executes as an independent bubblewrap container (`bwrap --unshare-all --share-net --new-session --clearenv`, omitting `--die-with-parent` so an orphaned proxy detects EOF on its control socket, completes accounting, and writes its closing record). Minimal mounts are restricted by `ProxyBinds` (`SYSTEM_RO`, `SYSTEM_LINKS`, and temporary runtime directories).
- **Credential Protection:** Operator credentials are read-only bind mounts at `/run/va/credential` (`IN_SANDBOX_CREDENTIAL`) and CA bundles at `/run/va/ca.pem` (`IN_SANDBOX_CA`). Denied set functions `egress_denied` and `all_egress_denied` in `python/src/autonomy/analyst/launch.py` ensure route configurations and credential files are unconditionally denied to the actor sandbox.
- **TLS Security:** Upstream communication enforces TLS 1.2 or higher (`ssl.TLSVersion.TLSv1_2`), disabling renegotiation (`OP_NO_RENEGOTIATION`) and TLS-level compression (`OP_NO_COMPRESSION`). Hostname verification is enabled with custom CA bundles when configured.

## Route configuration

Route definitions are loaded from TOML documents at `<config>/routes/<name>.toml`, where route names match `_ROUTE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")`. Schema parsing is implemented in `python/src/autonomy/egress/route.py`:

| Key | Type | Description |
| --- | --- | --- |
| `api` | String | Target API dialect; must be member of `DIALECTS = frozenset({"anthropic-messages"})`. |
| `upstream` | String | HTTPS origin `"https://<host>[:<port>]"`; scheme must be `"https"`, no userinfo, path `""` or `"/"`, no query or fragment. |
| `max_request_bytes` | Integer | Positive maximum byte limit for actor request bodies. |
| `forward_headers` | List of strings | Lowercase header tokens. Must not match `always_dropped(name)` (`ALWAYS_DROPPED = frozenset({"host", "connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "expect", "proxy-authorization", "authorization", "x-api-key", "cookie", "set-cookie", "content-length", "forwarded"})` or `x-forwarded-*`). |
| `header_tokens` | Table (optional) | Permitted tokens for headers in `FEATURE_HEADERS["anthropic-messages"] = frozenset({"anthropic-version", "anthropic-beta"})`. |
| `ca_file` | String (optional) | Absolute path to an existing regular CA certificate bundle. |
| `credential` | Table | Required keys `file` (absolute path to regular file owned by process UID, permissions `0o077` mask empty, `st_nlink == 1`, single line visible ASCII `[\x21-\x7e]+`) and `header` (`"x-api-key"` or `"authorization"`). |
| `operations` | List of tables | Declarations defining `method` (`"POST"`), `path` (`"/v1/messages"`), `models`, `fields`, `block_types`, and optional `queries` (defaults to `("",)`; admits `"beta=true"` when `"tools"` in `fields`), `tool_types` (`KNOWN_TOOL_TYPES = frozenset({"custom"})`), and `source_types` (`KNOWN_SOURCE_TYPES`). |

When `credential.header` is `"authorization"`, the proxy formats the header value as `Bearer <token>`; when `"x-api-key"`, it transmits the raw token bytes.

Valid configuration example:
```toml
api = "anthropic-messages"
upstream = "https://api.anthropic.com"
max_request_bytes = 1048576
forward_headers = ["anthropic-version", "anthropic-beta"]

[header_tokens]
anthropic-version = ["2023-06-01"]
anthropic-beta = ["fine-grained-previews-2025-01-01"]

[credential]
file = "/path/to/token.secret"
header = "x-api-key"

[[operations]]
method = "POST"
path = "/v1/messages"
models = ["claude-3-5-sonnet-20241022"]
fields = ["model", "messages", "max_tokens", "stream", "tools"]
tool_types = ["custom"]
block_types = ["text", "tool_use", "tool_result"]
```

Configurations are rejected (`RouteRefused`) if fields are missing, if `forward_headers` includes credentials or hop-by-hop tokens, or if credential files have group/world permissions or multiple hardlinks:
```toml
# REJECTED: credential headers cannot be forwarded by the actor
forward_headers = ["x-api-key", "authorization"]
```

## Closed anthropic-messages dialect

Body parsing and verification in `python/src/autonomy/egress/dialect.py` strictly restricts client payloads:
- `parse_body(data)`: Rejects UTF-8 byte-order marks (`\xef\xbb\xbf`), non-UTF-8 encodings, duplicate object keys (`_pairs`), non-standard JSON numbers (`NaN`, `Infinity`), lone surrogates (`_strings_encode`), non-object top-level JSON, or parser recursion exceeding limits (`Refused("request-malformed", ...)`).
- `check_body(body, op)`:
  - Requires `"model"`, `"messages"`, and `"max_tokens"`. All present top-level keys must be declared in `op.fields` from `KNOWN_FIELDS` (`model`, `messages`, `max_tokens`, `system`, `stream`, `tools`, `tool_choice`, `thinking`, `temperature`, `top_p`, `top_k`, `metadata`, `stop_sequences`, `output_config`).
  - `"model"` must be admitted by `op.models` (`Refused("model-refused", ...)`).
  - Validates scalar types: `"max_tokens"` (integer >= 1, not boolean), `"stream"` (boolean), `"temperature"` and `"top_p"` (numbers), `"top_k"` (integer >= 0), `"stop_sequences"` (list of strings).
  - Validates structures: `"metadata"` (optional `user_id`), `"output_config"` (optional `effort` in `"low"`, `"medium"`, `"high"`, `"xhigh"`, `"max"`, `None`), and `"thinking"` (budget tokens >= 1).
  - Validates blocks and sources: `"system"` (string or text blocks), `"tools"` (client definitions with name, description, schema, and `tool_types`), `"tool_choice"` (`"auto"`, `"any"`, `"tool"`, `"none"`), and `"messages"` (roles `"user"` / `"assistant"`, allowed `block_types` from `KNOWN_BLOCK_TYPES`, and allowed `source_types` from `KNOWN_SOURCE_TYPES`). Tool schema internals and tool input values are passed transparently without dialect validation. Unknown dialect elements raise `Refused("body-refused", ...)`.

## HTTP framing, headers, and allowance

Actor request processing in `python/src/autonomy/egress/request.py` and `python/src/autonomy/egress/server.py` enforces protocol framing:
- `parse_head(raw)`: Restricts request heads to `MAX_HEAD = 64 KiB` (65536 bytes). Enforces HTTP/1.1; rejects `CONNECT`, `Upgrade`, URI fragments, `Transfer-Encoding`, missing or duplicate `Content-Length`, obsolete line folding, or control characters (`request-malformed`, `target-refused`).
- `forwarded_headers(request, route)`: Filters client headers against `route.forward_headers`, strips hop-by-hop and `always_dropped` names, and validates header values against declared `route.header_tokens` (`Refused("header-refused", ...)`).
- `Allowance`:
  - `admit(run, operation, model, request_bytes, in_flight) -> str | None`: Evaluated before connecting upstream. A non-None return aborts the request (`Refused("allowance-refused", ...)`).
  - `settle(seq, upstream_request_id, usage) -> None`: Invoked in a `finally` block when streaming completes to record accounting and token usage.
  - Default implementation is `NoAllowance`, which permits all valid requests under the route.
- Responses: Upstream bodies stream to the actor with HTTP/1.1 `Transfer-Encoding: chunked`. The terminating chunk `0\r\n\r\n` is transmitted only if the full upstream response is received while `Gate.is_open`. Refusals return HTTP 403 (`egress_refused`) or HTTP 502 (`egress_upstream`) JSON payloads with explicit `Content-Length`.

## Proxy and namespace helper lifecycle

The proxy lifecycle coordinates four steps across an `AF_UNIX` `SOCK_SEQPACKET` control channel:
1. **Startup (`autonomy.egress.session`):** The supervisor launches `bwrap` running `proxy.main`, opens a `pidfd` on the child PID (`proxy-unstarted`), and sends route configuration:
   ```json
   {"op": "route", "route": "<base64>", "lease": 60.0, "run": "<run_id>"}
   ```
   The supervisor awaits `{"op": "ready"}` within `PROXY_START_TIMEOUT = 10.0` seconds (`proxy-unready`).
2. **Namespace Helper (`autonomy.egress.helper`):** `helper.make_listener` executes `/usr/bin/python3 -I` in the host namespace within `HELPER_TIMEOUT = 10.0` seconds. It opens the actor netns at `/proc/<child_pid>/ns/net`, verifies child liveness via `pidfd_send_signal(pidfd, 0)`, retrieves the owning user namespace with `ioctl(net, NS_GET_USERNS = 0xB701)`, calls `setns(owner, CLONE_NEWUSER)` then `setns(net, CLONE_NEWNET)`, binds `127.0.0.1:4780`, and passes the socket over `SCM_RIGHTS` (`listener-failed`).
3. **Attachment:** The supervisor passes the listener fd to the proxy via `{"op": "listener"}` over `SCM_RIGHTS` and awaits `{"op": "listening"}` within `LISTENING_TIMEOUT = 5.0` seconds (`proxy-unlistening`).
4. **Lease Renewal & Shutdown:** The supervisor transmits `{"op": "renew"}` periodically before lease expiry. At run completion, the supervisor sends `{"op": "close"}` and waits up to `CLOSE_TIMEOUT = 5.0` seconds. Inside the proxy, `ProxyServer.close` closes `upstream.Gate`, waking network loops (`POLL = 0.2` seconds, `SLICE = 16 KiB`), shuts tracked sockets (`SHUT_RDWR`), and appends the closing record to `<run_dir>/egress.jsonl`:
   ```json
   {"at": "2026-11-05T12:00:00Z", "closed": "close", "last_seq": 12}
   ```
   Unresponsive proxies are terminated via `kill_orphan` sending `SIGKILL` to `pidfd`.

## Failure

### Route Refusal Codes (Exit 2)

| Code | Meaning |
| --- | --- |
| `route-unknown` | Route name not found under `<config>/routes/`. |
| `route-invalid` | Route TOML missing required keys, invalid schema, or forbidden headers. |
| `credential-unavailable` | Credential file missing, invalid permissions, or multiple hardlinks. |

### Egress Unproven Codes (Exit 4)

| Code | Meaning |
| --- | --- |
| `proxy-bind-refused` | Proxy mounts overlap denied paths or ancestry. |
| `proxy-unstarted` | Bubblewrap failed to start or `pidfd_open` failed. |
| `proxy-unready` | Proxy failed to initialize or timed out awaiting route configuration. |
| `proxy-unlistening` | Proxy timed out or failed to accept listener descriptor. |
| `listener-failed` | Helper failed to enter namespace, bind loopback, or transfer descriptor. |
| `credential-invalid` | In-sandbox credential cannot be read or contains invalid data. |

### Actor HTTP 403 Egress Refusal Codes

| Refusal Code | Description |
| --- | --- |
| `request-malformed` | Invalid HTTP/1.1 syntax, invalid JSON, duplicate keys, or surrogates. |
| `request-too-large` | Request payload exceeds `max_request_bytes`. |
| `target-refused` | Unsupported HTTP method or path outside declared operations. |
| `operation-refused` | Target query string or endpoint options not permitted. |
| `header-refused` | Request headers not in `forward_headers` or feature tokens disallowed. |
| `model-refused` | Requested model not in operation `models` list. |
| `body-refused` | Payload fields, block types, tool types, or source types disallowed. |
| `allowance-refused` | `Allowance.admit` rejected request. |
| `route-closed` | Request attempted after route entered shutdown. |

HTTP 502 responses return error type `egress_upstream` when TCP connections, TLS handshakes, or upstream transfers fail. Closing findings record `egress-unproven`, `egress-lost`, `egress-close-timeout`, or `ProxySurvived` when a proxy process survives shutdown.
