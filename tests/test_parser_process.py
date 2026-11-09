"""Catch native parser crashes in a child process rather than killing pytest."""

import os
import subprocess
import sys


def test_large_javascript_keeps_coordinates_and_process_alive(tmp_path):
    # Rows beyond CPython's small-integer cache expose Point ownership bugs.
    source = "\n" * 300 + "".join(
        f'import {{ value as input_{number} }} from "./dep_{number}.js";\n'
        f"export function task_{number}() {{\n  return input_{number};\n}}\n"
        for number in range(400)
    )
    path = tmp_path / "large.js"
    path.write_text(source, encoding="utf-8")
    code = """
import gc
import sys
from pathlib import Path
from codesearch.imports import extract_import_details
from codesearch.parser import extract_symbols

path = Path(sys.argv[1])
for iteration in range(3):
    symbols = extract_symbols(path, "javascript")
    imports = extract_import_details(path, "javascript")
    assert len(symbols) == len(imports) == 400
    for number, (symbol, record) in enumerate(zip(symbols, imports)):
        assert symbol.name == f"task_{number}"
        assert symbol.line == 302 + number * 4
        assert symbol.end_line == 304 + number * 4
        assert record["line"] == 301 + number * 4
    gc.collect()
print("native parsing completed")
"""
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", code, str(path)],
        capture_output=True,
        text=True,
        timeout=45,
        env={**os.environ, "PYTHONMALLOC": "debug"},
    )
    assert result.returncode == 0, result.stderr[-6000:]
    assert "native parsing completed" in result.stdout
