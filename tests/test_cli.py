import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def test_real_stdio_process(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "module.py").write_text("def ping(): return 'pong'")
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "codesearch", "--workspace", str(root), "--data-dir", str(tmp_path / "data")],
    )
    async with Client(transport, timeout=30) as client:
        assert len(await client.list_tools()) == 26
        result = await client.call_tool("search_symbols", {"query": "ping"})
        assert result.data["result_count"] == 1
