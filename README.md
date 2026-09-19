# Crewmeister API

Community Python SDK, CLI and local MCP server under Apache-2.0, requiring Python 3.14 and managed with uv.
The base SDK has no runtime dependencies.
Optional CLI `.env` support is installed with `crewmeister-api[cli]`.
The local STDIO MCP adapter is installed with `crewmeister-api[mcp]`.

## Install from this checkout

```sh
uv sync --locked --dev --all-extras
uv run --no-sync crewmeister describe --json
uv build --no-sources --out-dir dist/sdk
```

In a consuming repository, install the reviewed local artifact with
`uv add /absolute/path/to/crewmeister_api-0.1.0-py3-none-any.whl`.
A public repository or package-registry release is not assumed by these instructions.
The API examples below require your own authorized Crewmeister access; only
`describe`, help, and version discovery are offline.

```python
from crewmeister_api import CrewmeisterApiClient, CrewmeisterApiConfig, PlatformApiService

client = CrewmeisterApiClient(CrewmeisterApiConfig.from_env())
members = PlatformApiService(client).list_resource("members", limit=10)
```

```sh
uv run crewmeister platform members list --limit 10
uv run python -m crewmeister_api platform members list --limit 10
```

For an agent-assisted operational task, read the compact
[`crewmeister-use` skill](.agents/skills/crewmeister-use/SKILL.md) first. It selects the
SDK, CLI, or MCP path and defines their output and write contracts.

### Offline operation catalog

`crewmeister describe --json` writes a deterministic category index without
configuration, login or network access. To inspect one resource or task, use
`crewmeister describe time-tracking durations --json`. The index includes the package
version, shared authentication operation, the nine MCP operation families and
the actual CLI pagination and output contract. A selected endpoint identifies its HTTP
method, path shape, required item ID or JSON payload, pagination, read/write effect and
MCP availability. Download entries are SDK/CLI-only and identify the metadata path and
binary reference used for their binary output.
The catalog is derived from the installed package's existing category registry; it does
not copy the audit matrix or assert unverified provider payload schemas or permissions.
Job reads are marked `contract: "live-verified"` for the confirmed report-task route,
otherwise `"guideline-derived"`. Both are separate from the 395 explicit OpenAPI operations.
The salary-generation batch route is additionally based on the provider's web client;
it is not part of that OpenAPI inventory.

```python
from crewmeister_api import describe_api

index = describe_api()
operations = describe_api("time-tracking", "durations")["operations"]
```

```sh
crewmeister platform members list --page 0
crewmeister platform teams create --json-file payload.json --yes
crewmeister platform teams batch --json-file payload.json --yes
crewmeister platform task subscription-action --json-file payload.json --yes
crewmeister platform teams create --json-file payload.json --yes --async
crewmeister platform teams job JOB_ID
crewmeister integration job i-cal-subscription JOB_ID
crewmeister integration task i-cal-subscription --json-file payload.json --yes --output-file ./calendar-feed.txt
crewmeister time-tracking time-tracking-reports download REPORT_ID --output-file ./report.xlsx
crewmeister salary-export salary-exports download EXPORT_ID --output-file ./salary-export.bin
```

The first command returns one redacted provider page. Most commands return
redacted JSON; `download` writes no stdout, while the iCal export retains its
redacted task result. Payload schemas and provider permissions are
operation-specific and are not inferred from the generic CRUD commands. Existing
SDK methods and CLI success responses do not retain an HTTP status; a response
is not by itself proof of a completed async or business operation.

`--async` adds `X-Write-Async: true` only to a confirmed write; the default remains
synchronous. The SDK exposes the same choice as `async_write=True` on shared write and
task methods. Job reads accept only registered resources or tasks. The report task uses
the verified `/api/v3/timetracking/time-tracking-report-task-jobs/<job-id>` path;
other paths follow the unverified guideline `<endpoint>-jobs/<job-id>` convention.
The CLI and SDK never poll or retry writes. A returned
job with `status: "ERROR"` exits the CLI with status 1 and yields MCP outcome `rejected`.
`WAITING` and `PROCESSING` yield MCP outcome `pending`, never a completion claim.
For a successful report job, `responses` is a list of `SyncWriteResponse` objects;
the report is at `responses[0].resourceAfterWrite.output.timeTrackingReport`.
Read it with `crewmeister time-tracking job time-tracking-report JOB_ID`.

The iCal `--output-file` option is available only on the iCal task. It creates a
new owner-only file before the request, never overwrites or follows an existing
target, and removes an incomplete file on failure. It writes only the documented
`resourceAfterWrite.output.feedURL`; standard JSON stays redacted. `--async`
cannot be combined with the output option. The CLI never opens or subscribes to
the URL. Job output remains unavailable until its documented `responses` shape
is confirmed.

The CLI `download` commands reserve a new owner-only file, read the selected
resource metadata and use only its relative `/api/v3/...`
`binaryContentReference`. They stream without overwriting an existing path,
reject redirects and foreign origins before the download request, and remove
incomplete output. The SDK writes to its caller-provided binary stream. JSON and
HTML Content-Type success bodies are rejected as files; stdout never receives
the reference or binary content. One explicitly authorized Time-Tracking-Report
download was verified; Salary-Export availability still depends on a separately
verified resource.

For an adapter that needs a successful HTTP status, use
`client.request_with_response(...)`; existing SDK methods keep returning their raw
payload. Prefix a command with `--error-format json` for a redacted structured error on
stderr. Neither form proves a completed async or business operation.

Set `CREWMEISTER_API_BEARER_TOKEN` or `CREWMEISTER_API_USERNAME` and `CREWMEISTER_API_PASSWORD`.
Configuration may also be passed explicitly to `CrewmeisterApiConfig`; the SDK
does not load repository files or modify the environment. The default endpoint
is the staging API; configure `CREWMEISTER_API_BASE_URL` for your intended environment.
Write commands require `--yes`. CLI responses redact known sensitive fields,
including normalized `pincode` keys. Exact `accessTokenExpiresAt` and
`refreshTokenExpiresAt` fields remain visible. Known `resourceBefore` and
`resourceAfter` audit JSON strings are decoded, recursively redacted and returned
as strings; unreadable or excessively nested snapshots are replaced with
`[REDACTED]`. Feed URLs inside audit snapshots are also protected. Other strings
are not parsed. SDK responses remain raw and must be handled as sensitive data.

### Scoped salary generation

`salary-export-generation-tasks` supports the web client's synchronous PATCH batch
through the existing resource interface. Supply an existing export configuration and
an explicit, non-empty `userIdFilter` of user IDs. This synthetic `salary-generation.json`
example must be adapted to the authorized crew, configuration, user and month:

```json
[
  {
    "method": "POST",
    "path": "/",
    "body": {
      "input": {
        "crewId": 24,
        "salaryExportConfigurationId": 1,
        "from": "2026-08-01",
        "to": "2026-08-31",
        "userIdFilter": [7]
      }
    }
  }
]
```

```sh
crewmeister --env-file .env salary-export salary-export-generation-tasks batch --json-file salary-generation.json --yes
```

The SDK uses `SalaryExportApiService.batch_patch_resource("salary-export-generation-tasks", payload)`;
MCP uses `crewmeister_batch` with category `salary-export`, that resource, the same
payload and `confirm=true`. All pass the payload unchanged; no configuration is created
and no user restriction is inferred or enforced locally. Check the individual batch
response's `statusCode` and the result at
`[0].body.resourceAfterWrite.output.salaryExport` before using its ID with the existing
`salary-exports download` command. CLI success alone does not prove business success
or the exported file's person scope.

CLI and MCP preserve a batch `body` with the documented
`@type: "com.crewmeister/SyncWriteResponse"` when its parent has an integer
`statusCode`. Its fields are redacted recursively, including file references and
tokens. Token bodies, error bodies and unrecognized body shapes remain masked.
The SDK continues to return the provider payload unchanged.

This route is verified against the provider's web client and offline transports.
A live salary file remains unverified because no export configuration was visible
under the authorized account. Direct POST, async generation and the automatically
listed guideline-derived job route have not been verified; use the synchronous batch.
The separate DATEV upload operation is not part of this flow.

### Explicit CLI environment files

Install the CLI extra from the locally built wheel:

```sh
uv tool install "./dist/sdk/crewmeister_api-0.1.0-py3-none-any.whl[cli]"
```

For development, the setup above installs all extras; use
`uv run --no-sync crewmeister --env-file .env ...`.
The installed command works directly:

```sh
crewmeister --env-file .env time-tracking durations list \
  --filter 'crewId==24;date>=2026-08-01;date<2026-09-01'
```

Place the global `--env-file PATH` option before the category. Relative paths
resolve from the current working directory; no parent-directory search or
implicit `.env` loading occurs. Existing environment variables take precedence
over file values, then configuration defaults apply. Empty environment values
also override file values and retain the existing configuration semantics.

Files use UTF-8 and python-dotenv quoting/comment syntax. Variable interpolation
is disabled: `${NAME}` remains literal. Bare keys without `=` are ignored.
The CLI builds a local configuration mapping and does not change `os.environ`.
The SDK never loads files implicitly. Missing/unreadable specified files fail
before API access; `--help` and `--version` need neither the file nor the extra.
Without the extra, `--env-file` reports the required `crewmeister-api[cli]`
installation. Without this option, the base CLI keeps using environment variables.

### Local MCP server

Install the MCP extra from the approved package source:

```sh
uv tool install "./dist/sdk/crewmeister_api-0.1.0-py3-none-any.whl[mcp]"
crewmeister-mcp --env-file /absolute/path/to/.env
```

The server uses STDIO only and exposes `crewmeister_describe` plus the nine fixed
operation tools `crewmeister_list`, `crewmeister_get`, `crewmeister_create`,
`crewmeister_batch`, `crewmeister_patch`, `crewmeister_replace`,
`crewmeister_delete`, `crewmeister_task` and `crewmeister_job`. They cover every
registered operation with an MCP family. Binary download entries have no MCP family and
use the SDK or CLI. Tool inputs select a registered category and resource or task;
they cannot supply an arbitrary URL or HTTP method. List accepts one page with
`query`, `page` and `page_size`; item operations use `item_id`; write and task
operations use a JSON `payload`. Writes and tasks accept `async_write=true`; job reads
take a registered `kind`, `endpoint` and `job_id`.

`CREWMEISTER_API_BASE_URL` is mandatory for this entry point and must be one
canonical HTTPS origin without a path, query, fragment or credentials. The server
reads its configuration once at startup. `--env-file` has the same precedence and
does not modify `os.environ`; installing either optional extra supplies its parser.
Startup and tool discovery never authenticate. The first API tool call uses the
existing bearer token or performs the configured username/password login, then reuses
that client token. Successful tool results contain redacted `status` and `payload`;
known API, configuration and transport errors return a redacted `error` object.
Every write and task also requires `confirm=true`; this records the requested write
without replacing the MCP host's authorization. Successful writes are `completed`,
or `accepted` for HTTP 202. A rejected provider response is `rejected`; an input
or authentication failure is `not_sent`; a transport failure is `unknown`.
Unknown results are never retried or rolled back automatically.

The default transport rejects HTTP redirects without following them. Configure
the canonical HTTPS endpoint. Injected transports are responsible for their own
network security and must not forward credentials through redirects.

Build the consumer plugin from this checkout with
`uv run --no-sync python scripts/build_plugin.py`.
The output is `dist/plugins/crewmeister`; existing output is never overwritten.
For another build, choose a new `--output-dir`. Its MCP configuration starts `crewmeister-mcp` with an
expected package version, so an installed mismatch fails before configuration or API
access. The bundle contains only the consumer skill, manifests, license and onboarding;
it never contains environment values or an `.env` file. Its portable `mcp.json`
and Codex overlay share the same STDIO start contract; the overlay adds variable names.
It is not a marketplace entry or a compatibility statement for other hosts.

To export the plugin after its containerized offline checks:

```sh
docker build --target plugin-artifacts --output type=local,dest=dist/plugins .
```

This repository's original code, tests, build scripts, configuration, and
companion skill are released under [Apache-2.0](LICENSE); see [NOTICE](NOTICE).
The [DCO](DCO) retains its own copying terms, and third-party material retains
its applicable license. No other repository or its history is included.

### Docker runtime

```sh
docker build -t crewmeister-api:runtime .
docker run --rm -i --env-file .env crewmeister-api:runtime
```

The default entry point is the local STDIO MCP server, running as a non-root user.
Keep stdin open with `-i`; do not allocate a TTY or publish ports.
The environment file remains on the host and must never be copied into the image.
For an offline CLI check, override the entry point:

```sh
docker run --rm --network none --entrypoint crewmeister crewmeister-api:runtime describe --json
```

### SDK contracts

All SDK failures derive from `CrewmeisterError`. Existing configuration errors
remain `ValueError`s; transport and API errors remain `RuntimeError`s.
`CrewmeisterApiError` exposes `status_code`, `payload`, and a copied `headers`
dictionary (including `Retry-After` if supplied). Request IDs come from the
API's documented error payload; no undocumented header name is assumed.
Unreadable error bodies retain their HTTP status with `payload=None`.
The client closes every received response, including errors. Error messages do
not dump response bodies or headers; inspect them only in controlled code.

The supported Python surface is the client, configuration, `CrewmeisterApiResponse`,
exported category services and errors, plus `JsonValue`, `JsonObject`, `QueryValue`,
`HttpResponse` and `Transport`. JSON payloads remain ordinary dictionaries, lists and scalars;
these types do not validate complete endpoint schemas. A custom transport takes
an urllib `Request` and timeout in seconds and returns a response with `status`,
`headers` (a mapping or email `Message`), `read([size]) -> bytes`, and `close() -> None`.
Status must contain a valid HTTP status for a usable response. Legacy duck-typed
responses with only `code`/`getcode()` must provide `status` and `headers` now.
Registries and CLI parser helpers are internal implementation details.

A client caches its bearer token. It does not refresh expired tokens, retry
requests, or promise thread safety. Create a new client with updated explicit
configuration when credentials change. The wheel includes `py.typed`; check SDK
types with `uv run --no-sync mypy src` from this checkout. mypy is
a development tool only, using the existing uv dev group.

For lazy SDK reads, use `service.iter_resource(...)`. `list_resource(...)` is a
convenience that materializes the same iterator. `limit=0` makes no API request.
For one page, use `service.get_resource_page("members", page=2, page_size=10)`.
It performs one GET and returns the raw response, including metadata; it does not
follow continuation fields or invent missing metadata. CLI equivalent:
`crewmeister platform members list --page 2 --page-size 10`. Only explicit
`--page` changes the output to a redacted Page object; the default remains the
streamed array. Page numbers start at zero. `--page` cannot be combined with
`--limit`. List queries reserve `page` and `pageSize`; use the dedicated SDK
arguments/CLI options. CLI option conflicts fail before creating the client.
The iterator requires valid `hasNextPage` or `totalPages` metadata before it yields
a page, rejecting missing or contradictory continuation information.

CLI lists stream one redacted JSON array, retaining only the current page and
record being serialized. A first-page failure leaves stdout empty. A later
failure leaves an incomplete array, reports the error on stderr and exits 1.
Consumers must check the exit status before accepting an export as complete.

Run `crewmeister --help`, `crewmeister platform --help`, or
`crewmeister platform members --help` to discover supported commands without
credentials. Task groups and operations also support `--help`. No arguments show
root help and exit 0. `crewmeister --version` uses the installed SDK distribution
version. Success and help use stdout/0; syntax errors use stderr/2; SDK and I/O
failures use stderr/1. `--yes` is checked before reading write payloads or creating
a client.

## License, maintenance and distribution

The confirmed and tested runtime is CPython 3.14. The metadata requires Python
3.14 or newer; newer versions are not yet validated or promised supported.
SDK and CLI version both come from the package metadata. Keep consumer version
pins in the consuming project's uv lockfile. Installation from a reviewed local
wheel, as shown above, requires no registry credentials.

Copyright 2026 BelStark. [BelStark](https://github.com/BelStark) is the primary
maintainer and decides which contributions and official releases are accepted.
Contributions are welcome under the [contribution terms and DCO](CONTRIBUTING.md).
Contributors retain their copyright. Forks and commercial use are permitted
subject to Apache-2.0; contributing does not grant repository write access.

This is an independent community client, not an official Crewmeister product.
The software license does not grant access to Crewmeister services, credentials,
customer data or trademarks. Third-party dependencies retain their own licenses.

The software is provided as described in Apache-2.0 sections 7 and 8, subject to
applicable law. No additional warranty, support response time or maintenance
period is promised. Known API limitations above remain; this is not a guarantee
of correct payroll, business outcomes or suitability for a particular deployment.

Remote repository creation, registry ownership and an installable public release
remain separate publication steps. Keep registry credentials in uv authentication
or environment variables, never pyproject.toml.

## Changes in 0.1.0

SDK and CLI share one distribution. Imports move to `crewmeister_api`, and the
standalone CLI starts with the category. Redirects fail; response errors share
a closed-response lifecycle and typed exceptions. JSON types are exported.
Lists stream and validate continuation metadata; consumers must check exit codes
before accepting an export. Root and nested help and package version are available.

## Artifact verification

The GitHub Actions `sdk-package` job checks SDK types, builds an sdist and a wheel from
that sdist, then installs only the wheel into a temporary CPython 3.14 environment
outside the checkout. It runs the existing SDK tests, verifies package contents,
entry points, version, Apache-2.0 metadata and bundled LICENSE/NOTICE, and
type-checks a small installed-package consumer.
Artifacts are retained under `dist/sdk`; the job does not publish to a registry.
The quality job also verifies the generated plugin; the artifact job exports it separately.
CI and Docker use uv 0.11.8; the SDK build backend is pinned to Hatchling 1.32.0.

### Mandatory offline validation

Run `docker build --target test -t crewmeister-api:test .` for lint, formatting,
types, all unit tests, the real STDIO MCP handshake, and plugin generation. Run
`docker build --target sdk-artifacts --output type=local,dest=dist/sdk .` for
build, typing and installed-wheel checks outside the source checkout.
Dependencies are prepared first; test commands run with `RUN --network=none`
and `uv run --no-sync`. A quick local test is
`uv run --no-sync python -m unittest discover -s tests -p "test_*.py"`,
but the network-isolated Docker tests are the acceptance path. Do not pass environment files, Crewmeister
credentials, host sockets or host networking. Tests use synthetic fake transports;
no Crewmeister login, GET or mutation is permitted, including on stage.
No additional environment variables or services are needed.

### Known API limitations

`delete ID --yes` takes no JSON file. Synthetic tests prove transport and CLI
behavior; they do not certify all server payloads, task envelopes, permissions,
or business transitions. Most job routes remain guideline-derived. Complete iCal
job output, Salary-Export file availability, and unverified async flows must not
be treated as confirmed contracts. Stage is not a confirmed isolated sandbox.

`tests/fixtures/api-operations.csv` is a frozen reference of 395 distinct
method/path pairs from the original V3 OpenAPI audit. It is intentionally
independent of the runtime catalog; the catalog test fails if it is missing.
It does not establish vendor permission or correctness of every payload schema.
