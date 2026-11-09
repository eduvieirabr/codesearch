"""Record the manual examples through a real MCP stdio client, using synthetic files."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from codesearch import __version__
from codesearch.server import TOOLS

ROOT = Path(__file__).resolve().parents[1]


async def record(output: Path) -> None:
    catalog = json.loads((ROOT / "docs/manual/tools.json").read_text(encoding="utf-8"))
    assert {entry["name"] for entry in catalog} == set(TOOLS)
    recordings: list[dict] = []
    ids: dict[str, str] = {}

    with tempfile.TemporaryDirectory(prefix="codesearch-manual-") as directory:
        temporary = Path(directory)
        workspace = temporary / "manual-project"
        shutil.copytree(
            ROOT / "examples/manual-project",
            workspace,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        transport = StdioTransport(
            command=sys.executable,
            keep_alive=False,
            args=[
                "-m",
                "codesearch",
                "--workspace",
                str(workspace),
                "--data-dir",
                str(temporary / "index"),
                "--transport",
                "stdio",
                "--scan-interval",
                "3600",
            ],
        )
        async with Client(transport, timeout=60) as client:
            schemas = await client.list_tools()
            assert {tool.name for tool in schemas} == set(TOOLS)

            async def call(name: str, args: dict, label: str, group: str) -> dict:
                result = await client.call_tool(name, args)
                assert not result.is_error, name
                data = result.data
                assert isinstance(data, dict), name
                recordings.append(
                    {"tool": name, "args": args, "label": label, "group": group, "result": data}
                )
                return data

            async def resolve(value):
                if isinstance(value, str) and value.startswith("$"):
                    name = value[1:]
                    if name not in ids:
                        found = await call(
                            "search_symbols",
                            {"query": name, "kind": None},
                            f"Descobrir o ID de {name}",
                            "Preparar IDs",
                        )
                        matches = [item for item in found["results"] if item["name"] == name]
                        assert len(matches) == 1, name
                        ids[name] = matches[0]["symbol_id"]
                    return ids[name]
                if isinstance(value, list):
                    return [await resolve(item) for item in value]
                if isinstance(value, dict):
                    return {key: await resolve(item) for key, item in value.items()}
                return value

            results = {}
            for entry in catalog:
                results[entry["name"]] = await call(
                    entry["name"], await resolve(entry["args"]), entry["prompt"], entry["group"]
                )

            # Assert useful observations, not just successful protocol responses.
            assert results["get_project_summary"]["files"] == 8
            assert results["search_text"]["results"]
            assert results["grep_content"]["matches"][0]["file"] == "shop/pricing.py"
            assert {row["path"] for row in results["find_importers"]["importers"]} == {
                "shop/checkout.py"
            }
            assert {
                row["path"]: row["distance"]
                for row in results["get_blast_radius"]["affected_files"]
            } == {"shop/checkout.py": 1, "shop/api.py": 2}
            assert results["get_dependency_cycles"]["cycles"][0]["files"] == [
                "shop/cycle_a.py",
                "shop/cycle_b.py",
            ]
            assert results["get_call_hierarchy"]["edges"]
            assert results["get_class_hierarchy"]["edges"]
            assert results["get_context_bundle"]["budget"]["used_chars"] <= 12000
            assert results["get_symbol_source"]["error_count"] == 0

            first = await call(
                "find_file",
                {"pattern": "**/*.py", "max_results": 2},
                "Página 1: dois arquivos Python",
                "Paginação e limites",
            )
            assert first["next_offset"] == 2
            second = await call(
                "find_file",
                {"pattern": "**/*.py", "max_results": 2, "offset": first["next_offset"]},
                "Página 2: continuar com next_offset",
                "Paginação e limites",
            )
            assert not (
                {row["path"] for row in first["matches"]}
                & {row["path"] for row in second["matches"]}
            )
            part = await call(
                "get_file_content",
                {"file_path": "shop/pricing.py", "max_chars": 80},
                "Leitura curta: observar next_cursor",
                "Paginação e limites",
            )
            assert part["truncated"] and part["next_cursor"]
            tail = await call(
                "get_file_content",
                {"file_path": "shop/pricing.py", "cursor": part["next_cursor"], "max_chars": 4000},
                "Continuar a leitura pelo cursor",
                "Paginação e limites",
            )
            assert part["content"] + tail["content"] == (workspace / "shop/pricing.py").read_text(
                encoding="utf-8"
            )
            partial = await call(
                "get_symbol_source",
                {"symbol_ids": [ids["calculate_total"], "missing-demo-id"], "max_chars": 8000},
                "Um ID válido e um inválido: observar o erro parcial",
                "Paginação e limites",
            )
            assert partial["error_count"] == 1 and len(partial["results"]) == 1

            # This write simulates a developer edit, outside MCP, in the temporary copy only.
            pricing = workspace / "shop/pricing.py"
            pricing.write_text(
                pricing.read_text(encoding="utf-8")
                + '\n\ndef shipping_fee() -> int:\n    """Added during the demo."""\n    return 0\n',
                encoding="utf-8",
            )
            await call(
                "refresh_index",
                {"force": False},
                "Atualizar após uma edição na cópia temporária",
                "Atualização incremental",
            )
            delta = await call(
                "get_index_changes", {}, "Ver o delta da edição simulada", "Atualização incremental"
            )
            assert "shop/pricing.py" in json.dumps(delta)
            updated = await call(
                "search_symbols",
                {"query": "shipping_fee", "kind": None},
                "Encontrar shipping_fee sem commit",
                "Atualização incremental",
            )
            assert updated["results"][0]["name"] == "shipping_fee"
            await call(
                "refresh_index",
                {"force": True},
                "Verificação integral opcional",
                "Atualização incremental",
            )
            await call(
                "get_index_status", {}, "Conferir o índice ao final", "Atualização incremental"
            )

            resources = await client.list_resources()
            prompts = await client.list_prompts()
            assert any(str(item.uri) == "codesearch://summary" for item in resources)
            assert any(item.name == "explore_project" for item in prompts)

    payload = {
        "version": __version__,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "transport": "stdio",
        "workspace": "examples/manual-project (temporary copy)",
        "source_execution": False,
        "tool_count": len(schemas),
        "call_count": len(recordings),
        "checks": [
            "26 tools via MCP stdio",
            "direct and transitive importers",
            "import cycle",
            "call and class candidates",
            "JSON budget",
            "pagination",
            "source cursor",
            "partial ID error",
            "incremental refresh",
            "resource and prompt discovery",
        ],
        "schemas": [{"name": item.name, "inputSchema": item.input_schema} for item in schemas],
        "recordings": recordings,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {len(schemas)} tools, {len(recordings)} MCP stdio calls; {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/manual/demo-results.json")
    args = parser.parse_args()
    asyncio.run(record(args.output))


if __name__ == "__main__":
    main()
