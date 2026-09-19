# Crewmeister API

Community Python SDK, CLI and local MCP server for the Crewmeister API.
Independent project, not an official Crewmeister product. Apache-2.0 licensed.

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/); tested on CPython 3.14.
The base SDK has no runtime dependencies. Optional extras add CLI `.env` support
(`cli`) and the STDIO MCP server (`mcp`).

## Supported areas

Platform, time tracking, absence, shift planning, salary export, integration,
audit and notifications. Available reads, writes, batches, tasks and jobs are
listed in the offline catalog; binary downloads use the SDK or CLI.

[Detailed usage](docs/usage.md) · [Agent skill](.agents/skills/crewmeister-use/SKILL.md) ·
[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

## Quick start

Clone and install the checkout, then inspect the catalog without credentials:

```sh
git clone https://github.com/BelStark/crewmeister-api-python.git
cd crewmeister-api-python
uv sync --locked --dev --all-extras
uv run --no-sync crewmeister describe --json
cp .env.template .env
```

Edit `.env`: explicitly choose `CREWMEISTER_API_BASE_URL` and enable either
`CREWMEISTER_API_BEARER_TOKEN` **or** `CREWMEISTER_API_USERNAME` plus
`CREWMEISTER_API_PASSWORD`. The template points to stage, which is **not an
isolated sandbox**. Keep credentials and employee data out of Git.

The examples below make real requests using your own authorized Crewmeister
access. Only catalog, help and version commands are offline. Configuration files
are loaded only when explicitly requested; process environment variables take
precedence. See [configuration and installation options](docs/usage.md#configuration).

### CLI

Read one page of members:

```sh
uv run --no-sync crewmeister --env-file .env platform members list --page 0 --page-size 10
```

For every operation, inspect its requirements and command options first:

```sh
uv run --no-sync crewmeister describe time-tracking durations --json
uv run --no-sync crewmeister time-tracking durations list --help
```

`describe` includes routes, filters, payload schemas, constraints and contract
evidence. Use documented fields; do not infer missing schemas.
Explicit `--page` returns one page; ordinary lists stream an array.
Check the exit code before accepting output as complete.

### Python SDK

With the extras installed above, explicitly load the same `.env`:

```python
from crewmeister_api import CrewmeisterApiClient, CrewmeisterApiConfig, PlatformApiService
from crewmeister_api.configuration import load_env_file

config = CrewmeisterApiConfig.from_env(load_env_file(".env"))
client = CrewmeisterApiClient(config)
members = PlatformApiService(client).get_resource_page("members", page=0, page_size=10)
```

For process environment variables only, use `CrewmeisterApiConfig.from_env()`;
this needs no extra. SDK responses are raw and may contain sensitive data.
See [SDK contracts](docs/usage.md#sdk-contracts) for pagination, errors and custom transports.

### MCP for agents

Configure your MCP host to launch a local STDIO server from this checkout:

```sh
uv run --directory /absolute/path/to/crewmeister-api-python --no-sync crewmeister-mcp --env-file /absolute/path/to/.env
```

Set the host's command to `uv` and pass the remaining tokens as arguments.
`CREWMEISTER_API_BASE_URL` is mandatory and must be a canonical HTTPS origin
without a path, query or credentials. Startup and tool discovery do not log in.

Start with `crewmeister_describe`, then select a registered category and endpoint.
MCP covers list, get, create, batch, patch, replace, delete, task and job operations;
downloads remain SDK/CLI-only. Read the [agent skill](.agents/skills/crewmeister-use/SKILL.md)
before operating on data. [MCP details and plugin packaging](docs/usage.md#mcp-and-consumer-plugin)
cover tool inputs, outcomes and host setup.

## Safe use

- CLI writes require `--yes`; MCP writes require `confirm=true` and host authorization.
  Neither validates the business intent or restricts the affected employees.
- CLI and MCP redact known sensitive fields, but output can still contain employee data.
  SDK output is unredacted.
- No automatic retries, write polling or rollback. An accepted job is not a completed operation.
- The default transport rejects redirects. Unknown outcomes must be reconciled before retrying.
- [Jobs, downloads, iCal and scoped salary generation](docs/usage.md#writes-jobs-and-files)
  have additional requirements; inspect them before use.

## Development

### Mandatory offline validation

```sh
docker build --target test -t crewmeister-api:test .
docker build --target sdk-artifacts --output type=local,dest=dist/sdk .
```

These run lint, formatting, types, unit tests, MCP handshake, plugin generation
and installed-package checks. Tests run without networking after dependency
preparation. Never pass host credentials, `.env` files or sockets; no live
Crewmeister requests are permitted during development, including on stage.
See [CONTRIBUTING.md](CONTRIBUTING.md) and [artifact verification](docs/usage.md#artifact-verification).

### Known API limitations

Offline tests verify client behavior, not every provider payload, permission or
business transition. Most job routes are guideline-derived, not live-verified.
Complete iCal job output, salary-file availability and unverified async flows
must not be treated as confirmed contracts. The catalog records these distinctions;
see [the usage reference](docs/usage.md#operation-catalog).

## License and contributions

Maintained by [BelStark](https://github.com/BelStark). Contributions are welcome
under [Apache-2.0](LICENSE) with [DCO sign-off](CONTRIBUTING.md); forks and
commercial use are permitted subject to the license. See [NOTICE](NOTICE);
third-party material retains its own terms.

Provided without additional warranty, support or maintenance commitments,
subject to applicable law and Apache-2.0 sections 7–8. The license does not grant
access to Crewmeister services, customer data or trademarks, nor guarantee payroll
or other business outcomes.
