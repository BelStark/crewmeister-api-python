import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_plugin import build_plugin


class PluginTests(unittest.TestCase):
    def test_plugin_builds_the_canonical_skill_and_carries_the_mcp_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plugin_dir = build_plugin(Path(temporary), package_version="1.2.3")

            portable = json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8"))
            codex = json.loads((plugin_dir / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
            mcp = json.loads((plugin_dir / "mcp.json").read_text(encoding="utf-8"))
            overlay = json.loads((plugin_dir / ".mcp.json").read_text(encoding="utf-8"))

            self.assertEqual(portable["$schema"], "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json")
            for manifest in (portable, codex):
                self.assertEqual(manifest["license"], "Apache-2.0")
                self.assertEqual(manifest["author"], {"name": "BelStark"})
            self.assertEqual(codex["interface"]["developerName"], "BelStark")
            for name in ("LICENSE", "NOTICE"):
                self.assertEqual(
                    (plugin_dir / name).read_bytes(), (Path(__file__).resolve().parents[1] / name).read_bytes()
                )
            self.assertIn("Apache License", (plugin_dir / "LICENSE").read_text(encoding="utf-8"))
            self.assertEqual(codex["skills"], "./skills/")
            self.assertEqual(mcp["$schema"], "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json")
            self.assertEqual(mcp["mcpServers"]["crewmeister"]["type"], "stdio")
            self.assertEqual(mcp["mcpServers"]["crewmeister"]["command"], "crewmeister-mcp")
            self.assertEqual(mcp["mcpServers"]["crewmeister"]["args"], ["--expected-version", "1.2.3"])
            self.assertEqual(overlay["mcpServers"]["crewmeister"]["command"], "crewmeister-mcp")
            self.assertEqual(overlay["mcpServers"]["crewmeister"]["args"], ["--expected-version", "1.2.3"])
            self.assertIn("CREWMEISTER_API_BASE_URL", overlay["mcpServers"]["crewmeister"]["env_vars"])
            self.assertTrue((plugin_dir / "skills" / "crewmeister-use" / "SKILL.md").is_file())
            self.assertEqual(
                sorted(path.relative_to(plugin_dir).as_posix() for path in plugin_dir.rglob("*") if path.is_file()),
                [
                    ".codex-plugin/plugin.json",
                    ".mcp.json",
                    "LICENSE",
                    "NOTICE",
                    "README.md",
                    "mcp.json",
                    "plugin.json",
                    "skills/crewmeister-use/SKILL.md",
                ],
            )

    def test_plugin_refuses_to_overwrite_an_existing_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            bundle = build_plugin(output)
            before = (bundle / "plugin.json").read_bytes()
            with self.assertRaises(FileExistsError):
                build_plugin(output)
            self.assertEqual((bundle / "plugin.json").read_bytes(), before)
