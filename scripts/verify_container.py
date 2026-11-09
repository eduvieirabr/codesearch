"""Opt-in real-container validation, run after launching the verification fixture."""

import asyncio
import os
import subprocess
from pathlib import Path

import httpx
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test-results" / "container-workspace"


async def main():
    FIXTURE.mkdir(parents=True, exist_ok=True)
    (FIXTURE / "sample.py").write_text("def initial_symbol():\n    return 'hello'\n")
    response = httpx.get("http://127.0.0.1:18090/health", timeout=15)
    assert response.json()["status"] == "ok"
    async with Client("http://127.0.0.1:18090/mcp", timeout=30) as client:
        await client.call_tool("refresh_index", {})
        assert len(await client.list_tools()) == 26
        first = await client.call_tool("search_symbols", {"query": "initial_symbol"})
        assert first.data["result_count"] == 1
        symbol_id = first.data["results"][0]["symbol_id"]
        bundle = await client.call_tool("get_context_bundle", {"symbol_ids": [symbol_id]})
        assert "return 'hello'" in bundle.data["results"][0]["source"]
        status = await client.call_tool("refresh_index", {})
        assert status.data["read_files"] == 0
        graph = await client.call_tool("get_dependency_graph", {})
        assert graph.data["nodes"]
        (FIXTURE / "sample.py").write_text("def changed_symbol():\n    return 'updated'\n")
        await client.call_tool("refresh_index", {})
        changed = await client.call_tool("search_symbols", {"query": "changed_symbol"})
        assert changed.data["result_count"] == 1
        old = await client.call_tool("search_symbols", {"query": "initial_symbol"})
        assert all(row["name"] != "initial_symbol" for row in old.data["results"])
    result = subprocess.run(
        [
            "wsl.exe",
            "-d",
            "Ubuntu-24.04",
            "--exec",
            "podman",
            "exec",
            "codesearch-verify",
            "python",
            "-c",
            "from pathlib import Path; Path('/workspace/forbidden.txt').write_text('no')",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0 and "Read-only file system" in result.stderr
    assert not (FIXTURE / "forbidden.txt").exists()
    transport = StdioTransport(
        command="powershell.exe",
        args=[
            "-NoProfile",
            "-File",
            str(ROOT / "scripts" / "run.ps1"),
            "-Workspace",
            str(FIXTURE),
            "-Transport",
            "stdio",
        ],
        env=dict(os.environ),
    )
    async with Client(transport, timeout=45) as client:
        assert len(await client.list_tools()) == 26
        found = await client.call_tool("search_symbols", {"query": "changed_symbol"})
        assert found.data["result_count"] == 1
    print(
        "PASS: 26 tools, HTTP context/graph, zero-read refresh, changes, read-only mount and stdio"
    )


if __name__ == "__main__":
    asyncio.run(main())
