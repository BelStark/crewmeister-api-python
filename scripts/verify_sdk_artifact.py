"""Existing installed-artifact checks; run only in the offline Docker stage."""

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

root = Path.cwd()
wheel = next((root / "dist/sdk").glob("*.whl"))
sdist = next((root / "dist/sdk").glob("*.tar.gz"))
extra_environments = {
    "cli": ("cli", Path("/tmp/crewmeister-cli-consumer")),
    "mcp": ("mcp", Path("/tmp/crewmeister-mcp-consumer")),
    "combined": ("cli,mcp", Path("/tmp/crewmeister-combined-consumer")),
}
if sys.argv[1:] == ["--prepare-extras"]:
    # Dependency installation only; all executable checks remain in the network-disabled stage.
    for extras, environment in extra_environments.values():
        subprocess.run(["uv", "venv", str(environment), "--python", "3.14"], check=True)
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(environment / "bin/python"),
                "--constraint",
                "/tmp/cli-dependencies.txt",
                f"{wheel}[{extras}]",
            ],
            check=True,
        )
    sys.exit(0)

with zipfile.ZipFile(wheel) as archive:
    names = archive.namelist()
    assert "crewmeister_api/py.typed" in names
    assert "crewmeister_api/contracts.json" in names
    assert all(n.startswith(("crewmeister_api/", "crewmeister_api-")) for n in names)
    assert not any(n.endswith(".crt") or "crewmeister_prime" in n for n in names)
    for name in ("LICENSE", "NOTICE"):
        bundled = next(n for n in names if n.endswith(f".dist-info/licenses/{name}"))
        assert archive.read(bundled) == (root / name).read_bytes()
with tarfile.open(sdist) as archive:
    names = archive.getnames()
    assert any(n.endswith("/src/crewmeister_api/py.typed") for n in names)
    assert any(n.endswith("/src/crewmeister_api/contracts.json") for n in names)
    assert all(
        n.split("/")[1]
        in {
            "src",
            "tests",
            "scripts",
            "docs",
            ".agents",
            "pyproject.toml",
            "README.md",
            "LICENSE",
            "NOTICE",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "DCO",
            "PKG-INFO",
            ".gitignore",
        }
        for n in names
    )
    for name in (
        "LICENSE",
        "NOTICE",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "DCO",
        "docs/usage.md",
        "tests/fixtures/api-operations.csv",
        "scripts/build_plugin.py",
        ".agents/skills/crewmeister-use/SKILL.md",
    ):
        bundled = next(n for n in names if n.endswith(f"/{name}"))
        with archive.extractfile(bundled) as content:
            assert content.read() == (root / name).read_bytes()

with tempfile.TemporaryDirectory(prefix="crewmeister-consumer-") as directory:
    consumer = Path(directory)
    python = consumer / "venv/bin/python"
    cli = consumer / "venv/bin/crewmeister"
    env = {key: value for key, value in os.environ.items() if not key.startswith("CREWMEISTER_")}
    env.pop("PYTHONPATH", None)
    subprocess.run(["uv", "venv", "--offline", str(consumer / "venv"), "--python", "3.14"], check=True)
    subprocess.run(["uv", "pip", "install", "--offline", "--no-deps", "--python", str(python), str(wheel)], check=True)
    shutil.copytree(root / "tests", consumer / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    subprocess.run(
        [str(python), "-m", "unittest", "discover", "-s", "tests", "-p", "test_crewmeister_*.py"],
        cwd=consumer,
        env=env,
        check=True,
    )
    metadata_check = """
from importlib.metadata import distribution
from importlib.util import find_spec
assert find_spec("crewmeister_prime") is None
package = distribution("crewmeister-api")
assert package.metadata["License-Expression"] == "Apache-2.0"
assert set(package.metadata.get_all("License-File")) == {"LICENSE", "NOTICE"}
assert package.metadata["Author"] == "BelStark"
assert package.metadata["Maintainer"] == "BelStark"
assert "Private :: Do Not Upload" not in package.metadata.get_all("Classifier", [])
assert [(e.name, e.value) for e in package.entry_points] == [
    ("crewmeister", "crewmeister_api.cli:main"),
    ("crewmeister-mcp", "crewmeister_api.mcp_server:main"),
]
assert package.requires and len(package.requires) == 3
assert any(requirement.startswith("mcp") and "extra == 'mcp'" in requirement for requirement in package.requires)
assert sum(requirement.startswith("python-dotenv") for requirement in package.requires) == 2
assert find_spec("dotenv") is None
assert find_spec("mcp") is None
print(package.version)
"""
    package_version = subprocess.check_output(
        [str(python), "-c", metadata_check], cwd=consumer, env=env, text=True
    ).strip()
    cli_version = subprocess.check_output(
        [str(cli), "--env-file", "missing.env", "--version"], cwd=consumer, env=env, text=True
    ).strip()
    assert cli_version == f"crewmeister {package_version}"
    subprocess.run(
        [str(cli), "--env-file", "missing.env", "--help"], cwd=consumer, env=env, check=True, stdout=subprocess.DEVNULL
    )
    cli = extra_environments["cli"][1] / "bin/crewmeister"
    # Main path: actual file loading, then environment precedence, using the installed executable.
    (consumer / ".env").write_text("CREWMEISTER_API_PAGE_SIZE=0\n", encoding="utf-8")
    args = [str(cli), "--env-file", ".env", "platform", "members", "list", "--limit", "0"]
    invalid = subprocess.run(args, cwd=consumer, env=env, text=True, capture_output=True)
    assert invalid.returncode == 1 and "CREWMEISTER_API_PAGE_SIZE" in invalid.stderr and not invalid.stdout
    valid = subprocess.run(
        args, cwd=consumer, env={**env, "CREWMEISTER_API_PAGE_SIZE": "2"}, text=True, capture_output=True
    )
    assert valid.returncode == 0 and valid.stdout == "[]\n" and not valid.stderr
    # Critical failure: explicitly missing file; --limit 0 guarantees no request even on regression.
    (consumer / ".env").unlink()
    missing = subprocess.run(args, cwd=consumer, env=env, text=True, capture_output=True)
    assert missing.returncode == 1 and "I/O error" in missing.stderr and not missing.stdout
    for _extras, environment in (extra_environments["mcp"], extra_environments["combined"]):
        mcp_python = environment / "bin/python"
        mcp = environment / "bin/crewmeister-mcp"
        subprocess.run([str(mcp_python), "-c", "import mcp"], cwd=consumer, env=env, check=True)
        subprocess.run(
            [
                str(mcp_python),
                "-c",
                "from crewmeister_api import CrewmeisterApiClient, CrewmeisterApiConfig; "
                "from crewmeister_api.mcp_server import McpRouter, create_server; "
                "create_server(McpRouter(CrewmeisterApiClient(CrewmeisterApiConfig("
                "base_url='https://example.invalid', bearer_token='synthetic'))))",
            ],
            cwd=consumer,
            env=env,
            check=True,
        )
        subprocess.run(
            [str(mcp_python), "-m", "unittest", "tests.test_crewmeister_mcp_stdio"],
            cwd=consumer,
            env=env,
            check=True,
        )
        mismatch = subprocess.run(
            [str(mcp), "--expected-version", "0.0.0"], cwd=consumer, env=env, text=True, capture_output=True
        )
        assert mismatch.returncode == 2 and "requires crewmeister-api 0.0.0" in mismatch.stderr and not mismatch.stdout
    (consumer / "consumer.py").write_text(
        "from crewmeister_api import CrewmeisterApiClient, CrewmeisterApiConfig, PlatformApiService, JsonValue\n"
        "client = CrewmeisterApiClient(CrewmeisterApiConfig(bearer_token='synthetic'))\n"
        "items: list[JsonValue] = PlatformApiService(client).list_resource('members', limit=10)\n"
    )
    subprocess.run(
        [str(root / ".venv/bin/mypy"), "--python-executable", str(python), "consumer.py"],
        cwd=consumer,
        env=env,
        check=True,
    )
print("Installed SDK/CLI/MCP artifact checks passed.")
