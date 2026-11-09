from pathlib import Path

from codesearch.imports import extract_imports


class TestPythonImports:
    def test_module_import(self, tmp_path: Path):
        f = tmp_path / "app.py"
        f.write_text("import os\n")
        result = extract_imports(f, "python")
        assert {"name": "os", "path": "os", "kind": "module"} in result

    def test_from_import(self, tmp_path: Path):
        f = tmp_path / "app.py"
        f.write_text("from pathlib import Path\n")
        result = extract_imports(f, "python")
        assert {"name": "Path", "path": "pathlib", "kind": "from"} in result

    def test_from_import_multi_name(self, tmp_path: Path):
        f = tmp_path / "app.py"
        f.write_text("from pkg import A, B\n")
        result = extract_imports(f, "python")
        assert {"name": "A", "path": "pkg", "kind": "from"} in result
        assert {"name": "B", "path": "pkg", "kind": "from"} in result

    def test_multiline_from_import(self, tmp_path: Path):
        f = tmp_path / "app.py"
        f.write_text("from pathlib import (\n    Path,\n    PurePath,\n)\n")
        result = extract_imports(f, "python")
        assert {"name": "Path", "path": "pathlib", "kind": "from"} in result
        assert {"name": "PurePath", "path": "pathlib", "kind": "from"} in result

    def test_multiline_from_import_with_inline_comments(self, tmp_path: Path):
        f = tmp_path / "app.py"
        f.write_text("from os import (\n    path,  # filesystem\n    getcwd,\n)\n")
        result = extract_imports(f, "python")
        names = {r["name"] for r in result}
        assert "path" in names
        assert "getcwd" in names

    def test_multiline_from_import_partial_first_line(self, tmp_path: Path):
        f = tmp_path / "app.py"
        f.write_text("from os import (path,\n    getcwd)\n")
        result = extract_imports(f, "python")
        names = {r["name"] for r in result}
        assert "path" in names
        assert "getcwd" in names


class TestJavaImports:
    def test_single_import(self, tmp_path: Path):
        f = tmp_path / "Service.java"
        f.write_text("import com.example.Foo;\n")
        result = extract_imports(f, "java")
        assert {"name": "Foo", "path": "com.example.Foo", "kind": "module"} in result

    def test_wildcard_import(self, tmp_path: Path):
        f = tmp_path / "Service.java"
        f.write_text("import com.example.*;\n")
        result = extract_imports(f, "java")
        assert {"name": "*", "path": "com.example.*", "kind": "module"} in result

    def test_static_import(self, tmp_path: Path):
        f = tmp_path / "Service.java"
        f.write_text("import static com.example.Util.method;\n")
        result = extract_imports(f, "java")
        assert {"name": "method", "path": "com.example.Util.method", "kind": "module"} in result


class TestJsTsImports:
    def test_default_import(self, tmp_path: Path):
        f = tmp_path / "app.ts"
        f.write_text("import React from 'react'\n")
        result = extract_imports(f, "typescript")
        assert {"name": "React", "path": "react", "kind": "module"} in result

    def test_named_imports(self, tmp_path: Path):
        f = tmp_path / "app.ts"
        f.write_text("import { A, B } from './utils'\n")
        result = extract_imports(f, "typescript")
        assert {"name": "A", "path": "./utils", "kind": "module"} in result
        assert {"name": "B", "path": "./utils", "kind": "module"} in result

    def test_require(self, tmp_path: Path):
        f = tmp_path / "app.js"
        f.write_text("const fs = require('fs')\n")
        result = extract_imports(f, "javascript")
        assert {"name": "fs", "path": "fs", "kind": "require"} in result

    def test_combined_default_named_import(self, tmp_path: Path):
        f = tmp_path / "app.ts"
        f.write_text("import React, { useState, useEffect } from 'react'\n")
        result = extract_imports(f, "typescript")
        names = {r["name"] for r in result}
        assert "React" in names
        assert "useState" in names
        assert "useEffect" in names
        assert all(r["path"] == "react" for r in result)

    def test_combined_default_named_import_with_alias(self, tmp_path: Path):
        f = tmp_path / "app.ts"
        f.write_text("import App, { Component as C } from './App'\n")
        result = extract_imports(f, "typescript")
        names = {r["name"] for r in result}
        assert "App" in names
        assert "C" in names


class TestGoImports:
    def test_single_import(self, tmp_path: Path):
        f = tmp_path / "main.go"
        f.write_text('import "fmt"\n')
        result = extract_imports(f, "go")
        assert {"name": "fmt", "path": "fmt", "kind": "module"} in result

    def test_block_import(self, tmp_path: Path):
        f = tmp_path / "main.go"
        f.write_text('import (\n\t"fmt"\n\t"os"\n)\n')
        result = extract_imports(f, "go")
        assert {"name": "fmt", "path": "fmt", "kind": "module"} in result
        assert {"name": "os", "path": "os", "kind": "module"} in result

    def test_dot_import_single_line(self, tmp_path: Path):
        f = tmp_path / "main.go"
        f.write_text('import . "fmt"\n')
        result = extract_imports(f, "go")
        assert any(r["path"] == "fmt" for r in result)

    def test_dot_import_in_block(self, tmp_path: Path):
        f = tmp_path / "main.go"
        f.write_text('import (\n\t. "testing"\n\t"fmt"\n)\n')
        result = extract_imports(f, "go")
        paths = {r["path"] for r in result}
        assert "testing" in paths
        assert "fmt" in paths

    def test_blank_import(self, tmp_path: Path):
        f = tmp_path / "main.go"
        f.write_text('import _ "github.com/lib/pq"\n')
        result = extract_imports(f, "go")
        assert any(r["path"] == "github.com/lib/pq" for r in result)
