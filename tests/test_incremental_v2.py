"""Behavioral regression tests for persistent, metadata-based snapshots."""

import hashlib
import json
import os
import sqlite3

import pytest

from codesearch import parser, safeio
from codesearch import store as store_module
from codesearch.store import IndexStore
from codesearch.workspace import Workspace


@pytest.fixture
def indexed(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "one.py").write_text("def one(): return 1\n")
    (root / "two.py").write_text("def two(): return 2\n")
    workspace = Workspace(root, tmp_path / "data")
    store = IndexStore(workspace)
    yield root, store
    store.close()


def test_metadata_reuse_edit_and_forced_reads(indexed):
    root, store = indexed
    first = store.refresh()
    assert first.get("read_files") == 2
    second = store.refresh()
    assert second["read_files"] == 0
    assert second["read_bytes"] == 0
    assert second["reused_files"] == 2
    (root / "one.py").write_text("def updated(): return 3\n")
    third = store.refresh()
    assert third["read_files"] == 1
    assert third["updated"] == 1
    assert third["reused_files"] == 1
    forced = store.refresh(force=True)
    assert forced["read_files"] == 2
    assert forced["updated"] == 2
    assert forced["reused_files"] == 0


def test_ignore_rules_reread_and_purge_cached_content(indexed):
    root, store = indexed
    rules = root / ".codesearchignore"
    rules.write_text("# none\n")
    store.refresh()
    same = store.refresh()
    assert same.get("read_files") == 0
    assert same["policy_reads"] == 1
    rules.write_text("one.py\n")
    report = store.refresh()
    assert report["deleted"] == 1
    assert "one.py" not in {item["path"] for item in store.snapshot()["files"]}
    assert "one.py" not in {row["file"] for row in store.search_text("one", 10, 0)}


def test_touch_updates_fingerprint_without_repeated_reads(indexed):
    root, store = indexed
    store.refresh()
    path = root / "one.py"
    meta = path.stat()
    os.utime(path, ns=(meta.st_atime_ns, meta.st_mtime_ns + 2_000_000_000))
    report = store.refresh()
    assert report.get("read_files") == 1
    assert report["updated"] == 0
    assert store.refresh()["read_files"] == 0
    item = next(item for item in store.files() if item["path"] == "one.py")
    assert item["fingerprint"][3] == path.stat().st_mtime_ns


def test_parser_revision_reparses_unchanged_cached_sources(indexed, monkeypatch):
    _, store = indexed
    first = store.refresh()
    monkeypatch.setattr(parser, "PARSER_REVISION", "test-next-parser", raising=False)
    second = store.refresh(interval=3600)
    assert second["updated"] == 2
    assert second["generation"] > first["generation"]
    assert second["read_files"] == 0


def test_other_client_revision_polled_inside_scan_interval(indexed):
    root, first = indexed
    first.refresh()
    second = IndexStore(first.workspace)
    try:
        (root / "one.py").write_text("def different(): pass\n")
        changed = second.refresh()
        report = first.refresh(interval=3600)
        assert report.get("generation") == changed.get("generation")
        assert report["updated"] == changed["updated"]
        snapshot = first.snapshot()
        assert snapshot["generation"] == report["generation"]
        assert snapshot["report"]["generation"] == snapshot["generation"]
        assert snapshot["files"][0]["symbols"][0]["name"] == "different"
    finally:
        second.close()


def test_parser_diagnostic_survives_unchanged_refresh_and_restart(indexed, monkeypatch):
    _, store = indexed

    def failure(*args):
        raise RuntimeError("sensitive parser detail")

    monkeypatch.setattr(store_module, "extract_symbols", failure)
    first = store.refresh()
    assert len(first["diagnostics"]) == 2
    unchanged = store.refresh()
    assert unchanged["diagnostics"] == first["diagnostics"]
    assert unchanged["coverage"]["parser_errors"] == 2
    restarted = IndexStore(store.workspace)
    try:
        report = restarted.refresh()
        assert report["diagnostics"] == first["diagnostics"]
        assert report["read_files"] == 0
        assert restarted.snapshot()["files"][0]["diagnostics"] == [first["diagnostics"][0]]
    finally:
        restarted.close()


def test_schema_one_migrates_without_removing_content(tmp_path):
    root, data = tmp_path / "repo", tmp_path / "data"
    root.mkdir()
    data.mkdir()
    content = "def old(): pass\n"
    (root / "old.py").write_text(content)
    connection = sqlite3.connect(data / "index.sqlite3")
    connection.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE files (path TEXT PRIMARY KEY, language TEXT, size INTEGER,
            mtime_ns INTEGER, digest TEXT, content TEXT, symbols TEXT, imports TEXT);
        CREATE VIRTUAL TABLE file_search USING fts5(path, content);
    """)
    connection.executemany(
        "INSERT INTO meta VALUES (?,?)",
        [
            ("schema", "1"),
            (
                "workspace",
                str(root.resolve()) + ":" + os.environ.get("CODESEARCH_WORKSPACE_ID", ""),
            ),
            ("revision", "7"),
        ],
    )
    connection.execute(
        "INSERT INTO files VALUES (?,?,?,?,?,?,?,?)",
        (
            "old.py",
            "python",
            len(content),
            0,
            hashlib.sha256(content.encode()).hexdigest(),
            content,
            "[]",
            "[]",
        ),
    )
    connection.execute("INSERT INTO file_search VALUES (?,?)", ("old.py", content))
    connection.commit()
    connection.close()
    store = IndexStore(Workspace(root, data))
    try:
        assert store.files()[0]["content"] == content
        assert store.snapshot()["generation"] == 7
        assert store.refresh()["updated"] == 1
        assert store.files()[0]["symbols"][0]["name"] == "old"
    finally:
        store.close()


def test_same_handle_mutation_during_read_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "code.py"
    path.write_text("def before(): pass\n")
    workspace = Workspace(tmp_path, tmp_path / "data")
    original_fdopen = safeio.os.fdopen

    class MutatingReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def read(self, limit):
            content = self.stream.read(limit)
            path.write_text("def after_mutation(): pass\n")
            return content

    monkeypatch.setattr(
        safeio.os, "fdopen", lambda *a, **kw: MutatingReader(original_fdopen(*a, **kw))
    )
    with pytest.raises(ValueError, match="changed"):
        workspace._read(path)


def test_latest_meaningful_changes_survive_noop_and_restart(indexed):
    root, store = indexed
    store.refresh()
    (root / "one.py").write_text("def changed(): pass\n")
    (root / "two.py").unlink()
    store.refresh()
    changes = store.latest_changes()
    assert changes["modified"] == ["one.py"]
    assert changes["deleted"] == ["two.py"]
    assert changes["added"] == []
    store.refresh()
    assert store.latest_changes() == changes
    restarted = IndexStore(store.workspace)
    try:
        assert restarted.latest_changes() == changes
    finally:
        restarted.close()


def test_snapshot_fields_are_decoded_and_coverage_is_explicit(indexed):
    _, store = indexed
    store.refresh()
    snapshot = store.snapshot()
    assert snapshot["generation"] >= 1
    assert snapshot["report"]["coverage"]["indexed_files"] == 2
    item = snapshot["files"][0]
    assert isinstance(item["fingerprint"], list)
    assert isinstance(item["diagnostics"], list)
    assert isinstance(item["symbols"], list)
    assert item["symbol_count"] == 1
    json.dumps(snapshot)


def test_fts_filters_precede_pagination(indexed):
    root, store = indexed
    (root / "a.txt").write_text("keyword keyword keyword")
    (root / "z.py").write_text("def keyword(): pass")
    store.refresh()
    rows, generation, report = store.search_text_snapshot(
        "keyword", 1, 0, language="python", path_glob="**/*.py"
    )
    assert [row["file"] for row in rows] == ["z.py"]
    assert generation == report["generation"]


def test_snapshot_metadata_and_files_use_one_read_transaction(indexed, monkeypatch):
    root, first = indexed
    original_report = first.refresh()
    second = IndexStore(first.workspace)
    original_metadata = first._metadata
    attacked = False

    def update_between_metadata_and_files():
        nonlocal attacked
        metadata = original_metadata()
        if not attacked:
            attacked = True
            (root / "one.py").write_text("def replaced(): pass\n")
            second.refresh()
        return metadata

    monkeypatch.setattr(first, "_metadata", update_between_metadata_and_files)
    try:
        snapshot = first.snapshot()
        assert snapshot["generation"] == original_report["generation"]
        assert snapshot["files"][0]["symbols"][0]["name"] == "one"
        following = first.snapshot()
        assert following["generation"] > snapshot["generation"]
        assert following["files"][0]["symbols"][0]["name"] == "replaced"
    finally:
        second.close()


def test_changes_report_is_bounded_and_preserves_total_counts(indexed):
    root, store = indexed
    store.refresh()
    for number in range(120):
        (root / f"extra{number}.txt").write_text("content")
    store.refresh()
    changes = store.latest_changes()
    assert changes["counts"]["added"] == 120
    assert len(changes["added"]) <= 100
    assert changes["truncated"]


def test_force_reparses_even_when_fingerprint_is_unchanged(indexed, monkeypatch):
    _, store = indexed
    store.refresh()

    def failure(*args):
        raise RuntimeError("parser changed")

    monkeypatch.setattr(store_module, "extract_symbols", failure)
    report = store.refresh(force=True)
    assert report["coverage"]["parser_errors"] == 2
    assert all(row["symbols"] == [] for row in store.snapshot()["files"])


def test_unchanged_scan_does_not_read_source_handles(indexed, monkeypatch):
    _, store = indexed
    store.refresh()
    original_fdopen = safeio.os.fdopen

    class ReadGuard:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def read(self, limit):
            pytest.fail("An unchanged source handle must not be read")

    monkeypatch.setattr(
        safeio.os, "fdopen", lambda *args, **kwargs: ReadGuard(original_fdopen(*args, **kwargs))
    )
    assert store.refresh()["unchanged"] == 2


def test_replacement_same_size_and_mtime_is_not_reused(indexed):
    root, store = indexed
    store.refresh()
    path = root / "one.py"
    original = path.stat()
    replacement = root / "replacement.tmp"
    replacement.write_text("def new(): return 1\n")
    os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
    replacement.replace(path)
    report = store.refresh()
    assert report["read_files"] == 1
    assert store.snapshot()["files"][0]["symbols"][0]["name"] == "new"


def test_snapshot_changes_do_not_observe_a_later_commit(indexed, monkeypatch):
    root, first = indexed
    original_report = first.refresh()
    second = IndexStore(first.workspace)
    original_metadata = first._metadata
    changed = False

    def update_after_reading_metadata():
        nonlocal changed
        metadata = original_metadata()
        if not changed:
            changed = True
            (root / "two.py").unlink()
            second.refresh()
        return metadata

    monkeypatch.setattr(first, "_metadata", update_after_reading_metadata)
    try:
        snapshot = first.snapshot()
        assert snapshot["generation"] == original_report["generation"]
        assert snapshot["changes"]["generation"] == snapshot["generation"]
        assert snapshot["changes"]["added"] == ["one.py", "two.py"]
        assert snapshot["changes"]["deleted"] == []
        assert {row["path"] for row in snapshot["files"]} == {"one.py", "two.py"}
        following = first.snapshot()
        assert following["generation"] > snapshot["generation"]
        assert following["changes"]["generation"] == following["generation"]
        assert following["changes"]["deleted"] == ["two.py"]
        assert [row["path"] for row in following["files"]] == ["one.py"]
    finally:
        second.close()
