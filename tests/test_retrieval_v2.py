"""Contracts for v0.2 retrieval and context tools."""

import json

import pytest

from codesearch.retrieval import bounded_response
from codesearch.service import CodeSearchService


@pytest.fixture
def service(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(
        "from util import calculate\n\n@route('/run')\ndef run():\n"
        "    return calculate(2)\n\nclass Base:\n    pass\n\nclass Child(Base):\n    def work(self):\n        return run()\n",
        encoding="utf-8",
    )
    (root / "util.py").write_text("def calculate(value):\n    return value * 2\n", encoding="utf-8")
    (root / "app.ts").write_text("export function run() { return 1; }\n")
    (root / ".env").write_text("PASSWORD=hidden")
    svc = CodeSearchService(root, tmp_path / "data", scan_interval=0)
    yield svc
    svc.close()


def test_search_filters_and_match_evidence(service):
    result = service.search_symbols(
        query="run", language="python", file_pattern="*.py", decorator="route"
    )
    assert result["result_count"] == 1
    assert result["results"][0]["match_type"] == "exact"
    assert result["_meta"]["generation"] > 0
    assert "coverage" in result["_meta"]


def test_batch_source_and_partial_errors(service):
    symbols = service.get_file_outline(file_path="app.py")["symbols"]
    ids = [s["symbol_id"] for s in symbols if s["name"] in {"run", "work"}]
    result = service.get_symbol_source(symbol_ids=[ids[0], "missing", ids[1], ids[0]])
    assert len(result["results"]) == 2
    assert len(result["errors"]) == 1
    assert "return calculate" in result["results"][0]["source"]


def test_context_budget_counts_serialized_envelope(service):
    ids = [s["symbol_id"] for s in service.get_file_outline(file_path="app.py")["symbols"]]
    for compact in (False, True):
        result = service.get_context_bundle(symbol_ids=ids, max_chars=1800, compact=compact)
        assert len(json.dumps(result, ensure_ascii=False)) <= 1800
        assert result["budget"]["limit_chars"] == 1800
    task = service.assemble_task_context(task="calculate", max_chars=2200)
    assert len(json.dumps(task, ensure_ascii=False)) <= 2200
    assert task["results"]


def test_context_pins_one_snapshot(service, monkeypatch):
    original = service.store.snapshot
    calls = 0

    def snapshot():
        nonlocal calls
        calls += 1
        value = original()
        if calls == 1:
            (service.workspace.root / "util.py").write_text(
                "# moved\n\ndef calculate(value):\n    return 99\n"
            )
        return value

    monkeypatch.setattr(service.store, "snapshot", snapshot)
    result = service.get_symbol_context(name="calculate")
    assert "return value * 2" in result["content"]
    assert calls == 1


def test_regex_context_and_enclosing_symbol(service):
    result = service.grep_content(
        pattern=r"return\s+calculate", is_regex=True, context_lines=1, case_sensitive=True
    )
    assert len(result["matches"]) == 1
    match = result["matches"][0]
    assert match["symbol"]["name"] == "run"
    assert "def run" in "\n".join(match["context"])
    assert not result["timed_out"]


def test_regex_timeout_is_enforced(service):
    (service.workspace.root / "adversarial.txt").write_text("a" * 100_000 + "!")
    result = service.grep_content(pattern=r"(a|aa)+$", is_regex=True)
    assert result["timed_out"]
    assert result["truncated"]


def test_fts_filters_precede_pagination(service):
    result = service.search_text(
        query="run", language="typescript", file_pattern="*.ts", max_results=1
    )
    assert [row["file"] for row in result["results"]] == ["app.ts"]


def test_graph_tools_and_reports(service):
    assert service.find_importers(file_path="util.py")["importers"][0]["path"] == "app.py"
    graph = service.get_dependency_graph(file_path="app.py")
    assert graph["edges"]
    assert service.get_blast_radius(file_path="util.py")["affected_files"]
    assert service.get_dependency_cycles()["cycles"] == []
    assert service.get_repo_outline()["directories"]
    assert service.get_index_changes()["generation"] >= 1


def test_hierarchy_candidates_and_no_compiler_claim(service):
    symbols = service.get_file_outline(file_path="app.py")["symbols"]
    child = next(s for s in symbols if s["name"] == "Child")
    run = next(s for s in symbols if s["name"] == "run")
    assert service.get_class_hierarchy(symbol_id=child["symbol_id"])["edges"]
    assert service.get_call_hierarchy(symbol_id=run["symbol_id"])["edges"]


def test_aggregate_grep_budget_and_byte_continuation(service):
    (service.workspace.root / "big.txt").write_text(("hit " + "x" * 1500 + "\n") * 100)
    result = service.grep_content(pattern="hit", max_results=500, max_chars=6000)
    assert len(json.dumps(result, ensure_ascii=False)) <= 6000
    assert result["truncated"] and result["next_offset"] is not None
    source = service.get_file_content(file_path="big.txt", max_chars=1500)
    assert source["next_cursor"]
    next_page = service.get_file_content(
        file_path="big.txt", cursor=source["next_cursor"], max_chars=1500
    )
    assert (
        source["content"] + next_page["content"]
        == (service.workspace.root / "big.txt").read_text()[:3000]
    )


def test_budgeted_source_continues_without_loss_for_unicode_crlf(service):
    source = "@route('/ação')\r\ndef enormous():\r\n    return '" + "ação" * 4000 + "'\r\n"
    (service.workspace.root / "huge.py").write_bytes(source.encode("utf-8"))
    symbol = service.search_symbols(query="enormous")["results"][0]
    result = service.get_symbol_source([symbol["symbol_id"]], max_chars=1600)
    assert result["results"] and result["truncated"]
    assert result["budget"]["used_chars"] == len(json.dumps(result, ensure_ascii=False)) <= 1600
    entry = result["results"][0]
    assert entry["source_truncated"] and entry["next_cursor"]
    combined = entry["source"]
    cursor = entry["next_cursor"]
    while cursor:
        rest = service.get_file_content(file_path="huge.py", cursor=cursor, max_chars=1500)
        combined += rest["content"]
        cursor = rest["next_cursor"]
    assert combined == source.replace("\r\n", "\n").rstrip("\n")


def test_stale_source_cursor_is_rejected(service):
    first = service.get_file_content(file_path="app.py", max_chars=10)
    (service.workspace.root / "app.py").write_text("def different(): pass\n")
    with pytest.raises(ValueError, match="stale"):
        service.get_file_content(file_path="app.py", cursor=first["next_cursor"])


def test_ambiguous_legacy_ids_require_stable_id(service):
    (service.workspace.root / "single.ts").write_text("class A { run() { return 1; } }")
    outline = service.get_file_outline(file_path="single.ts")["symbols"]
    assert len(outline) == 2
    result = service.get_symbol_source(["single.ts:1", *[s["symbol_id"] for s in outline]])
    assert result["error_count"] == 1
    assert "Ambiguous" in result["errors"][0]["error"]
    assert len(result["results"]) == 2
    assert result["results"][0]["source"] != result["results"][1]["source"]


def test_task_context_retains_omissions_and_import_limits(service):
    imports = "".join(f"import module{n}\n" for n in range(20))
    definitions = "".join(f"def worker_{n}():\n    return '" + "x" * 1000 + "'\n" for n in range(8))
    (service.workspace.root / "workers.py").write_text(imports + definitions)
    result = service.assemble_task_context("worker", max_chars=2000)
    assert result["truncated"]
    assert result["omitted_count"] > 0
    assert result["omitted_imports"] >= 10
    assert result["budget"]["used_chars"] == len(json.dumps(result, ensure_ascii=False)) <= 2000


def test_budget_reserves_longer_false_literal():
    with pytest.raises(ValueError, match="Budget too small"):
        bounded_response({"a": "x" * 908}, [], 1024)
