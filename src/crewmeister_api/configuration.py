"""Explicit environment-file loading for Crewmeister command integrations."""

from __future__ import annotations

import os
from collections.abc import Mapping

from crewmeister_api.client import CrewmeisterConfigError


def load_env_file(path: str, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return values from one UTF-8 file with process values taking precedence."""

    try:
        from dotenv.parser import parse_stream
    except ImportError:
        raise CrewmeisterConfigError(
            "--env-file requires python-dotenv; install crewmeister-api[cli] or crewmeister-api[mcp]."
        ) from None
    with open(path, encoding="utf-8") as stream:
        bindings = list(parse_stream(stream))
    if any(binding.error for binding in bindings):
        raise CrewmeisterConfigError("The environment file did not contain valid syntax.")
    file_values = {binding.key: binding.value for binding in bindings if binding.key is not None}
    values: dict[str, str] = {key: value for key, value in file_values.items() if value is not None}
    values.update(os.environ if environ is None else environ)
    return values
