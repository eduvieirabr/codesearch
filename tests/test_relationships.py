"""Regression coverage for snapshot-only, conservative relationship analysis."""

import json

import pytest

from codesearch.relationships import DependencyAnalysis


def imp(path, name=None, kind="module", local=None, imported=None, dynamic=False):
    return {
        "path": path,
        "name": name or path,
        "kind": kind,
        "local_name": local if local is not None else (name or path.split(".")[0]),
        "imported_name": imported if imported is not None else (name or path),
        "line": 1,
        "dynamic": dynamic,
    }


def file(path, imports=(), symbols=(), language="python"):
    return {
        "path": path,
        "language": language,
        "content": "",
        "imports": list(imports),
        "symbols": list(symbols),
    }


def symbol(name, *, sid=None, parent=None, kind="function", calls=(), bases=()):
    return {
        "name": name.split(".")[-1],
        "qualified_name": name,
        "parent": parent,
        "symbol_id": sid or name,
        "kind": kind,
        "line": 1,
        "end_line": 3,
        "calls": list(calls),
        "bases": list(bases),
    }


def pairs(result):
    return {(edge["source"], edge["target"]) for edge in result["edges"]}


def test_python_roots_relative_children_and_from_symbol_fallback():
    analysis = DependencyAnalysis(
        [
            file("main.py", [imp("pkg.child"), imp("pkg", "helper", "from")]),
            file("src/pkg/__init__.py"),
            file("src/pkg/child.py", [imp(".", "sibling", "from")]),
            file("src/pkg/sibling.py", [imp("..pkg", "child", "from")]),
        ]
    )
    assert pairs(analysis.graph()) == {
        ("main.py", "src/pkg/child.py"),
        ("main.py", "src/pkg/__init__.py"),
        ("src/pkg/child.py", "src/pkg/sibling.py"),
        ("src/pkg/sibling.py", "src/pkg/child.py"),
    }
    assert analysis.importers("src/pkg/child.py")["total"] == 2


def test_ambiguous_python_roots_do_not_choose_a_dependency():
    analysis = DependencyAnalysis(
        [file("main.py", [imp("util")]), file("util.py"), file("src/util.py")]
    )
    result = analysis.graph("main.py")
    assert result["edges"] == []
    assert result["unresolved_counts"]["ambiguous"] == 1
    assert result["unresolved"][0]["candidates"] == ["src/util.py", "util.py"]


def test_javascript_exact_extension_index_and_ambiguous_extension_candidates():
    analysis = DependencyAnalysis(
        [
            file(
                "web/main.ts",
                [imp("./exact.js"), imp("./converted.js"), imp("./folder"), imp("./choice")],
                language="typescript",
            ),
            *[
                file(path, language="typescript")
                for path in [
                    "web/exact.js",
                    "web/exact.ts",
                    "web/converted.ts",
                    "web/folder/index.ts",
                    "web/choice.ts",
                    "web/choice.js",
                ]
            ],
        ]
    )
    result = analysis.graph("web/main.ts")
    assert pairs(result) == {
        ("web/main.ts", "web/exact.js"),
        ("web/main.ts", "web/converted.ts"),
        ("web/main.ts", "web/folder/index.ts"),
    }
    assert result["unresolved_counts"] == {"ambiguous": 1}


def test_dynamic_external_unsupported_and_missing_imports_remain_explicit():
    analysis = DependencyAnalysis(
        [
            file(
                "scripts/run.sh",
                [imp("./lib.sh"), imp("$CONFIG", dynamic=True), imp("../excluded.sh")],
                language="bash",
            ),
            file("scripts/lib.sh", language="bash"),
            file("web/main.js", [imp("react"), imp("./excluded.js")], language="javascript"),
            file("main.go", [imp("example.com/lib")], language="go"),
            file("main.java", [imp("com.example.Foo")], language="java"),
        ]
    )
    result = analysis.graph()
    assert pairs(result) == set()
    assert result["unresolved_counts"] == {
        "dynamic": 1,
        "missing": 1,
        "external": 1,
        "runtime_context": 2,
        "unsupported": 2,
    }
    assert "compiler" in result["semantics"]
    assert "safe" in result["semantics"]


def test_reverse_traversal_keeps_edge_direction_and_depth():
    analysis = DependencyAnalysis(
        [file("a.py", [imp("b")]), file("b.py", [imp("c")]), file("c.py")]
    )
    graph = analysis.graph("c.py", direction="importers", depth=1)
    assert pairs(graph) == {("b.py", "c.py")}
    assert {node["path"] for node in graph["nodes"]} == {"b.py", "c.py"}
    blast = analysis.blast_radius("c.py", depth=2, max_results=1)
    assert blast["affected_files"] == [{"path": "b.py", "distance": 1}]
    assert blast["total"] == 2
    assert blast["next_offset"] == 1
    assert analysis.blast_radius("c.py", depth=2, offset=1)["affected_files"] == [
        {"path": "a.py", "distance": 2}
    ]


def test_cycles_are_strong_components_include_self_loops_and_paginate():
    analysis = DependencyAnalysis(
        [
            file("a.py", [imp("b")]),
            file("b.py", [imp("a")]),
            file("self.py", [imp("self")]),
            file("leaf.py"),
        ]
    )
    result = analysis.cycles(max_results=1)
    assert result["cycles"][0]["files"] == ["a.py", "b.py"]
    assert result["total"] == 2
    assert result["next_offset"] == 1
    assert analysis.cycles(offset=1)["cycles"][0]["files"] == ["self.py"]


def test_long_dependency_chains_do_not_use_recursive_traversal():
    records = [file(f"m{i}.py", [imp(f"m{i + 1}")]) for i in range(1200)]
    records.append(file("m1200.py", [imp("m0")]))
    result = DependencyAnalysis(records).cycles()
    assert result["total"] == 1
    assert result["cycles"][0]["file_count"] == 1201
    assert result["cycles"][0]["files_truncated"]
    assert len(result["cycles"][0]["files"]) <= 100


def test_graph_node_edge_evidence_and_unresolved_samples_are_bounded():
    records = [
        file(
            "a.py",
            [imp("b", name="x" * 2000) for _ in range(30)]
            + [imp("missing" + str(i)) for i in range(100)],
        )
    ]
    records.extend([file("b.py", [imp("c")]), file("c.py")])
    analysis = DependencyAnalysis(records)
    result = analysis.graph("a.py", depth=3, max_nodes=2, max_edges=1)
    assert len(result["nodes"]) == 2
    assert len(result["edges"]) == 1
    assert result["truncated"]
    assert len(result["edges"][0]["evidence"]) <= 10
    assert result["edges"][0]["evidence_count"] == 30
    assert result["unresolved_count"] == 100
    assert len(result["unresolved"]) <= 50
    assert len(json.dumps(result)) < 50_000


def test_calls_use_same_file_owners_and_imported_aliases_without_global_guessing():
    analysis = DependencyAnalysis(
        [
            file(
                "main.py",
                [imp("lib", "run", "from", local="go")],
                [
                    symbol("entry", calls=["go", "Worker.work", "other", "helper"]),
                    symbol("helper"),
                    symbol("Worker", kind="class"),
                    symbol("Worker.work", parent="Worker", calls=["self.finish"]),
                    symbol("Worker.finish", parent="Worker"),
                ],
            ),
            file("lib.py", symbols=[symbol("run", sid="lib.run")]),
            file("unrelated.py", symbols=[symbol("other", sid="unrelated.other")]),
        ]
    )
    result = analysis.call_hierarchy("entry", direction="callees", depth=2)
    assert pairs(result) == {
        ("entry", "lib.run"),
        ("entry", "Worker.work"),
        ("entry", "helper"),
        ("Worker.work", "Worker.finish"),
    }
    assert result["unresolved_counts"] == {"unresolved": 1}
    assert analysis.call_hierarchy("lib.run", direction="callers")["edges"][0]["source"] == "entry"


def test_python_module_and_relative_child_aliases_resolve_calls():
    analysis = DependencyAnalysis(
        [
            file(
                "pkg/main.py",
                [imp(".child", "run", "from", local="go"), imp("pkg.child", local="child_alias")],
                [symbol("entry", calls=["go", "child_alias.run"])],
            ),
            file("pkg/child.py", symbols=[symbol("run", sid="child.run")]),
        ]
    )
    result = analysis.call_hierarchy("entry", direction="callees")
    assert pairs(result) == {("entry", "child.run")}
    assert result["edges"][0]["evidence_count"] == 2


def test_duplicate_same_file_symbols_and_aliases_are_ambiguous():
    analysis = DependencyAnalysis(
        [
            file(
                "main.py",
                [imp("one", "run", "from", local="go"), imp("two", "run", "from", local="go")],
                [
                    symbol("entry", calls=["run", "go"]),
                    symbol("run", sid="run1"),
                    symbol("run", sid="run2"),
                ],
            ),
            file("one.py", symbols=[symbol("run", sid="one.run")]),
            file("two.py", symbols=[symbol("run", sid="two.run")]),
        ]
    )
    result = analysis.call_hierarchy("entry", direction="callees")
    assert result["edges"] == []
    assert result["unresolved_counts"] == {"ambiguous": 2}


def test_inheritance_resolves_aliases_and_keeps_derived_to_base_direction():
    analysis = DependencyAnalysis(
        [
            file("base.py", symbols=[symbol("Base", sid="base.Base", kind="class")]),
            file(
                "app.py",
                [imp("base", "Base", "from", local="Parent")],
                [
                    symbol("Child", kind="class", bases=["Parent"]),
                    symbol("Grandchild", kind="class", bases=["Child", "Unknown"]),
                ],
            ),
        ]
    )
    result = analysis.class_hierarchy("base.Base", direction="subclasses", depth=2)
    assert pairs(result) == {("Child", "base.Base"), ("Grandchild", "Child")}
    assert result["unresolved_counts"] == {"unresolved": 1}


def test_missing_call_metadata_reports_limitation_without_scanning_source():
    old = symbol("entry")
    old.pop("calls")
    item = file("main.py", symbols=[old, symbol("run")])
    item["content"] = "def entry():\n    run()\n"
    result = DependencyAnalysis([item]).call_hierarchy("entry")
    assert result["edges"] == []
    assert result["metadata_missing_count"] == 1
    assert any("metadata" in reason for reason in result["limitations"])


def test_hierarchy_caps_and_duplicate_legacy_ids_are_explicit():
    analysis = DependencyAnalysis(
        [file("a.py", symbols=[symbol("root", calls=["b", "c"]), symbol("b"), symbol("c")])]
    )
    result = analysis.call_hierarchy("root", max_nodes=2)
    assert len(result["nodes"]) == 2
    assert result["truncated"]
    with pytest.raises(ValueError, match="ambiguous"):
        analysis.call_hierarchy("a.py:1")


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("graph", {"depth": -1}),
        ("graph", {"depth": 21}),
        ("graph", {"max_nodes": 0}),
        ("graph", {"max_edges": 0}),
        ("graph", {"direction": "sideways"}),
        ("importers", {"file_path": "a.py", "offset": -1}),
        ("cycles", {"max_results": 501}),
        ("blast_radius", {"file_path": "a.py", "depth": 21}),
        ("call_hierarchy", {"symbol_id": "entry", "depth": 21}),
        ("class_hierarchy", {"symbol_id": "entry"}),
    ],
)
def test_invalid_requests_raise_value_error(method, kwargs):
    analysis = DependencyAnalysis([file("a.py", symbols=[symbol("entry")])])
    with pytest.raises(ValueError):
        getattr(analysis, method)(**kwargs)


def test_python_child_module_in_one_root_does_not_hide_another_package_root():
    analysis = DependencyAnalysis(
        [
            file("main.py", [imp("pkg", "child", "from")]),
            file("pkg/child.py"),
            file("src/pkg/__init__.py"),
        ]
    )
    result = analysis.graph("main.py")
    assert result["edges"] == []
    assert result["unresolved_counts"] == {"ambiguous": 1}
    assert result["unresolved"][0]["candidates"] == ["pkg/child.py", "src/pkg/__init__.py"]


def test_ambiguous_import_binding_is_not_downgraded_to_generic_unresolved_call():
    analysis = DependencyAnalysis(
        [
            file(
                "main.py", [imp("lib", "run", "from", local="go")], [symbol("entry", calls=["go"])]
            ),
            file("lib.py", symbols=[symbol("run", sid="lib.run")]),
            file("src/lib.py", symbols=[symbol("run", sid="src.lib.run")]),
        ]
    )
    result = analysis.call_hierarchy("entry")
    assert result["edges"] == []
    assert result["unresolved_counts"] == {"ambiguous": 1}


def test_multiple_import_bindings_remain_ambiguous_even_when_only_one_has_symbol_metadata():
    analysis = DependencyAnalysis(
        [
            file(
                "main.py",
                [imp("one", "run", "from", local="go"), imp("two", "run", "from", local="go")],
                [symbol("entry", calls=["go"])],
            ),
            file("one.py", symbols=[symbol("run", sid="one.run")]),
            file("two.py"),
        ]
    )
    result = analysis.call_hierarchy("entry")
    assert result["edges"] == []
    assert result["unresolved_counts"] == {"ambiguous": 1}


def test_incoming_calls_disclose_missing_metadata_outside_reachable_nodes():
    old = symbol("entry")
    old.pop("calls")
    analysis = DependencyAnalysis([file("main.py", symbols=[old, symbol("target")])])
    result = analysis.call_hierarchy("target", direction="callers")
    assert result["metadata_missing_count"] == 1
    assert any("metadata" in limitation for limitation in result["limitations"])


def test_python_unaliased_dotted_module_and_from_child_module_bindings():
    analysis = DependencyAnalysis(
        [
            file(
                "pkg/main.py",
                [imp("pkg.child"), imp(".", "child", "from", local="c")],
                [symbol("entry", calls=["pkg.child.run", "c.run"])],
            ),
            file("pkg/child.py", symbols=[symbol("run", sid="child.run")]),
        ]
    )
    result = analysis.call_hierarchy("entry")
    assert pairs(result) == {("entry", "child.run")}
    assert result["edges"][0]["evidence_count"] == 2


def test_bash_quoted_shell_characters_are_literal_but_still_require_runtime_context():
    analysis = DependencyAnalysis(
        [
            file("run.sh", [imp("./$CONFIG.sh", dynamic=False)], language="bash"),
            file("$CONFIG.sh", language="bash"),
        ]
    )
    result = analysis.graph()
    assert pairs(result) == set()
    assert result["unresolved_counts"] == {"runtime_context": 1}


def test_javascript_named_and_namespace_aliases_and_default_import_limitations():
    analysis = DependencyAnalysis(
        [
            file(
                "main.ts",
                [
                    imp("./lib", "go", local="go", imported="run"),
                    imp("./lib", "ns", local="ns", imported="*"),
                    imp("./lib", "Default", local="Default", imported="default"),
                ],
                [symbol("entry", calls=["go", "ns.run", "Default"])],
                language="typescript",
            ),
            file(
                "lib.ts",
                symbols=[
                    symbol("run", sid="lib.run"),
                    symbol("Default", sid="lib.Default", kind="class"),
                ],
                language="typescript",
            ),
        ]
    )
    result = analysis.call_hierarchy("entry")
    assert pairs(result) == {("entry", "lib.run")}
    assert result["edges"][0]["evidence_count"] == 2
    assert result["unresolved_counts"] == {"unresolved": 1}


@pytest.mark.parametrize(
    "importer, module, package",
    [("main.py", "pkg", "pkg"), ("src/pkg/consumer.py", ".", "src/pkg")],
)
def test_python_package_symbol_and_child_module_collision_is_ambiguous(importer, module, package):
    analysis = DependencyAnalysis(
        [
            file(
                importer,
                [imp(module, "f", "from", local="call_f")],
                [symbol("entry", calls=["call_f"])],
            ),
            file(package + "/__init__.py", symbols=[symbol("f", sid="package.f")]),
            file(package + "/f.py", symbols=[symbol("other", sid="child.other")]),
        ]
    )
    graph = analysis.graph(importer)
    assert graph["edges"] == []
    assert graph["unresolved_counts"] == {"ambiguous": 1}
    assert graph["unresolved"][0]["candidates"] == [package + "/__init__.py", package + "/f.py"]
    assert analysis.importers(package + "/f.py")["total"] == 0
    calls = analysis.call_hierarchy("entry", direction="callees")
    assert calls["edges"] == []
    assert calls["unresolved_counts"] == {"ambiguous": 1}


@pytest.mark.parametrize("source_path", ["./common.sh", "common.sh", "../common.sh"])
def test_bash_literal_sources_do_not_invent_cwd_or_path_resolution(source_path):
    analysis = DependencyAnalysis(
        [
            file("scripts/build.sh", [imp(source_path, kind="source")], language="bash"),
            file("scripts/common.sh", language="bash"),
            file("common.sh", language="bash"),
        ]
    )
    result = analysis.graph("scripts/build.sh")
    assert result["edges"] == []
    assert result["unresolved_counts"] == {"runtime_context": 1}
    assert result["unresolved"][0]["candidates"] == []
    assert analysis.importers("scripts/common.sh")["total"] == 0
    assert analysis.importers("common.sh")["total"] == 0
