from codesearch.parser import extract_symbols


def test_tsx_arrow_function_has_range(tmp_path):
    path = tmp_path / "component.tsx"
    path.write_text(
        "export const Card = (name: string) => {\n return <div>{name}</div>;\n};\n",
        encoding="utf-8",
    )
    symbols = extract_symbols(path, "typescript")
    assert any(s.name == "Card" and s.end_line == 3 for s in symbols)


def test_rust_functions_and_structs(tmp_path):
    path = tmp_path / "lib.rs"
    path.write_text("pub struct User { pub name: String }\npub fn lookup() -> bool { true }\n")
    symbols = extract_symbols(path, "rust")
    assert {s.name for s in symbols} == {"User", "lookup"}


def test_python_end_line_and_utf8(tmp_path):
    path = tmp_path / "example.py"
    path.write_text('def ola():\n    """Olá mundo."""\n    return 1\n', encoding="utf-8")
    symbol = extract_symbols(path, "python")[0]
    assert symbol.end_line == 3
    assert symbol.summary == "Olá mundo."
