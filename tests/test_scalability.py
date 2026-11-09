"""Large-index regressions measured by database work, not wall-clock timing."""

import tracemalloc

import pytest

from codesearch.service import CodeSearchService
from codesearch.store import IndexStore
from codesearch.workspace import Workspace


@pytest.mark.parametrize("phase", ["cold", "edited", "deleted"])
def test_text_index_updates_scale_with_file_count(tmp_path, phase):
    def measure(count):
        base = tmp_path / str(count)
        root = base / "source"
        root.mkdir(parents=True)
        for number in range(count):
            (root / f"file_{number:04}.txt").write_text("original searchable token\n" * 8)
        store = IndexStore(Workspace(root, base / "data"))
        try:
            if phase != "cold":
                store.refresh()
                for source in root.iterdir():
                    if phase == "edited":
                        source.write_text("replacement searchable token\n" * 8)
                    else:
                        source.unlink()
            steps = 0

            def progress():
                nonlocal steps
                steps += 100
                return 0

            store.connection.set_progress_handler(progress, 100)
            report = store.refresh()
            store.connection.set_progress_handler(None, 0)
            assert report["status"] == "ok"
            if phase == "deleted":
                assert report["deleted"] == count
                assert store.search_text("searchable", count + 1, 0) == []
            else:
                assert report["updated"] == count
                term = "replacement" if phase == "edited" else "original"
                results = store.search_text(term, count + 1, 0)
                assert len(results) == count
                assert len({row["file"] for row in results}) == count
                if phase == "edited":
                    assert store.search_text("original", count + 1, 0) == []
            return steps
        finally:
            store.close()

    small, large = measure(128), measure(512)
    # Four times as many files must not require quadratic full-index scans.
    # Allow room for SQLite page splits, FTS merges and version differences.
    assert large < 6 * small, (phase, small, large)


def test_index_status_does_not_materialize_source_content(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    content = "def operation(): pass\n" + "# synthetic source padding\n" * 10_000
    for number in range(12):
        (root / f"module_{number}.py").write_text(content)
    service = CodeSearchService(root, tmp_path / "data", scan_interval=3600)
    try:
        indexed = service.refresh_index()
        tracemalloc.start()
        try:
            status = service.get_index_status()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert status["files"] == status["symbols"] == 12
        assert status["generation"] == indexed["generation"]
        assert status["_meta"]["coverage"] == status["coverage"]
        assert peak < 1024 * 1024, peak
        (root / "new.py").write_text("def added(): pass\n")
        service.scan_interval = 0
        service.refresh_index()
        updated = service.get_index_status()
        assert updated["files"] == updated["symbols"] == 13
        assert updated["generation"] > status["generation"]
        assert updated["_meta"]["generation"] == updated["generation"]
    finally:
        service.close()
