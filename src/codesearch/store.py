"""Transactional SQLite snapshots; queries use only admitted files."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import asdict

from . import parser
from .imports import extract_import_details
from .parser import EXTENSION_TO_LANGUAGE, extract_symbols
from .workspace import SourceFile, Workspace

SCHEMA_VERSION = "2"
MAX_CHANGES = 100


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _parser_revision() -> str:
    return str(parser.PARSER_REVISION)


def _decode_file(row) -> dict:
    item = dict(row)
    for key in ("symbols", "imports", "fingerprint", "diagnostics"):
        item[key] = json.loads(item[key])
    return item


class IndexStore:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.lock = threading.RLock()
        workspace.data_dir.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            workspace.data_dir / "index.sqlite3", timeout=30, check_same_thread=False
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        try:
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                self.connection.execute(
                    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                identity = str(workspace.root) + ":" + os.environ.get("CODESEARCH_WORKSPACE_ID", "")
                existing = self._metadata()
                if existing.get("workspace", identity) != identity:
                    raise ValueError(
                        "Index workspace mismatch; use a separate data directory for this workspace"
                    )
                if existing.get("schema", "1") not in {"1", SCHEMA_VERSION}:
                    raise ValueError("Unsupported index schema; use a separate data directory")
                self.connection.execute("""
                    CREATE TABLE IF NOT EXISTS files (
                        path TEXT PRIMARY KEY, language TEXT, size INTEGER, mtime_ns INTEGER,
                        digest TEXT, content TEXT, symbols TEXT, imports TEXT
                    )
                """)
                columns = {row[1] for row in self.connection.execute("PRAGMA table_info(files)")}
                for name, definition in {
                    "fingerprint": "TEXT NOT NULL DEFAULT 'null'",
                    "diagnostics": "TEXT NOT NULL DEFAULT '[]'",
                    "symbol_count": "INTEGER NOT NULL DEFAULT 0",
                    "import_count": "INTEGER NOT NULL DEFAULT 0",
                    "parser_revision": "TEXT NOT NULL DEFAULT ''",
                }.items():
                    if name not in columns:
                        self.connection.execute(f"ALTER TABLE files ADD COLUMN {name} {definition}")
                self.connection.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS file_search USING fts5(path, content)"
                )
                self._set_meta("workspace", identity)
                self._set_meta("schema", SCHEMA_VERSION)
        except BaseException:
            self.connection.close()
            raise
        self.last_scan = 0.0
        with self.connection:
            self.connection.execute("BEGIN")
            self.generation, self.last_report = self._state(self._metadata())

    def _metadata(self) -> dict[str, str]:
        return dict(self.connection.execute("SELECT key,value FROM meta"))

    def _set_meta(self, key: str, value: str) -> None:
        self.connection.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))

    @staticmethod
    def _state(metadata: dict[str, str]) -> tuple[int, dict]:
        generation = int(metadata.get("revision", "0"))
        report = json.loads(metadata.get("report", "null"))
        if report is None:
            report = {
                "status": "not_indexed",
                "repo": "local",
                "generation": generation,
                "files": 0,
                "updated": 0,
                "unchanged": 0,
                "deleted": 0,
                "skipped": 0,
                "truncated": False,
                "bytes": 0,
                "diagnostics": [],
                "indexed_at": None,
                "last_change_at": None,
                "read_files": 0,
                "reused_files": 0,
                "read_bytes": 0,
                "policy_reads": 0,
                "policy_read_bytes": 0,
                "coverage": {"complete": False},
            }
        return generation, report

    def close(self):
        with self.lock:
            self.connection.close()

    def refresh(self, force: bool = False, interval: float = 0) -> dict:
        with self.lock:
            # Poll the persisted revision even when this client's scan timer has not expired.
            with self.connection:
                self.connection.execute("BEGIN")
                metadata = self._metadata()
                self.generation, self.last_report = self._state(metadata)
            parser_revision = _parser_revision()
            if (
                not force
                and self.last_scan
                and time.monotonic() - self.last_scan < interval
                and metadata.get("parser_revision") == parser_revision
            ):
                return json.loads(_json(self.last_report))
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                metadata = self._metadata()
                revision = int(metadata.get("revision", "0"))
                old = {
                    row["path"]: _decode_file(row)
                    for row in self.connection.execute("SELECT * FROM files ORDER BY path")
                }
                cached = {}
                for path, row in old.items():
                    identity = row["fingerprint"]
                    if identity is not None:
                        cached[path] = SourceFile(
                            path=path,
                            content=row["content"],
                            size=identity[2],
                            mtime_ns=identity[3],
                            digest=row["digest"],
                            dev=identity[0],
                            ino=identity[1],
                            ctime_ns=identity[4],
                        )
                sources, scan = self.workspace.scan(cached=cached, force=force)
                updated = unchanged = 0
                deleted = sorted(set(old) - sources.keys())
                for path in deleted:
                    self.connection.execute("DELETE FROM files WHERE path=?", (path,))
                    self.connection.execute("DELETE FROM file_search WHERE path=?", (path,))
                changes = {"added": [], "modified": [], "deleted": deleted, "reparsed": []}
                for path, source in sources.items():
                    previous = old.get(path)
                    same_content = previous is not None and previous["digest"] == source.digest
                    if (
                        same_content
                        and not force
                        and previous["parser_revision"] == parser_revision
                    ):
                        unchanged += 1
                        # Touches still update metadata, avoiding a content read on every scan.
                        self.connection.execute(
                            "UPDATE files SET size=?,mtime_ns=?,fingerprint=? WHERE path=?",
                            (source.size, source.mtime_ns, _json(source.fingerprint), path),
                        )
                        continue
                    language = EXTENSION_TO_LANGUAGE.get(source.suffix, "text")
                    symbols, imports, diagnostics = [], [], []
                    try:
                        symbols = [
                            asdict(symbol) for symbol in extract_symbols(source, language, path)
                        ]
                    except Exception as exc:
                        diagnostics.append(
                            {"file": path, "reason": f"parser: {type(exc).__name__}"}
                        )
                    try:
                        imports = extract_import_details(source, language)
                    except Exception as exc:
                        diagnostics.append(
                            {"file": path, "reason": f"imports: {type(exc).__name__}"}
                        )
                    self.connection.execute(
                        """INSERT OR REPLACE INTO files
                           (path,language,size,mtime_ns,digest,content,symbols,imports,
                            fingerprint,diagnostics,symbol_count,import_count,parser_revision)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            path,
                            language,
                            source.size,
                            source.mtime_ns,
                            source.digest,
                            source.content,
                            _json(symbols),
                            _json(imports),
                            _json(source.fingerprint),
                            _json(diagnostics),
                            len(symbols),
                            len(imports),
                            parser_revision,
                        ),
                    )
                    if not same_content:
                        self.connection.execute("DELETE FROM file_search WHERE path=?", (path,))
                        self.connection.execute(
                            "INSERT INTO file_search VALUES (?,?)", (path, source.content)
                        )
                    updated += 1
                    if previous is None:
                        changes["added"].append(path)
                    elif not same_content:
                        changes["modified"].append(path)
                    elif (
                        previous["parser_revision"] != parser_revision
                        or previous["symbols"] != symbols
                        or previous["imports"] != imports
                        or previous["diagnostics"] != diagnostics
                    ):
                        changes["reparsed"].append(path)
                previous_revision = revision
                if updated or deleted or revision == 0:
                    revision += 1
                indexed_at = time.time()
                last_change_at = json.loads(metadata.get("last_change_at", "null"))
                if any(changes.values()):
                    last_change_at = indexed_at
                    counts = {key: len(value) for key, value in changes.items()}
                    budget = MAX_CHANGES
                    bounded = {}
                    for key, paths in changes.items():
                        bounded[key] = sorted(paths)[:budget]
                        budget -= len(bounded[key])
                    self._set_meta(
                        "latest_changes",
                        _json(
                            {
                                "generation": revision,
                                "previous_generation": previous_revision,
                                "changed_at": indexed_at,
                                **bounded,
                                "counts": counts,
                                "truncated": sum(counts.values()) > MAX_CHANGES,
                            }
                        ),
                    )
                rows = self.connection.execute(
                    "SELECT language,diagnostics,symbol_count,import_count FROM files ORDER BY path"
                ).fetchall()
                errors = list(scan["diagnostics"])
                parser_errors = parsed_files = text_files = symbols_count = imports_count = 0
                for row in rows:
                    diagnostics = json.loads(row["diagnostics"])
                    errors.extend(diagnostics[: max(0, 30 - len(errors))])
                    parser_errors += bool(diagnostics)
                    text_files += row["language"] == "text"
                    parsed_files += row["language"] != "text" and not diagnostics
                    symbols_count += row["symbol_count"]
                    imports_count += row["import_count"]
                complete = not scan["truncated"] and not errors
                report = {
                    "status": "ok" if complete else "partial",
                    "repo": "local",
                    "files": len(sources),
                    "updated": updated,
                    "unchanged": unchanged,
                    "deleted": len(deleted),
                    **scan,
                    "diagnostics": errors,
                    "indexed_at": indexed_at,
                    "last_change_at": last_change_at,
                    "generation": revision,
                    "parser_revision": parser_revision,
                    "coverage": {
                        "scope": "admitted workspace files",
                        "complete": complete,
                        "indexed_files": len(sources),
                        "parsed_files": parsed_files,
                        "text_files": text_files,
                        "parser_errors": parser_errors,
                        "symbols": symbols_count,
                        "imports": imports_count,
                    },
                }
                self._set_meta("revision", str(revision))
                self._set_meta("indexed_at", str(indexed_at))
                self._set_meta("last_change_at", _json(last_change_at))
                self._set_meta("parser_revision", parser_revision)
                self._set_meta("report", _json(report))
            self.last_scan = time.monotonic()
            self.generation, self.last_report = revision, report
            return json.loads(_json(report))

    def snapshot(self) -> dict:
        """Return files, report and saved changes from one read transaction."""
        with self.lock, self.connection:
            self.connection.execute("BEGIN")
            metadata = self._metadata()
            generation, report = self._state(metadata)
            files = [
                _decode_file(row)
                for row in self.connection.execute("SELECT * FROM files ORDER BY path")
            ]
            return {
                "generation": generation,
                "report": report,
                "files": files,
                "changes": self._changes(metadata),
            }

    def files(self) -> list[dict]:
        return self.snapshot()["files"]

    @staticmethod
    def _changes(metadata: dict[str, str]) -> dict:
        return json.loads(
            metadata.get(
                "latest_changes",
                _json(
                    {
                        "generation": int(metadata.get("revision", "0")),
                        "previous_generation": 0,
                        "changed_at": None,
                        "added": [],
                        "modified": [],
                        "deleted": [],
                        "reparsed": [],
                        "counts": {"added": 0, "modified": 0, "deleted": 0, "reparsed": 0},
                        "truncated": False,
                    }
                ),
            )
        )

    def latest_changes(self) -> dict:
        """Return the bounded last meaningful change; no-op scans preserve it."""
        with self.lock, self.connection:
            self.connection.execute("BEGIN")
            return self._changes(self._metadata())

    def search_text_snapshot(
        self,
        query: str,
        limit: int,
        offset: int,
        language: str | None = None,
        path_glob: str | None = None,
    ) -> tuple[list[dict], int, dict]:
        """FTS results and revision metadata from one read transaction."""
        tokens = re.findall(r"\w+", query, flags=re.UNICODE)[:32]
        with self.lock, self.connection:
            self.connection.execute("BEGIN")
            generation, report = self._state(self._metadata())
            if not tokens:
                return [], generation, report
            expression = " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens)
            rows = self.connection.execute(
                """SELECT file_search.path AS file,
                          snippet(file_search, 1, '[', ']', ' … ', 32) AS snippet,
                          bm25(file_search, 4.0, 1.0) AS rank
                   FROM file_search JOIN files ON files.path=file_search.path
                   WHERE file_search MATCH ? AND (? IS NULL OR files.language=?)
                   ORDER BY rank, file_search.path""",
                (expression, language, language),
            )
            result = []
            skipped = 0
            for row in rows:
                if path_glob and not (
                    fnmatch.fnmatchcase(row["file"], path_glob)
                    or (
                        path_glob.startswith("**/")
                        and fnmatch.fnmatchcase(row["file"], path_glob[3:])
                    )
                ):
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                if len(result) >= limit:
                    break
                result.append(dict(row))
            return result, generation, report

    def search_text(
        self,
        query: str,
        limit: int,
        offset: int,
        language: str | None = None,
        path_glob: str | None = None,
    ) -> list[dict]:
        return self.search_text_snapshot(query, limit, offset, language, path_glob)[0]
