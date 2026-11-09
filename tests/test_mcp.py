import json

from fastmcp import Client

from codesearch.server import create_server
from codesearch.service import CodeSearchService

LEGACY = {
    "index_repo",
    "get_file_tree",
    "get_file_outline",
    "search_symbols",
    "get_file_content",
    "find_file",
    "grep_content",
    "find_references",
    "get_file_imports",
}


async def test_mcp_tools_resources_prompts_and_errors(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("def ping():\n    return 'pong'\n\nclass Base:\n    pass\n")
    service = CodeSearchService(root, tmp_path / "data", scan_interval=0)
    try:
        async with Client(create_server(service)) as client:
            tools = await client.list_tools()
            assert len(tools) == 26 and LEGACY <= {tool.name for tool in tools}
            outline = await client.call_tool("get_file_outline", {"file_path": "app.py"})
            symbols = {s["name"]: s["symbol_id"] for s in outline.data["symbols"]}
            for name, args in [
                ("index_repo", {"url": "."}),
                ("index_directory", {}),
                ("refresh_index", {}),
                ("get_index_status", {}),
                ("get_project_summary", {}),
                ("get_file_tree", {}),
                ("get_file_outline", {"file_path": "app.py"}),
                ("search_symbols", {"query": "ping"}),
                ("get_file_content", {"file_path": "app.py"}),
                ("find_file", {"pattern": "*.py"}),
                ("grep_content", {"pattern": "pong"}),
                ("find_references", {"name": "ping"}),
                ("get_file_imports", {"file_path": "app.py"}),
                ("search_text", {"query": "pong"}),
                ("get_symbol_context", {"name": "ping"}),
                ("get_symbol_source", {"symbol_ids": [symbols["ping"]]}),
                ("get_context_bundle", {"symbol_ids": [symbols["ping"]]}),
                ("assemble_task_context", {"task": "ping"}),
                ("find_importers", {"file_path": "app.py"}),
                ("get_dependency_graph", {}),
                ("get_blast_radius", {"file_path": "app.py"}),
                ("get_dependency_cycles", {}),
                ("get_call_hierarchy", {"symbol_id": symbols["ping"]}),
                ("get_class_hierarchy", {"symbol_id": symbols["Base"]}),
                ("get_repo_outline", {}),
                ("get_index_changes", {}),
            ]:
                result = await client.call_tool(name, args)
                assert not result.is_error, name
            resources = await client.list_resources()
            assert str(resources[0].uri) == "codesearch://summary"
            content = await client.read_resource("codesearch://summary")
            assert json.loads(content[0].text)["files"] == 1
            assert len(await client.list_prompts()) == 1
            prompt = await client.get_prompt("explore_project", {"question": "Where is ping?"})
            assert prompt.messages
            result = await client.call_tool(
                "get_file_content", {"file_path": "../secret"}, raise_on_error=False
            )
            assert result.is_error
    finally:
        service.close()
