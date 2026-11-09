"""Snapshot-consistent local search, source retrieval and structural analysis."""

from __future__ import annotations

import copy
import threading
import time
from collections import Counter
from contextvars import ContextVar
from pathlib import Path, PurePosixPath

import regex

from .indexer import match_type, path_matches
from .parser import SymbolInfo
from .retrieval import (
    Snapshot,
    bounded_response,
    decode_cursor,
    encode_cursor,
    pinned_tool,
    serialized_size,
    validate_budget,
)
from .store import IndexStore
from .workspace import Workspace

MAX_CONTENT = 64_000


def page(items: list, limit: int, offset: int) -> tuple[list, dict]:
    if not 1 <= limit <= 500 or offset < 0:
        raise ValueError("max_results must be 1..500 and offset must be nonnegative")
    truncated = len(items) > offset + limit
    return items[offset : offset + limit], {
        "truncated": truncated,
        "next_offset": offset + limit if truncated else None,
    }


def bounded_fields(item: dict, caps: dict[str, int]) -> dict:
    result = dict(item)
    clipped = []
    for key, limit in caps.items():
        value = result.get(key)
        if isinstance(value, str) and len(value) > limit:
            result[key] = value[:limit]
            clipped.append(key)
    if clipped:
        result["fields_truncated"] = clipped
    return result


def symbol_dict(symbol: SymbolInfo | dict) -> dict:
    item = vars(symbol) if isinstance(symbol, SymbolInfo) else symbol
    result = bounded_fields(
        {**item, "id": f"{item['file']}:{item['line']}"},
        {
            "name": 500,
            "qualified_name": 1000,
            "parent": 1000,
            "signature": 1000,
            "summary": 500,
            "docstring": 2000,
        },
    )
    for key in ("decorators", "bases", "calls"):
        values = result.get(key, [])
        result[key] = [value[:500] for value in values[:30]]
        if len(values) > 30 or any(len(value) > 500 for value in values):
            result.setdefault("fields_truncated", []).append(key)
    return result


class CodeSearchService:
    def __init__(self, workspace: Path, data_dir: Path, scan_interval: float = 2, **limits):
        if scan_interval < 0:
            raise ValueError("scan_interval must be nonnegative")
        self.workspace = Workspace(workspace, data_dir, **limits)
        self.store = IndexStore(self.workspace)
        self.scan_interval = scan_interval
        self._cached: Snapshot | None = None
        self._lock = threading.RLock()
        self._request = ContextVar(f"codesearch_request_{id(self)}", default=None)

    def close(self):
        self.store.close()

    def _view(self, repo: str = "local") -> Snapshot:
        self.workspace.validate_repo(repo)
        request = self._request.get()
        if request is not None and request["snapshot"] is not None:
            return request["snapshot"]
        with self._lock:
            report = self.store.refresh(interval=self.scan_interval)
            if self._cached is None or self._cached.generation != self.store.generation:
                raw = self.store.snapshot()
                self._cached = Snapshot(
                    raw["generation"], raw["report"], tuple(raw["files"]), raw.get("changes", {})
                )
            # Share immutable records/lazy indexes; the report is copied per request.
            view = copy.copy(self._cached)
            if report.get("generation", view.generation) == view.generation:
                view.report = copy.deepcopy(report)
            if request is not None:
                request["snapshot"] = view
            return view

    def _metadata(self, view: Snapshot) -> dict:
        report = view.report
        return {
            "generation": view.generation,
            "coverage": report.get("coverage", {"status": report.get("status", "unknown")}),
            "index_truncated": report.get("truncated", False),
        }

    def _file(self, repo: str, file_path: str) -> dict:
        view = self._view(repo)
        path = self.workspace.relative_path(file_path)
        record = view.by_path.get(path)
        if record is None:
            raise ValueError(
                "File is missing, excluded, binary, oversized, or outside the indexed snapshot"
            )
        return record

    def _symbol(self, value: str, view: Snapshot) -> SymbolInfo:
        exact = [symbol for symbol in view.symbols if getattr(symbol, "symbol_id", "") == value]
        if not exact:
            exact = [s for s in view.symbols if f"{s.file}:{s.line}" == value]
        if not exact:
            raise ValueError("Symbol not found")
        if len(exact) != 1:
            raise ValueError("Ambiguous legacy symbol ID; use symbol_id")
        return exact[0]

    def index_repo(self, url: str = ".", use_ai_summaries: bool = False) -> dict:
        """Compatibility alias for indexing the configured local folder; remote URLs unsupported."""
        self.workspace.validate_repo(url)
        return self.refresh_index()

    def index_directory(self, path: str = ".") -> dict:
        """Index the configured workspace; selecting arbitrary host paths is not allowed."""
        self.workspace.validate_repo(path)
        return self.refresh_index()

    def refresh_index(self, force: bool = False) -> dict:
        """Scan immediately. Force verifies all content hashes and reparses every admitted file."""
        return self.store.refresh(force=force, interval=0)

    @pinned_tool
    def get_index_status(self) -> dict:
        """Report generation, coverage, persistent diagnostics and scan/read counters."""
        view = self._view()
        return {
            **view.report,
            "workspace": self.workspace.root.name,
            "symbols": len(view.symbols),
            "scan_interval_seconds": self.scan_interval,
            "limits": {
                "file_bytes": self.workspace.max_file_bytes,
                "files": self.workspace.max_files,
                "total_bytes": self.workspace.max_total_bytes,
            },
        }

    @pinned_tool
    def get_project_summary(self, repo: str = "local") -> dict:
        """Get languages, directories and likely entry points before exploring."""
        view = self._view(repo)
        hints = {
            "pyproject.toml",
            "package.json",
            "go.mod",
            "Cargo.toml",
            "pom.xml",
            "README.md",
            "main.py",
            "app.py",
            "main.go",
            "Containerfile",
            "Dockerfile",
        }
        return {
            "repo": "local",
            "workspace": self.workspace.root.name,
            "files": len(view.files),
            "symbols": len(view.symbols),
            "languages": dict(Counter(row["language"] for row in view.files)),
            "directories": dict(
                Counter(
                    row["path"].split("/")[0] if "/" in row["path"] else "." for row in view.files
                ).most_common(30)
            ),
            "entry_points": [
                row["path"] for row in view.files if PurePosixPath(row["path"]).name in hints
            ][:30],
            "truncated": view.report.get("truncated", False),
            "reference_semantics": "textual identifiers and conservative static candidates; not compiler-resolved",
        }

    @pinned_tool
    def get_repo_outline(
        self, repo: str = "local", max_results: int = 100, offset: int = 0
    ) -> dict:
        """Directory-level file/language/symbol counts, with deterministic pagination."""
        view = self._view(repo)
        directories = {}
        for row in view.files:
            name = str(PurePosixPath(row["path"]).parent)
            entry = directories.setdefault(
                name, {"path": name, "files": 0, "symbols": 0, "languages": {}}
            )
            entry["files"] += 1
            entry["symbols"] += len(row["symbols"])
            entry["languages"][row["language"]] = entry["languages"].get(row["language"], 0) + 1
        selected, pagination = page(
            [directories[key] for key in sorted(directories)], max_results, offset
        )
        return {"repo": repo, "directories": selected, **pagination}

    @pinned_tool
    def get_file_tree(
        self,
        repo: str = "local",
        max_results: int = 200,
        offset: int = 0,
        path_prefix: str = "",
        language: str | None = None,
    ) -> dict:
        """Nested tree; path/language filters apply before pagination (500 files maximum)."""
        view = self._view(repo)
        prefix = self.workspace.relative_path(path_prefix).rstrip("/") if path_prefix else ""
        admitted = [
            row
            for row in view.files
            if (not prefix or row["path"] == prefix or row["path"].startswith(prefix + "/"))
            and (language is None or row["language"] == language)
        ]
        files, pagination = page(admitted, max_results, offset)
        tree, directories = [], {}
        for row in files:
            parts, children = row["path"].split("/"), tree
            for index in range(len(parts) - 1):
                path = "/".join(parts[: index + 1])
                if path not in directories:
                    node = {"path": path, "type": "dir", "children": []}
                    directories[path] = node
                    children.append(node)
                children = directories[path]["children"]
            children.append(
                {
                    "path": row["path"],
                    "type": "file",
                    "language": row["language"],
                    "size": row["size"],
                }
            )
        return {"repo": repo, "tree": tree, **pagination}

    @pinned_tool
    def get_file_outline(
        self, repo: str = "local", file_path: str = "", max_results: int = 100, offset: int = 0
    ) -> dict:
        """Definitions with qualified names, stable IDs, ownership, decorators and exact ranges."""
        row = self._file(repo, file_path)
        selected, pagination = page(row["symbols"], max_results, offset)
        return {"file": row["path"], "symbols": [symbol_dict(s) for s in selected], **pagination}

    @pinned_tool
    def search_symbols(
        self,
        repo: str = "local",
        query: str = "",
        max_results: int = 10,
        kind: str | None = "function",
        detail_level: str = "standard",
        offset: int = 0,
        language: str | None = None,
        file_pattern: str | None = None,
        decorator: str | None = None,
    ) -> dict:
        """Exact-name-first BM25 search. Filters precede pagination; kind=null includes all kinds."""
        page([], max_results, offset)
        if len(query) > 2000:
            raise ValueError("query must not exceed 2000 characters")
        if detail_level not in {"standard", "compact", "full"}:
            raise ValueError("detail_level must be compact, standard, or full")
        view = self._view(repo)
        found = view.index.search(
            query, offset + max_results + 1, kind, language, file_pattern, decorator
        )
        selected, pagination = page(found, max_results, offset)
        results = [{**symbol_dict(s), "match_type": match_type(s, query)} for s in selected]
        if detail_level != "full":
            for result in results:
                for key in ("docstring", "calls", "bases"):
                    result.pop(key, None)
        if detail_level == "compact":
            results = [
                {
                    key: value
                    for key, value in row.items()
                    if key
                    in {
                        "id",
                        "symbol_id",
                        "name",
                        "qualified_name",
                        "file",
                        "line",
                        "end_line",
                        "kind",
                        "match_type",
                    }
                }
                for row in results
            ]
        return {"result_count": len(results), "results": results, **pagination}

    @pinned_tool
    def get_file_content(
        self,
        repo: str = "local",
        file_path: str = "",
        start_line: int = 1,
        end_line: int | None = None,
        max_chars: int = MAX_CONTENT,
        cursor: str | None = None,
    ) -> dict:
        """Read up to 500 lines/64k source characters; next_cursor resumes inside a clipped line."""
        if start_line < 1 or (end_line is not None and end_line < start_line):
            raise ValueError("Expected 1 <= start_line <= end_line")
        if not 1 <= max_chars <= MAX_CONTENT:
            raise ValueError("max_chars must be 1..64000")
        row = self._file(repo, file_path)
        view = self._view(repo)
        text = row["content"].replace("\r\n", "\n")
        lines = text.splitlines(keepends=True)
        total = len(lines)
        start = sum(map(len, lines[: start_line - 1]))
        requested_end = sum(map(len, lines[:end_line])) if end_line is not None else len(text)
        if cursor:
            state = decode_cursor(cursor)
            if state.get("g") != view.generation or state.get("f") != row["path"]:
                raise ValueError(
                    "Continuation is stale or belongs to another file; restart the read"
                )
            start, requested_end = state.get("p"), state.get("e")
            if (
                type(start) is not int
                or type(requested_end) is not int
                or not 0 <= start <= requested_end <= len(text)
            ):
                raise ValueError("Invalid continuation offsets")
        line_cap = sum(map(len, text[start:requested_end].splitlines(keepends=True)[:500]))
        stop = min(requested_end, start + max_chars, start + line_cap)
        content = text[start:stop]
        truncated = stop < requested_end
        actual_start_line = text[:start].count("\n") + 1
        actual_end_line = text[:stop].count("\n") + (1 if stop and text[stop - 1] != "\n" else 0)
        return {
            "file": row["path"],
            "content": content,
            "start_line": actual_start_line,
            "end_line": actual_end_line,
            "total_lines": total,
            "truncated": truncated,
            "line_truncated": bool(truncated and content and content[-1] != "\n"),
            "next_start_line": text[:stop].count("\n") + 1 if truncated else None,
            "next_cursor": encode_cursor(
                {"g": view.generation, "f": row["path"], "p": stop, "e": requested_end}
            )
            if truncated
            else None,
        }

    @pinned_tool
    def find_file(
        self, repo: str = "local", pattern: str = "", max_results: int = 20, offset: int = 0
    ) -> dict:
        """Find filename substring or glob, including root-level ** matches."""
        if len(pattern) > 2000:
            raise ValueError("pattern too long")
        is_glob = any(character in pattern for character in "*?[")
        found = [
            {"path": row["path"], "language": row["language"], "size": row["size"]}
            for row in self._view(repo).files
            if (
                path_matches(row["path"], pattern)
                if is_glob
                else pattern.casefold() in PurePosixPath(row["path"]).name.casefold()
            )
        ]
        selected, pagination = page(found, max_results, offset)
        return {"repo": repo, "matches": selected, **pagination}

    @pinned_tool
    def grep_content(
        self,
        repo: str = "local",
        pattern: str = "",
        path_glob: str | None = None,
        max_results: int = 20,
        offset: int = 0,
        is_regex: bool = False,
        case_sensitive: bool = False,
        context_lines: int = 0,
        max_chars: int = 32_000,
    ) -> dict:
        """Literal or timed regex search with enclosing symbols, context and total JSON budget."""
        page([], max_results, offset)
        validate_budget(max_chars)
        if not pattern or len(pattern) > 2000 or not 0 <= context_lines <= 10:
            raise ValueError("pattern must have 1..2000 characters and context_lines must be 0..10")
        try:
            compiled = (
                regex.compile(pattern, 0 if case_sensitive else regex.IGNORECASE)
                if is_regex
                else None
            )
        except regex.error as exc:
            raise ValueError("Invalid regular expression") from exc
        view = self._view(repo)
        rows = [row for row in view.files if path_matches(row["path"], path_glob)]
        candidates, skipped, files_searched, timed_out = [], 0, 0, False
        deadline = time.monotonic() + 2.0
        needle = pattern if case_sensitive else pattern.casefold()
        stop = False
        for row in rows:
            files_searched += 1
            lines = row["content"].splitlines()
            for index, text in enumerate(lines):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out, stop = True, True
                    break
                try:
                    matched = (
                        bool(compiled.search(text, timeout=min(0.02, remaining)))
                        if compiled
                        else needle in (text if case_sensitive else text.casefold())
                    )
                except TimeoutError:
                    timed_out, stop = True, True
                    break
                if not matched:
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                entry = {
                    "file": row["path"],
                    "line": index + 1,
                    "content": text[:2000],
                    "content_truncated": len(text) > 2000,
                }
                if context_lines:
                    entry["context"] = [
                        line[:1000]
                        for line in lines[max(0, index - context_lines) : index + context_lines + 1]
                    ]
                    entry["context_start_line"] = max(0, index - context_lines) + 1
                enclosing = [
                    s
                    for s in row["symbols"]
                    if s["line"] <= index + 1 <= max(s["line"], s.get("end_line", 0))
                ]
                if enclosing:
                    closest = min(
                        enclosing,
                        key=lambda s: (
                            max(s["line"], s.get("end_line", 0)) - s["line"],
                            -s["line"],
                        ),
                    )
                    entry["symbol"] = {
                        key: symbol_dict(closest)[key]
                        for key in ("id", "symbol_id", "name", "line", "end_line")
                        if key in closest or key == "id"
                    }
                candidates.append(entry)
                if len(candidates) > max_results:
                    stop = True
                    break
            if stop:
                break
        pagination_cut = len(candidates) > max_results
        payload = {
            "repo": repo,
            "pattern": pattern[:500],
            "files_searched": files_searched,
            "scope_empty": not rows,
            "timed_out": timed_out,
            # Reserve at least four characters: final null can be longer than a small integer.
            "next_offset": max(9999, offset + min(len(candidates), max_results)),
            "truncated": pagination_cut or timed_out,
            "_meta": self._metadata(view),
        }
        result = bounded_response(payload, candidates[:max_results], max_chars, "matches")
        result["truncated"] = result["truncated"] or pagination_cut or timed_out
        result["next_offset"] = (
            offset + len(result["matches"]) if result["truncated"] and result["matches"] else None
        )
        for _ in range(4):
            result["budget"]["used_chars"] = serialized_size(result)
        return result

    @pinned_tool
    def find_references(
        self,
        repo: str = "local",
        name: str = "",
        path_glob: str | None = None,
        max_results: int = 20,
        offset: int = 0,
    ) -> dict:
        """Textual identifier occurrences, including declarations/comments; not compiler references."""
        if not name:
            self.workspace.validate_repo(repo)
            return {
                "repo": repo,
                "name": name,
                "references": [],
                "truncated": False,
                "next_offset": None,
            }
        if len(name) > 1000:
            raise ValueError("name too long")
        result = self.grep_content(
            repo,
            r"(?<!\w)" + regex.escape(name) + r"(?!\w)",
            path_glob,
            max_results,
            offset,
            is_regex=True,
            case_sensitive=True,
        )
        payload = {
            key: value
            for key, value in {**result, "name": name}.items()
            if key not in {"matches", "pattern", "budget"}
        }
        return bounded_response(payload, result["matches"], 32_000, "references")

    @pinned_tool
    def get_file_imports(
        self,
        repo: str = "local",
        file_path: str = "",
        max_results: int = 100,
        offset: int = 0,
        detailed: bool = False,
    ) -> dict:
        """AST import records; detailed mode includes original/local names and source evidence."""
        row = self._file(repo, file_path)
        selected, pagination = page(row["imports"], max_results, offset)
        imports = []
        for item in selected:
            record = item if detailed else {key: item[key] for key in ("name", "path", "kind")}
            imports.append(
                bounded_fields(
                    record, {"name": 500, "path": 1000, "local_name": 500, "imported_name": 500}
                )
            )
        return {"file": row["path"], "imports": imports, **pagination}

    @pinned_tool
    def search_text(
        self,
        query: str = "",
        repo: str = "local",
        max_results: int = 20,
        offset: int = 0,
        language: str | None = None,
        file_pattern: str | None = None,
    ) -> dict:
        """FTS5 ranked lexical file search; all query words required, filters precede pagination."""
        page([], max_results, offset)
        if len(query) > 2000:
            raise ValueError("query too long")
        self.workspace.validate_repo(repo)
        self.store.refresh(interval=self.scan_interval)
        found, generation, report = self.store.search_text_snapshot(
            query, max_results + 1, offset, language=language, path_glob=file_pattern
        )
        for row in found:
            row["snippet_truncated"] = len(row["snippet"]) > 2000
            row["snippet"] = row["snippet"][:2000]
        results, pagination = page(found, max_results, 0)
        if pagination["truncated"]:
            pagination["next_offset"] = offset + max_results
        return {
            "results": results,
            "result_count": len(results),
            **pagination,
            "_meta": {
                "generation": generation,
                "coverage": report.get("coverage"),
                "index_truncated": report.get("truncated", False),
            },
        }

    @pinned_tool
    def get_symbol_context(
        self,
        name: str,
        repo: str = "local",
        file_path: str | None = None,
        line: int | None = None,
        context_lines: int = 3,
    ) -> dict:
        """Legacy name-based definition lookup; one pinned snapshot keeps coordinates and source aligned."""
        if not 0 <= context_lines <= 50:
            raise ValueError("context_lines must be 0..50")
        view = self._view(repo)
        path = self.workspace.relative_path(file_path) if file_path else None
        found = [
            s
            for s in view.symbols
            if (s.name == name or getattr(s, "qualified_name", "") == name)
            and (path is None or s.file == path)
            and (line is None or s.line == line)
        ]
        if not found:
            raise ValueError("Symbol not found")
        if len(found) > 1:
            raise ValueError("Ambiguous symbol; specify file_path and line")
        symbol = found[0]
        result = self.get_file_content(
            repo,
            symbol.file,
            max(1, symbol.line - context_lines),
            max(symbol.line, symbol.end_line) + context_lines,
        )
        return {"symbol": symbol_dict(symbol), **result}

    def _source_entry(
        self, symbol: SymbolInfo, view: Snapshot, compact: bool = False, context_lines: int = 0
    ) -> dict:
        row = view.by_path[symbol.file]
        result = {
            key: value
            for key, value in symbol_dict(symbol).items()
            if key
            in {
                "id",
                "symbol_id",
                "name",
                "qualified_name",
                "file",
                "line",
                "end_line",
                "signature",
                "kind",
                "fields_truncated",
            }
        }
        if compact:
            return result
        raw = row["content"].encode("utf-8")
        start, end = getattr(symbol, "start_byte", 0), getattr(symbol, "end_byte", 0)
        if context_lines or not 0 <= start < end <= len(raw):
            lines = row["content"].replace("\r\n", "\n").splitlines(keepends=True)
            first = max(1, (symbol.source_start_line or symbol.line) - context_lines)
            last = max(symbol.line, symbol.end_line) + context_lines
            start = sum(map(len, lines[: first - 1]))
            source = "".join(lines[first - 1 : last])
            source_start_line = first
        else:
            source = raw[start:end].decode("utf-8").replace("\r\n", "\n")
            start = len(raw[:start].decode("utf-8").replace("\r\n", "\n"))
            source_start_line = symbol.source_start_line or symbol.line
        state = {"g": view.generation, "f": symbol.file, "p": start, "e": start + len(source)}
        result["source_cursor"] = encode_cursor(state)
        result["source_truncated"] = len(source) > MAX_CONTENT
        result["next_cursor"] = (
            encode_cursor({**state, "p": start + MAX_CONTENT})
            if result["source_truncated"]
            else None
        )
        result["source"] = source[:MAX_CONTENT]
        result["source_start_line"] = source_start_line
        return result

    @pinned_tool
    def get_symbol_source(
        self,
        symbol_ids: list[str],
        repo: str = "local",
        context_lines: int = 0,
        max_chars: int = MAX_CONTENT,
    ) -> dict:
        """Batch source by stable IDs (1..50). Partial errors and ordered deduplication are explicit."""
        if not 1 <= len(symbol_ids) <= 50 or not 0 <= context_lines <= 50:
            raise ValueError("Provide 1..50 IDs and context_lines between 0 and 50")
        validate_budget(max_chars)
        view = self._view(repo)
        entries, errors = [], []
        for value in dict.fromkeys(symbol_ids):
            try:
                entries.append(
                    self._source_entry(self._symbol(value, view), view, context_lines=context_lines)
                )
            except ValueError as exc:
                errors.append({"symbol_id": value[:200], "error": str(exc)})
        return bounded_response(
            {"errors": errors[:10], "error_count": len(errors), "_meta": self._metadata(view)},
            entries,
            max_chars,
        )

    @pinned_tool
    def get_context_bundle(
        self,
        symbol_ids: list[str],
        repo: str = "local",
        include_imports: bool = True,
        max_chars: int = 32_000,
        compact: bool = False,
    ) -> dict:
        """Definitions/imports under a JSON character budget; resume clipped source via next_cursor."""
        if not 1 <= len(symbol_ids) <= 50:
            raise ValueError("Provide 1..50 symbol IDs")
        validate_budget(max_chars)
        view = self._view(repo)
        entries, errors, imports = [], [], {}
        for value in dict.fromkeys(symbol_ids):
            try:
                symbol = self._symbol(value, view)
                entries.append(self._source_entry(symbol, view, compact=compact))
                if include_imports and symbol.file not in imports:
                    imports[symbol.file] = [
                        bounded_fields(
                            item,
                            {"name": 100, "path": 300, "local_name": 100, "imported_name": 100},
                        )
                        for item in view.by_path[symbol.file]["imports"][:10]
                    ]
            except ValueError as exc:
                errors.append({"symbol_id": value[:200], "error": str(exc)})
        payload = {
            "errors": errors[:5],
            "error_count": len(errors),
            "imports": imports,
            "omitted_import_files": 0,
            "omitted_imports": sum(
                max(0, len(view.by_path[path]["imports"]) - len(records))
                for path, records in imports.items()
            ),
            "_meta": self._metadata(view),
        }
        while serialized_size(payload) > max_chars // 2 and payload["imports"]:
            payload["omitted_imports"] += len(
                payload["imports"].pop(next(reversed(payload["imports"])))
            )
            payload["omitted_import_files"] += 1
        payload["truncated"] = bool(payload["omitted_imports"])
        return bounded_response(payload, entries, max_chars)

    @pinned_tool
    def assemble_task_context(
        self, task: str, repo: str = "local", max_chars: int = 32_000, max_symbols: int = 8
    ) -> dict:
        """Assemble a lexical-query context capsule in one call; no AI inference or token estimate."""
        if not task.strip() or len(task) > 2000 or not 1 <= max_symbols <= 30:
            raise ValueError("task needs 1..2000 characters and max_symbols must be 1..30")
        view = self._view(repo)
        symbols = view.index.search(task, limit=max_symbols, kind=None)
        if not symbols:
            return bounded_response(
                {
                    "query": task[:300],
                    "basis": "lexical_symbol_ranking",
                    "note": "No matching indexed symbols; this is not proof of absence",
                    "_meta": self._metadata(view),
                },
                [],
                max_chars,
            )
        result = self.get_context_bundle(
            [s.symbol_id for s in symbols], repo, True, max_chars, False
        )
        # Query attribution belongs inside the same enforced budget.
        payload = {key: value for key, value in result.items() if key not in {"results", "budget"}}
        payload["query"] = task[:300]
        payload["basis"] = "lexical_symbol_ranking"
        return bounded_response(payload, result["results"], max_chars)

    @pinned_tool
    def find_importers(
        self, file_path: str, repo: str = "local", max_results: int = 100, offset: int = 0
    ) -> dict:
        """Direct local importers with evidence and unresolved boundaries."""
        row = self._file(repo, file_path)
        return self._view(repo).relations.importers(row["path"], max_results, offset)

    @pinned_tool
    def get_dependency_graph(
        self,
        file_path: str | None = None,
        repo: str = "local",
        direction: str = "imports",
        depth: int = 1,
        max_nodes: int = 200,
        max_edges: int = 500,
    ) -> dict:
        """Bounded static file graph; unresolved/dynamic imports are not invented edges."""
        view = self._view(repo)
        path = self._file(repo, file_path)["path"] if file_path else None
        return view.relations.graph(path, direction, depth, max_nodes, max_edges)

    @pinned_tool
    def get_blast_radius(
        self,
        file_path: str,
        repo: str = "local",
        depth: int = 3,
        max_results: int = 100,
        offset: int = 0,
    ) -> dict:
        """Potential import-based impact, not a guarantee of runtime usage or deletion safety."""
        row = self._file(repo, file_path)
        return self._view(repo).relations.blast_radius(row["path"], depth, max_results, offset)

    @pinned_tool
    def get_dependency_cycles(
        self, repo: str = "local", max_results: int = 50, offset: int = 0
    ) -> dict:
        """Strongly connected local import groups, including explicit self-imports."""
        return self._view(repo).relations.cycles(max_results, offset)

    @pinned_tool
    def get_call_hierarchy(
        self,
        symbol_id: str,
        repo: str = "local",
        direction: str = "both",
        depth: int = 1,
        max_nodes: int = 100,
    ) -> dict:
        """Syntactic call candidates with conservative static resolution and uncertainty."""
        view = self._view(repo)
        symbol = self._symbol(symbol_id, view)
        return view.relations.call_hierarchy(symbol.symbol_id, direction, depth, max_nodes)

    @pinned_tool
    def get_class_hierarchy(
        self,
        symbol_id: str,
        repo: str = "local",
        direction: str = "both",
        depth: int = 1,
        max_nodes: int = 100,
    ) -> dict:
        """Declared inheritance candidates; dynamic and ambiguous bases remain unresolved."""
        view = self._view(repo)
        symbol = self._symbol(symbol_id, view)
        return view.relations.class_hierarchy(symbol.symbol_id, direction, depth, max_nodes)

    @pinned_tool
    def get_index_changes(self) -> dict:
        """Last meaningful indexed-file delta, persisted across restarts; this is not Git history."""
        return copy.deepcopy(self._view().changes)
