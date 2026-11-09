from concurrent.futures import ThreadPoolExecutor

import pytest

from codesearch.service import CodeSearchService


@pytest.fixture
def service(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "sample.py").write_text(
        'import os\n\ndef hello():\n    """Say hello."""\n    return "hello"\n', encoding="utf-8"
    )
    (root / ".env").write_text("SUPER_SECRET=123")
    (root / ".codesearchignore").write_text("hidden.py\n")
    (root / "hidden.py").write_text("def secret(): pass")
    svc = CodeSearchService(root, tmp_path / "data", scan_interval=0)
    yield svc
    svc.close()


def test_all_legacy_operations(service):
    assert service.index_repo(".")["status"] == "ok"
    assert service.get_file_tree()["tree"]
    assert service.get_file_outline(file_path="sample.py")["symbols"][0]["name"] == "hello"
    assert service.search_symbols(query="hello")["results"][0]["file"] == "sample.py"
    assert service.get_file_content(file_path="sample.py", start_line=3, end_line=4)[
        "content"
    ].startswith("def hello")
    assert service.find_file(pattern="**/*.py")["matches"][0]["path"] == "sample.py"
    assert service.grep_content(pattern="HELLO")["matches"]
    assert service.find_references(name="hello")["references"]
    assert service.get_file_imports(file_path="sample.py")["imports"][0]["name"] == "os"


def test_new_tools_and_refresh(service):
    assert service.index_directory()["status"] == "ok"
    assert service.get_index_status()["files"] == 2  # source + ignore file
    assert service.get_project_summary()["languages"]["python"] == 1
    assert service.search_text(query="hello")["results"][0]["file"] == "sample.py"
    context = service.get_symbol_context(name="hello")
    assert context["symbol"]["end_line"] == 5 and 'return "hello"' in context["content"]
    (service.workspace.root / "new.py").write_text("def added(): pass")
    assert service.refresh_index()["updated"] == 1
    assert service.search_symbols(query="added")["result_count"] == 1


@pytest.mark.parametrize(
    "path", [".env", "hidden.py", "../outside.py", "/etc/passwd", r"C:\Windows\win.ini"]
)
def test_exclusions_apply_to_all_direct_tools(service, path):
    for method in (service.get_file_content, service.get_file_outline, service.get_file_imports):
        with pytest.raises(ValueError):
            method(file_path=path)
    assert not service.grep_content(pattern="SUPER_SECRET")["matches"]
    assert not service.search_symbols(query="secret", kind=None)["results"]


def test_exact_limit_and_pagination(service):
    first = service.find_file(pattern="*", max_results=1)
    assert first["truncated"] and first["next_offset"] == 1
    second = service.find_file(pattern="*", max_results=1, offset=1)
    assert not second["truncated"] and second["next_offset"] is None
    assert first["matches"][0]["path"] != second["matches"][0]["path"]
    assert service.grep_content(pattern="import", max_results=1)["truncated"] is False
    assert service.find_references(name="")["references"] == []


def test_invalid_limits_queries_and_alias(service):
    with pytest.raises(ValueError):
        service.search_symbols(query="hello", max_results=-1)
    with pytest.raises(ValueError):
        service.get_file_tree(repo="https://github.com/o/r")
    with pytest.raises(ValueError):
        service.get_file_content(file_path="sample.py", start_line=0)
    with pytest.raises(ValueError):
        service.grep_content(pattern="")
    assert service.search_text(query="")["results"] == []


def test_large_lines_are_bounded(service):
    (service.workspace.root / "long.txt").write_text("x" * 100_000)
    result = service.get_file_content(file_path="long.txt")
    assert len(result["content"]) <= 64_000 and result["truncated"]
    match = service.grep_content(pattern="xxx")["matches"][0]
    assert len(match["content"]) <= 2000


def test_concurrent_queries(service):
    with ThreadPoolExecutor(max_workers=4) as pool:
        answers = list(pool.map(lambda _: service.search_symbols(query="hello"), range(8)))
    assert all(answer["result_count"] == 1 for answer in answers)
