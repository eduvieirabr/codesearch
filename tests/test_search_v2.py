"""Search ranking regressions from the comparison, independently implemented."""

from codesearch.indexer import CodeIndex
from codesearch.parser import SymbolInfo


def symbol(name, file, summary="", language="python", decorators=()):
    item = SymbolInfo(
        name=name, kind="function", file=file, line=1, signature=name, summary=summary
    )
    item.language = language
    item.qualified_name = name
    item.decorators = list(decorators)
    return item


def test_exact_name_beats_many_summary_hits():
    exact = symbol("load_orders", "z.py")
    others = [
        symbol("transform_" + str(i), f"{i}.py", "load_orders orders load") for i in range(20)
    ]
    assert CodeIndex([*others, exact]).search("load_orders")[0].file == "z.py"


def test_ties_do_not_depend_on_input_order():
    symbols = [symbol("run", path) for path in ["z.py", "a.py", "b.py"]]
    expected = ["a.py", "b.py", "z.py"]
    assert [s.file for s in CodeIndex(symbols).search("run")] == expected
    assert [s.file for s in CodeIndex(list(reversed(symbols))).search("run")] == expected


def test_filters_precede_limit():
    symbols = [
        symbol("run", "a.py"),
        symbol("run", "src/b.ts", language="typescript", decorators=["route"]),
    ]
    result = CodeIndex(symbols).search(
        "run", limit=1, language="typescript", file_pattern="**/*.ts", decorator="route"
    )
    assert [s.file for s in result] == ["src/b.ts"]


def test_qualified_name_is_searchable():
    item = symbol("load", "a.py")
    item.qualified_name = "Store.load"
    assert CodeIndex([item]).search("Store.load") == [item]


def test_filter_only_search():
    symbols = [symbol("a", "a.py"), symbol("b", "b.py", decorators=["property"])]
    assert CodeIndex(symbols).search("", decorator="property")[0].name == "b"


def test_identifier_parts_include_snake_camel_and_unicode():
    symbols = [
        symbol("load_orders", "a.py"),
        symbol("loadOrders", "b.py"),
        symbol("ler_ação", "c.py"),
    ]
    index = CodeIndex(symbols)
    assert {s.file for s in index.search("orders")} == {"a.py", "b.py"}
    assert index.search("ação")[0].file == "c.py"
