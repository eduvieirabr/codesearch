import json
import subprocess
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


async def test_preindex_persists_snapshot_before_mcp_start(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "module.py").write_text("def ping(): return 'pong'\n")
    args = [
        "-m",
        "codesearch",
        "--workspace",
        str(root),
        "--data-dir",
        str(tmp_path / "data"),
    ]
    result = subprocess.run(
        [sys.executable, *args, "--index-only"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    indexed = json.loads(result.stdout)
    assert indexed["status"] == "ok"
    assert indexed["updated"] == indexed["files"] == 1
    transport = StdioTransport(command=sys.executable, args=args)
    async with Client(transport, timeout=30) as client:
        status = (await client.call_tool("get_index_status", {})).data
        assert status["generation"] == indexed["generation"]
        assert status["indexed_at"] == indexed["indexed_at"]
        assert status["symbols"] == 1
        symbols = await client.call_tool("search_symbols", {"query": "ping"})
        assert symbols.data["result_count"] == 1
        refreshed = (await client.call_tool("get_index_status", {})).data
        assert refreshed["read_files"] == refreshed["updated"] == 0
        assert refreshed["unchanged"] == 1
