import pytest

from codesearch import imports
from codesearch.parser import extract_symbols


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


def test_python_metadata_and_decorator_source(tmp_path):
    text = '''# café\n@decorate("x")\nclass Worker(Base, pkg.Mixin):\n    """Worker documentation.\n\n    More detail.\n    """\n    @staticmethod\n    async def run(item: str) -> bool:\n        """Run it.\n\n        Details.\n        """\n        return await helper(item)\n'''
    path = write(tmp_path, "worker.py", text)
    symbols = extract_symbols(path, "python", "src/worker.py")
    cls, method = symbols
    assert getattr(cls, "qualified_name", "") == "Worker"
    assert cls.docstring == "Worker documentation.\n\nMore detail."
    assert cls.summary == "Worker documentation."
    assert cls.bases == ["Base", "pkg.Mixin"]
    assert cls.decorators == ['decorate("x")']
    assert method.qualified_name == "Worker.run"
    assert method.parent == "Worker"
    assert method.language == "python"
    assert method.decorators == ["staticmethod"]
    assert method.signature == "async def run(item: str) -> bool"
    assert method.source_start_line == 8
    assert method.line == 9
    assert text.encode()[method.start_byte : method.end_byte].decode().startswith("@staticmethod")
    assert method.calls == ["helper"]
    assert cls.calls == []


def test_python_calls_do_not_leak_nested_declarations(tmp_path):
    path = write(
        tmp_path,
        "a.py",
        """def outer():\n    direct()\n    def nested():\n        hidden()\n    class Hidden:\n        leaked()\n    x = lambda: also_hidden()\n    return obj.method()\n""",
    )
    symbols = extract_symbols(path, "python")
    assert [s.name for s in symbols] == ["outer"]
    assert getattr(symbols[0], "calls", None) == ["direct", "obj.method"]


def test_stable_ids_distinguish_overloads_and_survive_line_shifts(tmp_path):
    text = "class C { void f(int a) {} void f(String a) {} void f(int a) {} }\n"
    path = write(tmp_path, "C.java", text)
    before = extract_symbols(path, "java")
    ids = [getattr(s, "symbol_id", "") for s in before]
    assert len(set(ids)) == 4
    assert all(ids)
    path.write_bytes(("// shifted\n\n" + text).encode())
    after = extract_symbols(path, "java")
    assert ids == [s.symbol_id for s in after]
    assert all(s.line == 3 for s in after)
    assert "f(int a)" in after[1].signature
    assert "f(String a)" in after[2].signature


def test_typescript_declarations_arrow_members_and_scoped_calls(tmp_path):
    text = """interface Work extends Base { run(): void; }\ntype Item = string | number;\nenum Status { Ready }\nclass Worker extends Parent implements Work {\n    run = (item: Item): void => { helper(item); };\n    other() { const nested = () => hidden(); direct(); }\n}\n"""
    symbols = extract_symbols(write(tmp_path, "a.ts", text), "typescript")
    assert {"Work", "Item", "Status", "Worker", "run", "other"} <= {s.name for s in symbols}
    cls = next(s for s in symbols if s.name == "Worker")
    assert cls.bases == ["Parent", "Work"]
    assert cls.calls == []
    run = next(s for s in symbols if s.qualified_name == "Worker.run")
    assert run.parent == "Worker"
    assert run.calls == ["helper"]
    other = next(s for s in symbols if s.name == "other")
    assert other.calls == ["direct"]
    assert "nested" not in {s.name for s in symbols}


def test_java_interfaces_records_constructors_and_nested_classes(tmp_path):
    text = """interface I extends X, Y { void run(); }\nrecord R(int x) implements I { public R { check(x); } public void run() {} }\nclass C extends Base implements I { C(int x) { super(x); } class N { void call() { obj.work(); new T(); } } }\n"""
    symbols = extract_symbols(write(tmp_path, "C.java", text), "java")
    assert {"I", "R", "C", "N", "run", "call"} <= {s.name for s in symbols}
    assert next(s for s in symbols if s.name == "I").bases == ["X", "Y"]
    assert any(s.kind == "function" and s.qualified_name == "R.R" for s in symbols)
    nested = next(s for s in symbols if s.name == "N")
    assert nested.qualified_name == "C.N"
    method = next(s for s in symbols if s.name == "call")
    assert method.parent == "C.N"
    assert method.calls == ["obj.work", "T"]


def test_json_ranges_identify_nested_definition_and_unicode_key(tmp_path):
    text = '{\n  "é": 1,\n  "$defs": {\n    "Thing": {\n      "type": "object"\n    }\n  }\n}\n'
    symbols = extract_symbols(write(tmp_path, "a.json", text), "json")
    key, definition = symbols
    assert key.line == 2
    assert definition.line == 4
    assert definition.end_line == 6
    assert (
        text.encode()[definition.start_byte : definition.end_byte].decode()
        == '"Thing": {\n      "type": "object"\n    }'
    )
    assert text.encode()[key.start_byte : key.end_byte].decode() == '"é": 1'


def test_yaml_quoted_keys_have_real_ranges(tmp_path):
    text = '"key name":\n  child: value\nnext: 2\n'
    symbols = extract_symbols(write(tmp_path, "a.yaml", text), "yaml")
    assert [(s.name, s.line, s.end_line) for s in symbols] == [("key name", 1, 2), ("next", 3, 3)]
    assert (
        text.encode()[symbols[0].start_byte : symbols[0].end_byte].decode()
        == '"key name":\n  child: value'
    )


def test_markdown_sections_stop_at_peer_heading_and_ignore_fences(tmp_path):
    text = "# One\nintro\n```md\n# fake\n```\n## Child\ndetail\n# Two\nend\n"
    symbols = extract_symbols(write(tmp_path, "a.md", text), "markdown")
    assert [s.name for s in symbols] == ["One", "Child", "Two"]
    assert [(s.line, s.end_line) for s in symbols] == [(1, 7), (6, 7), (8, 9)]


def test_toml_tables_and_multiline_values(tmp_path):
    text = 'title = "Example"\n[project]\nname = "demo"\ndescription = """\n[fake]\nnot_a_key = true\n"""\n[project.scripts]\nrun = "app:main"\n'
    symbols = extract_symbols(write(tmp_path, "pyproject.toml", text), "toml")
    assert {s.qualified_name for s in symbols} == {
        "title",
        "project",
        "project.name",
        "project.description",
        "project.scripts",
        "project.scripts.run",
    }
    value = next(s for s in symbols if s.name == "description")
    assert value.end_line == 7
    assert value.parent == "project"


def test_bash_functions_and_literal_sources(tmp_path):
    text = '# source fake.sh\nsource ./lib.sh\n. "./other.sh"\nsource "$DYNAMIC"\nfunction build() {\n  compile file\n}\n'
    path = write(tmp_path, "build.sh", text)
    symbols = extract_symbols(path, "bash")
    assert [s.name for s in symbols] == ["build"]
    assert symbols[0].calls == ["compile"]
    assert symbols[0].end_line == 7
    assert hasattr(imports, "extract_import_details")
    records = imports.extract_import_details(path, "bash")
    assert [r["path"] for r in records[:2]] == ["./lib.sh", "./other.sh"]
    assert records[2]["dynamic"] is True


def test_python_import_details_preserve_aliases_and_relative_dots(tmp_path):
    text = """# import fake\ntext = "import nope"\nimport os.path as paths, sys\nfrom ..util import (\n    Thing as Alias,\n    other,\n)\nfrom . import child\n"""
    path = write(tmp_path, "a.py", text)
    legacy = imports.extract_imports(path, "python")
    assert len(legacy) == 5
    assert all(set(r) == {"name", "path", "kind"} for r in legacy)
    assert hasattr(imports, "extract_import_details")
    records = imports.extract_import_details(path, "python")
    assert records[0] == {
        "name": "os.path",
        "path": "os.path",
        "kind": "module",
        "local_name": "paths",
        "imported_name": "os.path",
        "line": 3,
        "dynamic": False,
    }
    assert records[2]["path"] == "..util"
    assert records[2]["local_name"] == "Alias"
    assert records[2]["imported_name"] == "Thing"
    assert records[-1]["path"] == "."


def test_js_imports_parse_multiline_type_reexports_and_dynamic(tmp_path):
    text = """/* require('fake'); import Bad from 'fake'; */\nconst text = "require('nope')";\nimport Default, {\n  type A as B,\n  C\n} from './mixed';\nimport type { Q } from './types';\nimport './side';\nexport { D as E } from './export';\nexport * from './all';\nconst lazy = import('./lazy');\nconst dynamic = import(target);\nconst { x: xx, y } = require('./common');\n"""
    path = write(tmp_path, "a.ts", text)
    legacy = imports.extract_imports(path, "typescript")
    assert "fake" not in {r["path"] for r in legacy}
    assert "nope" not in {r["path"] for r in legacy}
    assert hasattr(imports, "extract_import_details")
    records = imports.extract_import_details(path, "typescript")
    assert {"./mixed", "./types", "./side", "./export", "./all", "./lazy", "./common"} <= {
        r["path"] for r in records
    }
    alias = next(r for r in records if r["local_name"] == "B")
    assert alias["imported_name"] == "A"
    exported = next(r for r in records if r["path"] == "./export")
    assert exported["imported_name"] == "D"
    assert next(r for r in records if r["path"] == "./lazy")["dynamic"] is True
    assert any(r["dynamic"] and r["path"] == "target" for r in records)
    common = next(r for r in records if r["local_name"] == "xx")
    assert common["imported_name"] == "x"


@pytest.mark.parametrize(
    "filename,language,text",
    [
        ("a.py", "python", "def f():\n    pass\n"),
        ("a.ts", "typescript", "function f() {}\n"),
        ("a.go", "go", "package main\nfunc f() {}\n"),
        ("a.rs", "rust", "pub fn f() {}\n"),
        ("a.sql", "sql", "CREATE TABLE items (\n id INT\n);\nSELECT 1;\n"),
    ],
)
def test_all_source_ranges_are_bounded_utf8_slices(tmp_path, filename, language, text):
    path = write(tmp_path, filename, text)
    symbols = extract_symbols(path, language)
    assert symbols
    for symbol in symbols:
        assert getattr(symbol, "language", "") == language
        assert 0 <= symbol.start_byte < symbol.end_byte <= len(text.encode())
        assert symbol.source_start_line <= symbol.line <= symbol.end_line
        assert symbol.name in text.encode()[symbol.start_byte : symbol.end_byte].decode()
    if language == "sql":
        assert symbols[0].end_line == 3


def test_ts_decorators_include_export_and_method_source(tmp_path):
    text = "/** Useful class. */\n@decorate()\nexport class C {\n    @methodDecorator\n    run() { work(); }\n}\n"
    symbols = extract_symbols(write(tmp_path, "a.ts", text), "typescript")
    cls, method = symbols
    assert cls.decorators == ["decorate()"]
    assert method.decorators == ["methodDecorator"]
    assert cls.docstring == "Useful class."
    assert cls.source_start_line == 2
    assert method.source_start_line == 4
    assert method.line == 5
    assert (
        text.encode()[method.start_byte : method.end_byte].decode().startswith("@methodDecorator")
    )


def test_python_parenthesized_decorator_has_correct_source_start(tmp_path):
    text = "@(\n    decorate\n)\ndef run():\n    pass\n"
    symbol = extract_symbols(write(tmp_path, "a.py", text), "python")[0]
    assert symbol.source_start_line == 1
    assert text.encode()[symbol.start_byte : symbol.end_byte].decode() == text.rstrip()


def test_toml_quoted_hash_header_and_array_tables_have_ranges(tmp_path):
    text = '["a#b"."c.d"] # comment\nvalue = [\n  1,\n  2,\n]\n[[workers]]\nname = "a"\n[[workers]]\nname = "b"\n'
    symbols = extract_symbols(write(tmp_path, "a.toml", text), "toml")
    assert symbols[0].qualified_name == "a#b.c.d"
    assert symbols[0].end_line == 5
    assert symbols[1].end_line == 5
    assert len({s.symbol_id for s in symbols}) == len(symbols)
    assert symbols[2].end_line == 7
    assert symbols[4].end_line == 9


def test_ts_import_equals_require_preserves_namespace_alias(tmp_path):
    path = write(tmp_path, "a.ts", "import Library = require('./library');\n")
    records = imports.extract_import_details(path, "typescript")
    assert len(records) == 1
    assert records[0]["path"] == "./library"
    assert records[0]["local_name"] == "Library"
    assert records[0]["imported_name"] == "*"
    assert records[0]["dynamic"] is False


def test_bash_literal_source_paths_are_unquoted_and_unescaped(tmp_path):
    path = write(tmp_path, "a.sh", 'source path\\ with\\ spaces.sh\nsource ./dir/"my file".sh\n')
    records = imports.extract_import_details(path, "bash")
    assert [record["path"] for record in records] == ["path with spaces.sh", "./dir/my file.sh"]
    assert all(not record["dynamic"] for record in records)


@pytest.mark.parametrize(
    "filename,language,text",
    [
        ("broken.ts", "typescript", "class Good {}\nfunction broken( {"),
        ("broken.tsx", "typescript", "export const Good = () => <div />;\nfunction broken( {"),
        ("broken.js", "javascript", "function good() {}\nfunction broken( {"),
        ("Broken.java", "java", "class Good {}\nclass Broken {"),
        ("broken.go", "go", "package main\nfunc good() {}\nfunc broken( {"),
        ("broken.rs", "rust", "fn good() {}\nfn broken( {"),
        ("broken.sh", "bash", "good() { echo ok; }\nif true; then\n"),
    ],
)
def test_malformed_syntax_never_returns_apparently_complete_symbols(
    tmp_path, filename, language, text
):
    path = write(tmp_path, filename, text)
    with pytest.raises(SyntaxError, match=language):
        extract_symbols(path, language)


def test_malformed_tree_persists_incomplete_coverage_and_keeps_source(tmp_path):
    from codesearch.store import IndexStore
    from codesearch.workspace import Workspace

    root = tmp_path / "repo"
    root.mkdir()
    content = "class Good {}\nfunction broken( {"
    write(root, "broken.ts", content)
    workspace = Workspace(root, tmp_path / "data")
    store = IndexStore(workspace)
    try:
        report = store.refresh()
        assert report["coverage"]["complete"] is False
        assert report["coverage"]["parser_errors"] == 1
        assert report["diagnostics"] == [{"file": "broken.ts", "reason": "parser: SyntaxError"}]
        snapshot = store.snapshot()
        assert snapshot["files"][0]["content"] == content
        assert snapshot["files"][0]["symbols"] == []
        assert store.search_text("Good", 10, 0)[0]["file"] == "broken.ts"
    finally:
        store.close()
    reopened = IndexStore(workspace)
    try:
        report = reopened.refresh()
        assert report["coverage"]["complete"] is False
        assert report["coverage"]["parser_errors"] == 1
        assert report["diagnostics"] == [{"file": "broken.ts", "reason": "parser: SyntaxError"}]
    finally:
        reopened.close()
