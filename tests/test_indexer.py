from codesearch.indexer import CodeIndex
from codesearch.parser import SymbolInfo


def _sym(name: str, kind: str = "function", summary: str = "") -> SymbolInfo:
    return SymbolInfo(
        name=name, kind=kind, file="f.py", line=1, signature=f"def {name}()", summary=summary
    )


class TestCodeIndex:
    def test_search_by_exact_name_ranks_first(self):
        idx = CodeIndex([_sym("load_sales"), _sym("transform_orders")])
        assert idx.search("load_sales")[0].name == "load_sales"

    def test_search_by_summary_keyword(self):
        idx = CodeIndex(
            [
                _sym("load_sales", summary="Load daily sales data"),
                _sym("other"),
            ]
        )
        assert idx.search("daily sales")[0].name == "load_sales"

    def test_kind_filter_excludes_non_matching(self):
        idx = CodeIndex([_sym("fn", kind="function"), _sym("v_sales", kind="view")])
        results = idx.search("sales", kind="view")
        assert all(s.kind == "view" for s in results)

    def test_limit_respected(self):
        # 20 docs all named load_data; query matches all → exactly 3 returned
        idx = CodeIndex([_sym("load_data") for _ in range(20)])
        assert len(idx.search("load_data", limit=3)) == 3

    def test_empty_index_returns_empty(self):
        assert CodeIndex([]).search("anything") == []

    def test_zero_score_results_excluded(self):
        idx = CodeIndex([_sym("load_sales")])
        results = idx.search("completely_unrelated_xyzxyz")
        assert results == []

    def test_kind_none_returns_all_kinds(self):
        idx = CodeIndex(
            [
                _sym("fn", kind="function", summary="load data"),
                _sym("fn", kind="class", summary="load data"),
            ]
        )
        results = idx.search("fn", kind=None)
        kinds = {s.kind for s in results}
        assert "function" in kinds
        assert "class" in kinds

    def test_score_ordering_descending(self):
        idx = CodeIndex(
            [
                _sym("load_orders", summary="Load order data"),
                _sym("load_sales", summary="Load sales data here and now"),
            ]
        )
        results = idx.search("load sales")
        # load_sales has more relevant tokens — must rank ahead of load_orders
        assert results[0].name == "load_sales"
