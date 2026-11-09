from codesearch.parser import extract_symbols


class TestPythonParser:
    def test_extracts_top_level_function(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.py", "python")
        assert any(s.name == "load_sales" for s in syms)

    def test_function_kind(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.py", "python")
        sym = next(s for s in syms if s.name == "load_sales")
        assert sym.kind == "function"

    def test_function_line_number(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.py", "python")
        sym = next(s for s in syms if s.name == "load_sales")
        assert sym.line == 1

    def test_function_signature_contains_params(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.py", "python")
        sym = next(s for s in syms if s.name == "load_sales")
        assert "date" in sym.signature

    def test_function_docstring_extracted(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.py", "python")
        sym = next(s for s in syms if s.name == "load_sales")
        assert "Load daily sales" in sym.summary

    def test_extracts_class(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.py", "python")
        assert any(s.name == "SalesProcessor" and s.kind == "class" for s in syms)

    def test_extracts_class_method(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.py", "python")
        assert any(s.name == "process" and s.kind == "function" for s in syms)

    def test_excludes_nested_function(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.py", "python")
        assert not any(s.name == "_nested" for s in syms)

    def test_empty_file_returns_empty(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        assert extract_symbols(f, "python") == []

    def test_excludes_nested_class(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.py", "python")
        assert not any(s.name == "_InnerClass" for s in syms)

    def test_filepath_override(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.py", "python", filepath="src/etl/sales.py")
        assert all(s.file == "src/etl/sales.py" for s in syms)


class TestSQLParser:
    def test_extracts_function(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.sql", "sql")
        assert any(s.name == "get_monthly_revenue" for s in syms)

    def test_function_kind(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.sql", "sql")
        sym = next(s for s in syms if s.name == "get_monthly_revenue")
        assert sym.kind == "function"

    def test_extracts_view(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.sql", "sql")
        assert any(s.name == "v_sales_summary" and s.kind == "view" for s in syms)

    def test_extracts_table_kind(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.sql", "sql")
        assert any(s.name == "raw_transactions" and s.kind == "table" for s in syms)

    def test_schema_qualified_name(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.sql", "sql")
        assert any("bronze.events" in s.name for s in syms)

    def test_no_match_returns_empty(self, tmp_path):
        f = tmp_path / "q.sql"
        f.write_text("SELECT 1 FROM orders;")
        assert extract_symbols(f, "sql") == []


class TestYAMLParser:
    def test_extracts_top_level_keys(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.yaml", "yaml")
        names = [s.name for s in syms]
        assert "dag_id" in names
        assert "schedule" in names

    def test_kind_is_key(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.yaml", "yaml")
        assert syms and all(s.kind == "key" for s in syms)


class TestJSONParser:
    def test_extracts_top_level_keys(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.json", "json")
        names = [s.name for s in syms]
        assert "title" in names
        assert "type" in names

    def test_extracts_definitions(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.json", "json")
        defs = [s for s in syms if s.kind == "definition"]
        names = [s.name for s in defs]
        assert "Address" in names
        assert "Product" in names

    def test_definitions_key_excluded_from_keys(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.json", "json")
        keys = [s for s in syms if s.kind == "key"]
        assert not any(s.name == "definitions" for s in keys)


# ── Java ──────────────────────────────────────────────────────────────────────


class TestJavaParser:
    def test_extracts_class(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.java", "java")
        assert any(s.name == "SampleService" and s.kind == "class" for s in syms)

    def test_extracts_methods(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.java", "java")
        names = [s.name for s in syms if s.kind == "function"]
        assert "process" in names
        assert "validate" in names

    def test_method_kind(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.java", "java")
        sym = next(s for s in syms if s.name == "process")
        assert sym.kind == "function"

    def test_method_signature_contains_name(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.java", "java")
        sym = next(s for s in syms if s.name == "process")
        assert "process" in sym.signature

    def test_method_summary_extracted(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.java", "java")
        sym = next(s for s in syms if s.name == "process")
        assert "Process input data" in sym.summary


# ── TypeScript ────────────────────────────────────────────────────────────────


class TestTypescriptParser:
    def test_extracts_functions(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.ts", "typescript")
        names = [s.name for s in syms if s.kind == "function"]
        assert "greet" in names
        assert "farewell" in names

    def test_extracts_class(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.ts", "typescript")
        assert any(s.name == "Greeter" and s.kind == "class" for s in syms)

    def test_extracts_class_method(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.ts", "typescript")
        assert any(s.name == "hello" and s.kind == "function" for s in syms)

    def test_function_signature_contains_params(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.ts", "typescript")
        sym = next(s for s in syms if s.name == "greet")
        assert "greet" in sym.signature
        assert "name" in sym.signature


# ── JavaScript ────────────────────────────────────────────────────────────────


class TestJavaScriptParser:
    def test_extracts_functions(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.js", "javascript")
        names = [s.name for s in syms if s.kind == "function"]
        assert "add" in names
        assert "subtract" in names

    def test_extracts_class(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.js", "javascript")
        assert any(s.name == "Calculator" and s.kind == "class" for s in syms)

    def test_extracts_class_method(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.js", "javascript")
        assert any(s.name == "multiply" and s.kind == "function" for s in syms)


# ── Go ────────────────────────────────────────────────────────────────────────


class TestGoParser:
    def test_extracts_functions(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.go", "go")
        names = [s.name for s in syms if s.kind == "function"]
        assert "Process" in names
        assert "Validate" in names

    def test_extracts_struct_as_class(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.go", "go")
        assert any(s.name == "SampleStruct" and s.kind == "class" for s in syms)

    def test_struct_signature_contains_struct(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.go", "go")
        sym = next(s for s in syms if s.name == "SampleStruct")
        assert "struct" in sym.signature


# ── Markdown ──────────────────────────────────────────────────────────────────


class TestMarkdownParser:
    def test_extracts_h1(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.md", "markdown")
        assert any(s.name == "Project Title" for s in syms)

    def test_extracts_h2(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.md", "markdown")
        assert any(s.name == "Overview" for s in syms)

    def test_extracts_h3(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.md", "markdown")
        assert any(s.name == "Installation" for s in syms)

    def test_ignores_h4_and_deeper(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.md", "markdown")
        assert not any(s.name == "Ignored Heading" for s in syms)

    def test_kind_is_heading(self, fixture_dir):
        syms = extract_symbols(fixture_dir / "sample.md", "markdown")
        assert syms and all(s.kind == "heading" for s in syms)
