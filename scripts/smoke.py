"""Exercise a running MCP HTTP server: uv run python scripts/smoke.py URL."""

import asyncio
import sys

from fastmcp import Client


async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8091/mcp"
    async with Client(url, timeout=60) as client:
        tools = await client.list_tools()
        assert len(tools) == 26
        result = await client.call_tool("get_project_summary", {})
        assert not result.is_error
        print(
            f"Connected: {len(tools)} tools; {result.data['files']} files; {result.data['symbols']} symbols"
        )
        status = await client.call_tool("get_index_status", {})
        print(status.data)
        assert len(await client.list_resources()) == 1
        assert len(await client.list_prompts()) == 1


if __name__ == "__main__":
    asyncio.run(main())
