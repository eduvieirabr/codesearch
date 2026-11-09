import pytest

from codesearch.workspace import Workspace


def put(root, name, content="hello"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_nested_ignore_and_non_overridable_exclusions(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    put(root, ".gitignore", "*.log\n")
    put(root, "src/.gitignore", "!keep.log\n")
    put(root, ".codesearchignore", "private/\n")
    for name in [
        "a.py",
        "trace.log",
        "src/keep.log",
        "src/no.log",
        ".env",
        ".env.local",
        ".env.example",
        "id_rsa",
        "private/key.txt",
        "node_modules/pkg/index.js",
    ]:
        put(root, name)
    workspace = Workspace(root, tmp_path / "data")
    files, _ = workspace.scan()
    assert "a.py" in files and "src/keep.log" in files and ".env.example" in files
    assert (
        not {
            "trace.log",
            "src/no.log",
            ".env",
            ".env.local",
            "id_rsa",
            "private/key.txt",
            "node_modules/pkg/index.js",
        }
        & files.keys()
    )


def test_binary_oversize_and_limit_are_reported(tmp_path):
    put(tmp_path, "big.txt", "x" * 100)
    (tmp_path / "binary.bin").write_bytes(b"hello\x00world")
    put(tmp_path, "one.py", "x=1")
    put(tmp_path, "two.py", "x=2")
    files, report = Workspace(tmp_path, tmp_path / ".data", max_file_bytes=32, max_files=1).scan()
    assert len(files) == 1
    assert report["truncated"]
    assert report["skipped"] >= 2


def test_aliases_and_traversal(tmp_path):
    workspace = Workspace(tmp_path, tmp_path / ".data")
    for alias in ["local", ".", str(tmp_path), tmp_path.name]:
        workspace.validate_repo(alias)
    for alias in ["../outside", "https://github.com/o/r", "other"]:
        with pytest.raises(ValueError):
            workspace.validate_repo(alias)
    for candidate in ["../secret.txt", "/etc/passwd", r"C:\Windows\win.ini", "a/../../b"]:
        with pytest.raises(ValueError):
            workspace.relative_path(candidate)


def test_symlink_is_not_read(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = put(tmp_path, "outside.txt", "secret")
    try:
        (root / "link.txt").symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation unavailable on this Windows account")
    files, _ = Workspace(root, tmp_path / "data").scan()
    assert "link.txt" not in files
