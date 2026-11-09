"""Regression coverage for independently reviewed confinement and cache bugs."""

import json
import os
import subprocess

import pytest

from codesearch.service import CodeSearchService
from codesearch.workspace import Workspace


def test_shared_database_invalidates_other_clients(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "private.py").write_text("def private(): return 'secret'")
    a = CodeSearchService(root, tmp_path / "data", scan_interval=0)
    b = CodeSearchService(root, tmp_path / "data", scan_interval=0)
    try:
        assert a.get_file_content(file_path="private.py")["content"]
        assert b.get_file_content(file_path="private.py")["content"]
        (root / ".codesearchignore").write_text("private.py\n")
        b.refresh_index()
        with pytest.raises(ValueError):
            a.get_file_content(file_path="private.py")
        assert not a.search_symbols(query="private")["results"]
    finally:
        a.close()
        b.close()


@pytest.mark.parametrize("ignore", [".gitignore", ".codesearchignore"])
def test_utf8_bom_ignore_policy(tmp_path, ignore):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ignore).write_text("private.py\n", encoding="utf-8-sig")
    (root / "private.py").write_text("secret")
    files, _ = Workspace(root, tmp_path / "data").scan()
    assert "private.py" not in files


def test_directory_swap_does_not_read_outside(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    source = root / "src"
    source.mkdir(parents=True)
    (source / "code.txt").write_text("inside")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "code.txt").write_text("outside secret")
    workspace = Workspace(root, tmp_path / "data")
    original_open = os.open
    attacked = False

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal attacked
        if not attacked:
            attacked = True
            source.rename(root / "original")
            if os.name == "nt":
                result = subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-Command",
                        "& { param($link, $destination) New-Item -ItemType Junction -Path $link -Target $destination | Out-Null }",
                        str(source),
                        str(outside),
                    ],
                    capture_output=True,
                    text=True,
                )
                if result.returncode:
                    pytest.skip("Cannot create test junction")
            else:
                source.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_then_open)
    with pytest.raises((OSError, ValueError)):
        workspace._read(source / "code.txt")
    assert attacked


def test_response_fields_are_bounded_and_reported(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "long.md").write_text("# " + "a" * 100_000)
    (root / "long.js").write_text('import x from "' + "x" * 100_000 + '";')
    service = CodeSearchService(root, tmp_path / "data", scan_interval=0)
    try:
        outline = service.get_file_outline(file_path="long.md")
        assert len(json.dumps(outline)) < 10_000
        assert outline["symbols"][0]["fields_truncated"]
        imports = service.get_file_imports(file_path="long.js")
        assert len(json.dumps(imports)) < 10_000
        assert imports["imports"][0]["fields_truncated"]
    finally:
        service.close()
