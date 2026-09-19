"""Build the Apache-2.0 Crewmeister consumer bundle and Codex overlay."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import tomllib
from pathlib import Path

_NAME = "crewmeister"
_SCHEMA = "https://agent-plugins.org/schemas/1.0.0"
_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT = _ROOT / "dist/plugins"
_ENVIRONMENT = (
    "CREWMEISTER_API_BASE_URL",
    "CREWMEISTER_API_BEARER_TOKEN",
    "CREWMEISTER_API_USERNAME",
    "CREWMEISTER_API_PASSWORD",
    "CREWMEISTER_API_CALLER_CONTEXT",
    "CREWMEISTER_API_TIMEOUT_SECONDS",
    "CREWMEISTER_API_PAGE_SIZE",
)


def build_plugin(
    output_dir: Path = _DEFAULT_OUTPUT,
    *,
    package_version: str | None = None,
) -> Path:
    """Build one non-overwriting plugin directory from the canonical consumer skill."""

    skill_dir = _ROOT / ".agents/skills/crewmeister-use"
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / _NAME
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"{destination} already exists")
    if package_version is None:
        with (_ROOT / "pyproject.toml").open("rb") as project:
            package_version = tomllib.load(project)["project"]["version"]
    with tempfile.TemporaryDirectory(dir=output_dir, prefix=f".{_NAME}-") as temporary:
        plugin_dir = Path(temporary) / _NAME
        plugin_dir.mkdir()
        _write(plugin_dir / "plugin.json", _portable_manifest(package_version))
        _write(plugin_dir / "mcp.json", _portable_mcp(package_version))
        _write(plugin_dir / ".codex-plugin" / "plugin.json", _codex_manifest(package_version))
        _write(plugin_dir / ".mcp.json", _codex_mcp(package_version))
        skill_output = plugin_dir / "skills" / skill_dir.name
        skill_output.mkdir(parents=True)
        shutil.copy2(skill_dir / "SKILL.md", skill_output / "SKILL.md")
        for name in ("LICENSE", "NOTICE"):
            shutil.copy2(_ROOT / name, plugin_dir / name)
        (plugin_dir / "README.md").write_text(_readme(package_version), encoding="utf-8")
        plugin_dir.replace(destination)
    return destination


def _portable_manifest(package_version: str) -> dict[str, object]:
    return {
        "$schema": f"{_SCHEMA}/plugin.schema.json",
        **_metadata(package_version),
    }


def _metadata(package_version: str) -> dict[str, object]:
    return {
        "name": _NAME,
        "version": package_version,
        "description": "Crewmeister SDK, CLI, and MCP usage instructions.",
        "author": {"name": "BelStark"},
        "license": "Apache-2.0",
        "keywords": ["crewmeister", "mcp", "sdk", "cli"],
    }


def _codex_manifest(package_version: str) -> dict[str, object]:
    return {
        **_metadata(package_version),
        "skills": "./skills/",
        "mcpServers": "./.mcp.json",
        "interface": {
            "displayName": "Crewmeister",
            "shortDescription": "Use the Crewmeister SDK, CLI, and MCP server.",
            "longDescription": "Use the installed Crewmeister API package through its fixed MCP tools.",
            "developerName": "BelStark",
            "category": "Productivity",
            "capabilities": ["Read", "Write"],
            "defaultPrompt": ["Use Crewmeister through its offline catalog and fixed MCP tools."],
        },
    }


def _codex_mcp(package_version: str) -> dict[str, object]:
    return {
        "mcpServers": {
            _NAME: {
                **_server(package_version),
                "env_vars": list(_ENVIRONMENT),
            }
        }
    }


def _portable_mcp(package_version: str) -> dict[str, object]:
    return {
        "$schema": f"{_SCHEMA}/mcp.schema.json",
        "mcpServers": {
            _NAME: {
                "type": "stdio",
                **_server(package_version),
            }
        },
    }


def _server(package_version: str) -> dict[str, object]:
    return {"command": "crewmeister-mcp", "args": ["--expected-version", package_version]}


def _readme(package_version: str) -> str:
    return f"""# Crewmeister plugin

This community integration is maintained by BelStark under Apache-2.0; see
LICENSE and NOTICE. It is not an official Crewmeister product.

Install the matching reviewed wheel before enabling this Codex reference plugin.
Replace the absolute path below with the location of your built artifact:

```sh
uv tool install \"/absolute/path/to/crewmeister_api-{package_version}-py3-none-any.whl[mcp]\"
```

Configure `CREWMEISTER_API_BASE_URL` and exactly one credential form in the host process
environment. Do not place secrets or `.env` files in this plugin. The generated bundle
checks the package version before MCP configuration or network access.

This bundle contains the portable Agent Plugins skill and MCP configuration. Its
Codex-specific overlay contains the same launch contract and adds only
environment-variable names. Other hosts need their documented native MCP setup; this
bundle does not claim their compatibility.
"""


def _write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    """Build the consumer plugin without creating a marketplace entry."""

    parser = argparse.ArgumentParser(description="Build the Crewmeister agent plugin")
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT, metavar="PATH")
    args = parser.parse_args(argv)
    print(build_plugin(args.output_dir))


if __name__ == "__main__":
    main()
