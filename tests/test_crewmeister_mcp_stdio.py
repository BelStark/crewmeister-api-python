"""Exercise the installed MCP entry point without a Crewmeister network request."""

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec("mcp"), "MCP extra is not installed")
class CrewmeisterMcpStdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_initializes_lists_tools_and_describes_without_credentials(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server = StdioServerParameters(
            command=str(Path(sys.executable).with_name("crewmeister-mcp")),
            env={"CREWMEISTER_API_BASE_URL": "https://example.invalid"},
        )
        async with (
            asyncio.timeout(20),
            stdio_client(server) as (reader, writer),
            ClientSession(reader, writer) as session,
        ):
            initialized = await session.initialize()
            self.assertTrue(initialized.capabilities.tools)
            tools = await session.list_tools()
            self.assertEqual(
                {tool.name for tool in tools.tools},
                {
                    f"crewmeister_{name}"
                    for name in (
                        "describe",
                        "list",
                        "get",
                        "create",
                        "batch",
                        "patch",
                        "replace",
                        "delete",
                        "task",
                        "job",
                    )
                },
            )
            result = await session.call_tool("crewmeister_describe", {})
            self.assertFalse(result.is_error)
            self.assertEqual(result.structured_content["operation_count"], 469)
