"""Bounded, conservative relationship queries over one admitted index snapshot.

This module never reads or executes workspace files. Every edge is a syntactic
candidate, not a compiler result or evidence that deleting a file is safe.
"""

from __future__ import annotations

import posixpath
import re
from collections import Counter, defaultdict, deque

MAX_DEPTH = 20
MAX_SAMPLE = 50
MAX_EVIDENCE = 10
SEMANTICS = (
    "Static candidates from admitted snapshot metadata; no compiler resolution. "
    "Edges point from importer/caller/derived class to dependency/callee/base class. "
    "Unresolved or absent edges do not establish that changes or deletion are safe. "
    "External/missing imports were not resolved inside this snapshot and may refer to excluded files. "
    "Python package symbols that collide with child modules remain ambiguous. "
    "Bash relative source paths require runtime CWD, and bare names can use PATH; "
    "neither is proven by this snapshot, so they remain runtime_context without file edges."
)
JS_EXTENSIONS = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")
QUALIFIED_NAME = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$")


def _bounded(item: dict, limit: int = 512) -> dict:
    result = {}
    truncated = []
    for key, value in item.items():
        if isinstance(value, str) and len(value) > limit:
            result[key] = value[:limit]
            truncated.append(key)
        else:
            result[key] = value
    if truncated:
        result["fields_truncated"] = truncated
    return result


def _validate_depth(depth: int) -> None:
    if not isinstance(depth, int) or isinstance(depth, bool) or not 0 <= depth <= MAX_DEPTH:
        raise ValueError(f"depth must be 0..{MAX_DEPTH}")


def _validate_limit(value: int, name: str, maximum: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be 1..{maximum}")


def _page(items: list, max_results: int, offset: int) -> dict:
    _validate_limit(max_results, "max_results", 500)
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("offset must be nonnegative")
    more = offset + max_results < len(items)
    return {
        "items": items[offset : offset + max_results],
        "total": len(items),
        "truncated": more,
        "next_offset": offset + max_results if more else None,
    }


def _relative_path(path: str) -> str | None:
    value = posixpath.normpath(path.replace("\\", "/"))
    if value.startswith(("../", "/")) or value in ("..", ".") or ":" in value:
        return None
    return value


def _edge_add(edges: dict, source: str, target: str, evidence: dict) -> None:
    edge = edges.setdefault(
        (source, target),
        {"source": source, "target": target, "evidence": [], "evidence_count": 0},
    )
    edge["evidence_count"] += 1
    if len(edge["evidence"]) < MAX_EVIDENCE:
        edge["evidence"].append(_bounded(evidence))


def _edge_view(edge: dict) -> dict:
    return {
        **_bounded({"source": edge["source"], "target": edge["target"]}, 2048),
        "evidence": list(edge["evidence"]),
        "evidence_count": edge["evidence_count"],
        "evidence_truncated": edge["evidence_count"] > len(edge["evidence"]),
    }


def _adjacency(edges: dict) -> tuple[dict, dict]:
    forward, reverse = defaultdict(set), defaultdict(set)
    for source, target in edges:
        forward[source].add(target)
        reverse[target].add(source)
    return (
        {source: sorted(targets) for source, targets in forward.items()},
        {target: sorted(sources) for target, sources in reverse.items()},
    )


class DependencyAnalysis:
    """Build reusable dependency/call/base candidate graphs once per snapshot."""

    def __init__(self, files: list[dict]):
        self._files = {item["path"]: item for item in sorted(files, key=lambda f: f["path"])}
        self._edges: dict[tuple[str, str], dict] = {}
        self._unresolved: list[dict] = []
        self._bindings: dict[str, list[dict]] = defaultdict(list)
        self._symbols: dict[str, dict] = {}
        self._qualified: dict[tuple[str, str], list[str]] = defaultdict(list)
        self._legacy: dict[str, list[str]] = defaultdict(list)
        self._missing: dict[str, set[str]] = {"calls": set(), "bases": set()}
        for path, item in self._files.items():
            for symbol in item.get("symbols", []):
                sid = symbol.get("symbol_id") or f"{path}:{symbol.get('line', 0)}"
                self._symbols[sid] = {**symbol, "symbol_id": sid, "file": path}
                qualified = symbol.get("qualified_name") or symbol.get("name", "")
                self._qualified[path, qualified].append(sid)
                self._legacy[f"{path}:{symbol.get('line', 0)}"].append(sid)
                for field in self._missing:
                    if field not in symbol:
                        self._missing[field].add(sid)
            for imported in item.get("imports", []):
                candidates, status = self._resolve_import(path, item.get("language", ""), imported)
                evidence = {
                    key: imported.get(key)
                    for key in (
                        "name",
                        "path",
                        "kind",
                        "local_name",
                        "imported_name",
                        "line",
                        "dynamic",
                    )
                }
                if len(candidates) == 1 and status == "resolved":
                    target, prefix = candidates[0]
                    _edge_add(self._edges, path, target, evidence)
                    self._bindings[path].append(
                        {
                            "import": dict(imported),
                            "target": target,
                            "prefix": prefix,
                            "language": item.get("language", ""),
                        }
                    )
                else:
                    self._unresolved.append(
                        {
                            "source": path,
                            "status": status,
                            **evidence,
                            "candidates": sorted({candidate[0] for candidate in candidates}),
                        }
                    )
                    self._bindings[path].append({"import": dict(imported), "status": status})
        self._forward, self._reverse = _adjacency(self._edges)
        self._relations: dict[str, dict] = {}
        self._relation_unresolved: dict[str, list[dict]] = {}
        self._relation_adjacency: dict[str, tuple[dict, dict]] = {}
        for field in ("calls", "bases"):
            edges, unresolved = {}, []
            for sid, symbol in sorted(self._symbols.items()):
                if field == "bases" and symbol.get("kind") != "class":
                    continue
                for reference in symbol.get(field, []):
                    candidates, status = self._resolve_symbol(symbol, reference, field)
                    if len(candidates) == 1 and status == "resolved":
                        _edge_add(
                            edges,
                            sid,
                            candidates[0],
                            {
                                "reference": reference,
                                "line": symbol.get("line", 0),
                                "resolution": "static_candidate",
                            },
                        )
                    else:
                        unresolved.append(
                            {
                                "source": sid,
                                "reference": reference,
                                "status": status,
                                "candidates": candidates,
                            }
                        )
            self._relations[field] = edges
            self._relation_unresolved[field] = unresolved
            self._relation_adjacency[field] = _adjacency(edges)
        self._components: list[list[str]] | None = None

    def _python_candidates(self, module: str, root: str | None = None) -> list[str]:
        if not module or not all(part.isidentifier() for part in module.split(".")):
            return []
        stem = module.replace(".", "/")
        return sorted(
            {
                candidate
                for root in (("", "src/") if root is None else (root,))
                for candidate in (root + stem + ".py", root + stem + "/__init__.py")
                if candidate in self._files
            }
        )

    def _python_relative(self, importer: str, module: str) -> list[str]:
        dots = len(module) - len(module.lstrip("."))
        parts = posixpath.dirname(importer).split("/")
        if parts == [""] or dots > len(parts):
            return []
        package = "/".join(parts[: len(parts) - dots + 1])
        stem = posixpath.join(package, module[dots:].replace(".", "/")).rstrip("/")
        return sorted(
            candidate
            for candidate in (stem + ".py", stem + "/__init__.py")
            if candidate in self._files
        )

    def _resolve_import(
        self, importer: str, language: str, imported: dict
    ) -> tuple[list[tuple[str, str]], str]:
        path = imported.get("path", "")
        if imported.get("dynamic"):
            return [], "dynamic"
        if not isinstance(path, str) or not path:
            return [], "unsupported"
        if language == "python":
            name = imported.get("imported_name") or imported.get("name", "")
            found = []
            roots = (None,) if path.startswith(".") else ("", "src/")
            for root in roots:

                def resolve(module):
                    if root is None:
                        return self._python_relative(importer, module)
                    return self._python_candidates(module, root)

                prefix, candidates = "", []
                if imported.get("kind") == "from" and name != "*":
                    child = path + ("" if path.endswith(".") else ".") + name
                    candidates = resolve(child)
                    if candidates:
                        # A package attribute can shadow its same-named submodule.
                        # Read all snapshot symbols: importers may sort before the package.
                        for base in resolve(path):
                            if any(
                                not symbol.get("parent")
                                and (symbol.get("qualified_name") or symbol.get("name")) == name
                                for symbol in self._files[base].get("symbols", [])
                            ):
                                found.append((base, name))
                    else:
                        prefix = name
                if not candidates:
                    candidates = resolve(path)
                found.extend((candidate, prefix) for candidate in candidates)
            found = sorted(set(found))
            missing = "missing" if path.startswith(".") else "external"
        elif language in ("javascript", "typescript", "tsx", "jsx"):
            if not path.startswith(("./", "../")):
                return [], "external"
            base = _relative_path(posixpath.join(posixpath.dirname(importer), path))
            if base is None:
                return [], "missing"
            if base in self._files:
                candidates = [base]
            else:
                ext = posixpath.splitext(base)[1]
                if ext in (".js", ".jsx", ".mjs", ".cjs"):
                    replacements = {
                        ".js": (".ts", ".tsx"),
                        ".jsx": (".tsx",),
                        ".mjs": (".mts",),
                        ".cjs": (".cts",),
                    }[ext]
                    options = [base[: -len(ext)] + replacement for replacement in replacements]
                elif not ext:
                    options = [base + extension for extension in JS_EXTENSIONS]
                    options += [base + "/index" + extension for extension in JS_EXTENSIONS]
                else:
                    options = []
                candidates = sorted(candidate for candidate in options if candidate in self._files)
            name = imported.get("imported_name", "")
            prefix = "" if name == "*" else name
            found, missing = [(candidate, prefix) for candidate in candidates], "missing"
        elif language in ("bash", "shell", "sh"):
            if "dynamic" not in imported and any(
                marker in path for marker in ("$", "`", "~", "*", "?", "[")
            ):
                return [], "dynamic"
            if path.startswith("/"):
                return [], "external"
            # Source resolves against process CWD/PATH, not the script directory.
            return [], "runtime_context"
        else:
            return [], "unsupported"
        return found, "resolved" if len(found) == 1 else "ambiguous" if found else missing

    def _resolve_symbol(self, symbol: dict, reference: str, field: str) -> tuple[list[str], str]:
        if not isinstance(reference, str) or not QUALIFIED_NAME.fullmatch(reference):
            return [], "unsupported"
        path = symbol["file"]
        candidates = set(self._qualified.get((path, reference), []))
        first, _, suffix = reference.partition(".")
        if first in ("self", "cls", "this") and suffix:
            owner = symbol.get("parent")
            if owner:
                candidates.update(self._qualified.get((path, owner + "." + suffix), []))
        uncertain_binding = False
        ambiguous_binding = False
        matched_bindings = set()
        for binding in self._bindings.get(path, []):
            imported = binding["import"]
            local = imported.get("local_name")
            if not local or local != first or local == "*":
                continue
            matched_bindings.add(
                (imported.get("path"), imported.get("imported_name"), imported.get("kind"))
            )
            if "target" not in binding:
                uncertain_binding = True
                ambiguous_binding |= binding.get("status") == "ambiguous"
                continue
            prefix = binding["prefix"]
            remaining = suffix
            if binding["language"] == "python" and imported.get("kind") == "module":
                original = imported.get("imported_name") or imported.get("path", "")
                if original.startswith(local + "."):
                    required = original[len(local) + 1 :]
                    if remaining == required:
                        remaining = ""
                    elif remaining.startswith(required + "."):
                        remaining = remaining[len(required) + 1 :]
                    else:
                        continue
            qualified = ".".join(part for part in (prefix, remaining) if part)
            candidates.update(self._qualified.get((binding["target"], qualified), []))
        kinds = {"class"} if field == "bases" else {"function", "method", "class"}
        candidates = sorted(sid for sid in candidates if self._symbols[sid].get("kind") in kinds)
        if (
            ambiguous_binding
            or len(matched_bindings) > 1
            or len(candidates) > 1
            or (candidates and uncertain_binding)
        ):
            return candidates, "ambiguous"
        if len(candidates) == 1:
            return candidates, "resolved"
        return [], "unresolved"

    def _file(self, file_path: str) -> str:
        normalized = _relative_path(file_path)
        if normalized not in self._files:
            raise ValueError("File is missing, excluded, or outside the admitted snapshot")
        return normalized

    def _symbol(self, symbol_id: str) -> str:
        if symbol_id in self._symbols:
            return symbol_id
        candidates = self._legacy.get(symbol_id, [])
        if len(candidates) > 1:
            raise ValueError("Legacy symbol identifier is ambiguous; use symbol_id")
        if len(candidates) == 1:
            return candidates[0]
        raise ValueError("Symbol is missing from the admitted snapshot")

    @staticmethod
    def _diagnostics(records: list[dict], sources: set[str] | None = None) -> dict:
        selected = [record for record in records if sources is None or record["source"] in sources]
        sample = []
        for record in selected[:MAX_SAMPLE]:
            candidates = record.get("candidates", [])
            sample.append(
                {
                    **_bounded(
                        {key: value for key, value in record.items() if key != "candidates"}
                    ),
                    "candidates": [candidate[:2048] for candidate in candidates[:MAX_EVIDENCE]],
                    "candidate_count": len(candidates),
                    "candidates_truncated": len(candidates) > MAX_EVIDENCE,
                }
            )
        return {
            "unresolved": sample,
            "unresolved_count": len(selected),
            "unresolved_counts": dict(
                sorted(Counter(record["status"] for record in selected).items())
            ),
            "unresolved_truncated": len(selected) > MAX_SAMPLE,
            "semantics": SEMANTICS,
        }

    @staticmethod
    def _neighbors(
        node: str, forward: dict, reverse: dict, direction: str
    ) -> list[tuple[str, tuple[str, str]]]:
        neighbors = []
        if direction in ("out", "both"):
            neighbors.extend((target, (node, target)) for target in forward.get(node, []))
        if direction in ("in", "both"):
            neighbors.extend((source, (source, node)) for source in reverse.get(node, []))
        return sorted(set(neighbors))

    def _walk(
        self,
        root: str,
        forward: dict,
        reverse: dict,
        direction: str,
        depth: int,
        max_nodes: int,
        max_edges: int,
    ) -> tuple[dict, list, bool, bool]:
        distances, selected = {root: 0}, set()
        pending = deque([root])
        truncated = depth_limited = False
        while pending:
            node = pending.popleft()
            neighbors = self._neighbors(node, forward, reverse, direction)
            if distances[node] >= depth:
                if any(neighbor not in distances for neighbor, _ in neighbors):
                    depth_limited = True
                continue
            for neighbor, edge in neighbors:
                if edge not in selected and len(selected) >= max_edges:
                    truncated = True
                    continue
                if neighbor not in distances:
                    if len(distances) >= max_nodes:
                        truncated = True
                        continue
                    distances[neighbor] = distances[node] + 1
                    pending.append(neighbor)
                selected.add(edge)
        return distances, sorted(selected), truncated, depth_limited

    def importers(self, file_path: str, max_results: int = 100, offset: int = 0) -> dict:
        """Return direct admitted importers, preserving import evidence."""
        path = self._file(file_path)
        sources = self._reverse.get(path, [])
        items = [
            {"path": source[:2048], **_edge_view(self._edges[source, path])} for source in sources
        ]
        result = _page(items, max_results, offset)
        result["importers"] = result.pop("items")
        return {"file_path": path[:2048], **result, **self._diagnostics(self._unresolved)}

    def graph(
        self,
        file_path: str | None = None,
        direction: str = "imports",
        depth: int = 1,
        max_nodes: int = 200,
        max_edges: int = 500,
    ) -> dict:
        """Return a bounded graph; without a root, include the whole snapshot."""
        _validate_depth(depth)
        _validate_limit(max_nodes, "max_nodes", 1000)
        _validate_limit(max_edges, "max_edges", 5000)
        directions = {"imports": "out", "importers": "in", "both": "both"}
        if direction not in directions:
            raise ValueError("direction must be imports, importers, or both")
        if file_path is None:
            distances = {path: 0 for path in list(self._files)[:max_nodes]}
            candidates = [
                edge for edge in sorted(self._edges) if all(node in distances for node in edge)
            ]
            selected = candidates[:max_edges]
            truncated = len(distances) < len(self._files) or len(selected) < len(self._edges)
            depth_limited = False
        else:
            path = self._file(file_path)
            distances, selected, truncated, depth_limited = self._walk(
                path,
                self._forward,
                self._reverse,
                directions[direction],
                depth,
                max_nodes,
                max_edges,
            )
        nodes = [
            {
                **_bounded({"path": path, "language": self._files[path].get("language", "")}, 2048),
                "distance": distance,
            }
            for path, distance in sorted(distances.items(), key=lambda pair: (pair[1], pair[0]))
        ]
        return {
            "nodes": nodes,
            "edges": [_edge_view(self._edges[edge]) for edge in selected],
            "direction": direction,
            "depth": depth,
            "truncated": truncated,
            "depth_limited": depth_limited,
            "total_files": len(self._files),
            "total_edges": len(self._edges),
            **self._diagnostics(self._unresolved, None if file_path is None else set(distances)),
        }

    def blast_radius(
        self, file_path: str, depth: int = 3, max_results: int = 100, offset: int = 0
    ) -> dict:
        """Return reachable importers; this is not a prediction of runtime impact."""
        _validate_depth(depth)
        path = self._file(file_path)
        distances = {path: 0}
        pending = deque([path])
        depth_limited = False
        while pending:
            current = pending.popleft()
            for source in self._reverse.get(current, []):
                if source in distances:
                    continue
                if distances[current] >= depth:
                    depth_limited = True
                    continue
                distances[source] = distances[current] + 1
                pending.append(source)
        items = [
            {"path": source[:2048], "distance": distance}
            for source, distance in sorted(distances.items(), key=lambda pair: (pair[1], pair[0]))
            if source != path
        ]
        result = _page(items, max_results, offset)
        result["affected_files"] = result.pop("items")
        return {
            "file_path": path[:2048],
            "depth": depth,
            "depth_limited": depth_limited,
            **result,
            **self._diagnostics(self._unresolved),
        }

    def _strong_components(self) -> list[list[str]]:
        # Iterative Kosaraju avoids Python recursion limits on generated repositories.
        visited, finished = set(), []
        for root in self._files:
            if root in visited:
                continue
            visited.add(root)
            pending = [(root, iter(self._forward.get(root, [])))]
            while pending:
                node, neighbors = pending[-1]
                neighbor = next(neighbors, None)
                if neighbor is None:
                    finished.append(node)
                    pending.pop()
                elif neighbor not in visited:
                    visited.add(neighbor)
                    pending.append((neighbor, iter(self._forward.get(neighbor, []))))
        visited, components = set(), []
        for root in reversed(finished):
            if root in visited:
                continue
            component, pending = [], [root]
            visited.add(root)
            while pending:
                node = pending.pop()
                component.append(node)
                for neighbor in self._reverse.get(node, []):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        pending.append(neighbor)
            if len(component) > 1 or (root, root) in self._edges:
                components.append(sorted(component))
        return sorted(components)

    def cycles(self, max_results: int = 50, offset: int = 0) -> dict:
        """Return cyclic strongly connected components, including self imports."""
        if self._components is None:
            self._components = self._strong_components()
        result = _page(self._components, max_results, offset)
        result["cycles"] = [
            {
                "files": [path[:2048] for path in component[:100]],
                "file_count": len(component),
                "files_truncated": len(component) > 100,
            }
            for component in result.pop("items")
        ]
        return {**result, **self._diagnostics(self._unresolved)}

    def _hierarchy(
        self, symbol_id: str, field: str, direction: str, depth: int, max_nodes: int
    ) -> dict:
        _validate_depth(depth)
        _validate_limit(max_nodes, "max_nodes", 500)
        directions = {"both": "both"}
        directions.update(
            {"callees": "out", "callers": "in"}
            if field == "calls"
            else {"bases": "out", "subclasses": "in"}
        )
        if direction not in directions:
            raise ValueError(f"direction must be one of {', '.join(sorted(directions))}")
        sid = self._symbol(symbol_id)
        if field == "bases" and self._symbols[sid].get("kind") != "class":
            raise ValueError("class_hierarchy requires a class symbol")
        forward, reverse = self._relation_adjacency[field]
        distances, selected, truncated, depth_limited = self._walk(
            sid, forward, reverse, directions[direction], depth, max_nodes, 1000
        )
        nodes = []
        for node, distance in sorted(distances.items(), key=lambda pair: (pair[1], pair[0])):
            symbol = self._symbols[node]
            nodes.append(
                {
                    **_bounded(
                        {
                            key: symbol.get(key)
                            for key in (
                                "symbol_id",
                                "name",
                                "qualified_name",
                                "kind",
                                "file",
                                "line",
                                "end_line",
                            )
                        }
                    ),
                    "distance": distance,
                }
            )
        missing = sum(
            field == "calls" or self._symbols[node].get("kind") == "class"
            for node in self._missing[field]
        )
        limitations = [
            "Only syntactic metadata and unambiguous local/imported names are resolved; dynamic dispatch, reexports, default-export aliases, runtime imports and external symbols can be unresolved."
        ]
        if missing:
            limitations.append(
                f"{missing} snapshot symbols lack {field} metadata; source text is not used as a substitute."
            )
        return {
            "symbol_id": sid[:2048],
            "nodes": nodes,
            "edges": [_edge_view(self._relations[field][edge]) for edge in selected],
            "direction": direction,
            "depth": depth,
            "truncated": truncated,
            "depth_limited": depth_limited,
            "metadata_missing_count": missing,
            "limitations": limitations,
            **self._diagnostics(self._relation_unresolved[field], set(distances)),
        }

    def call_hierarchy(
        self, symbol_id: str, direction: str = "both", depth: int = 1, max_nodes: int = 100
    ) -> dict:
        """Return conservative caller/callee candidates, never text references."""
        return self._hierarchy(symbol_id, "calls", direction, depth, max_nodes)

    def class_hierarchy(
        self, symbol_id: str, direction: str = "both", depth: int = 1, max_nodes: int = 100
    ) -> dict:
        """Return candidate inheritance edges from derived classes to bases."""
        return self._hierarchy(symbol_id, "bases", direction, depth, max_nodes)
