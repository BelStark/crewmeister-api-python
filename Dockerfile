# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.11.8

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv-bin
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

FROM base AS builder
COPY --from=uv-bin /uv /uvx /usr/local/bin/
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra mcp --no-editable

FROM base AS test
COPY --from=uv-bin /uv /uvx /usr/local/bin/
COPY pyproject.toml uv.lock README.md LICENSE NOTICE DCO CONTRIBUTING.md SECURITY.md ./
COPY src ./src
COPY tests ./tests
COPY scripts ./scripts
COPY docs ./docs
COPY .agents/skills/crewmeister-use ./.agents/skills/crewmeister-use
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --dev --all-extras
RUN --network=none uv run --no-sync ruff check . \
    && uv run --no-sync black --check . \
    && uv run --no-sync mypy src \
    && uv run --no-sync python -m unittest discover -s tests -p "test_*.py" \
    && uv run --no-sync python scripts/build_plugin.py

FROM test AS sdk-package
RUN --mount=type=cache,target=/root/.cache/uv \
    uv build --no-sources --out-dir dist/sdk \
    && uv export --locked --all-extras --no-dev --no-emit-project --no-hashes \
        --output-file /tmp/cli-dependencies.txt \
    && uv run --no-sync python scripts/verify_sdk_artifact.py --prepare-extras
RUN --network=none uv run --no-sync python scripts/verify_sdk_artifact.py

FROM scratch AS sdk-artifacts
COPY --from=sdk-package /app/dist/sdk/ /

FROM scratch AS plugin-artifacts
COPY --from=test /app/dist/plugins/ /

FROM base AS runtime
ARG UID=10001
RUN adduser --disabled-password --gecos "" --home /nonexistent \
    --shell /usr/sbin/nologin --no-create-home --uid "${UID}" appuser
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
USER appuser
ENTRYPOINT ["crewmeister-mcp"]
