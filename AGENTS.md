# Repository Agent Guide

This repository contains the Crewmeister API SDK, CLI, local STDIO MCP server,
and companion consumer skill. Keep changes small and easy to validate.

- Use uv for environments, dependency management, builds, and Python tools.
- Prefer existing dependencies and the standard library; do not add speculative abstractions.
- Keep runtime code under src/crewmeister_api, tests under tests, and build helpers under scripts.
- Keep the base SDK dependency-free; CLI environment files and MCP remain optional extras.
- Never commit secrets, employee data, live API captures, or generated artifacts.
- Do not make live Crewmeister requests during development or tests, including against stage.
- Preserve explicit write confirmation, redaction, and no-automatic-retry behavior.
- Keep README.md, .env.template, CI, and Docker aligned when setup changes.
- Keep only the consumer skill under .agents/skills; do not add a backlog framework.
- BelStark maintains the project. Contributions use Apache-2.0 and DCO sign-offs.

## Verification

```sh
uv sync --locked --dev --all-extras
uv run --no-sync ruff check .
uv run --no-sync black --check .
uv run --no-sync mypy src
docker build --target test -t crewmeister-api:test .
docker build --target sdk-artifacts --output type=local,dest=dist/sdk .
```

Tests run without networking in Docker after dependency preparation. Use only
synthetic data; never pass host credentials, environment files, or sockets.
Run uv lock when dependency declarations change, then repeat verification.
