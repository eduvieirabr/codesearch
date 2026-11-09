import pytest

from codesearch.store import IndexStore
from codesearch.workspace import Workspace


def test_incremental_updates_deletes_restart_and_ignore(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "hello.py"
    source.write_text("def hello():\n    return 1\n")
    workspace = Workspace(root, tmp_path / "data")
    store = IndexStore(workspace)
    first = store.refresh()
    assert first["updated"] == 1
    assert store.refresh()["unchanged"] == 1
    assert store.files()[0]["symbols"][0]["name"] == "hello"
    store.close()
    store = IndexStore(workspace)
    assert len(store.files()) == 1
    source.write_text("def goodbye():\n    return 2\n")
    assert store.refresh()["updated"] == 1
    assert store.files()[0]["symbols"][0]["name"] == "goodbye"
    (root / ".gitignore").write_text("hello.py\n")
    assert store.refresh()["deleted"] == 1
    assert all(row["path"] != "hello.py" for row in store.files())
    source.unlink()
    store.refresh()
    store.close()


def test_database_cannot_be_reused_for_other_workspace(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    data = tmp_path / "data"
    IndexStore(Workspace(a, data)).close()
    with pytest.raises(ValueError, match="workspace"):
        IndexStore(Workspace(b, data))


def test_fts_handles_punctuation_and_empty_query(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "example.py").write_text("def load_sales():\n    return 'daily sales'\n")
    store = IndexStore(Workspace(root, tmp_path / "data"))
    store.refresh()
    assert store.search_text("daily sales", 10, 0)[0]["file"] == "example.py"
    assert store.search_text("", 10, 0) == []
    assert store.search_text('" OR *', 10, 0) == []
    store.close()
