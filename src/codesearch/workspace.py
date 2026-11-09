"""Bounded workspace scanning with inherited ignore rules."""

from __future__ import annotations

import hashlib
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from pathspec import GitIgnoreSpec

from .safeio import Fingerprint, read_confined_snapshot

DENIED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".tox",
    ".idea",
    "dist",
    "build",
    "target",
    ".next",
    ".codesearch",
    ".ssh",
    ".aws",
    ".gnupg",
}
DENIED_NAMES = {"id_rsa", "id_ed25519", "id_dsa", "credentials", "credentials.json"}
DENIED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"}


@dataclass(frozen=True)
class SourceFile:
    path: str
    content: str
    size: int
    mtime_ns: int
    digest: str
    dev: int = 0
    ino: int = 0
    ctime_ns: int = 0
    reused: bool = False

    @property
    def fingerprint(self) -> Fingerprint:
        return (self.dev, self.ino, self.size, self.mtime_ns, self.ctime_ns)

    @property
    def name(self):
        return PurePosixPath(self.path).name

    @property
    def suffix(self):
        return PurePosixPath(self.path).suffix.lower()

    def read_bytes(self):
        return self.content.encode("utf-8")

    def read_text(self, *args, **kwargs):
        return self.content


def is_link(path: Path) -> bool:
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & 0x400
    )


class Workspace:
    def __init__(
        self,
        root: Path,
        data_dir: Path,
        max_file_bytes: int = 1024 * 1024,
        max_files: int = 50_000,
        max_total_bytes: int = 128 * 1024 * 1024,
    ):
        self.root = Path(root).expanduser().resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("workspace must be a directory")
        self.data_dir = Path(data_dir).expanduser().resolve()
        if self.data_dir == self.root:
            raise ValueError("data directory must differ from workspace")
        if min(max_file_bytes, max_files, max_total_bytes) < 1:
            raise ValueError("scan limits must be positive")
        metadata = self.root.stat()
        self._root_identity = (metadata.st_dev, metadata.st_ino)
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files
        self.max_total_bytes = max_total_bytes

    def validate_repo(self, repo: str = "local") -> None:
        if repo in {"local", ".", self.root.name, str(self.root), self.root.as_posix()}:
            return
        raise ValueError("Unknown workspace. Use 'local' or the configured workspace path.")

    def relative_path(self, value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if (
            not value
            or path.is_absolute()
            or PureWindowsPath(value).drive
            or ".." in path.parts
            or "\x00" in value
        ):
            raise ValueError("Expected a relative path inside the workspace")
        return path.as_posix()

    def _read(self, path: Path) -> bytes:
        content, _ = self._read_snapshot(path)
        assert content is not None
        return content

    def _read_snapshot(
        self, path: Path, cached_fingerprint: Fingerprint | None = None
    ) -> tuple[bytes | None, Fingerprint]:
        current = self.root
        for part in path.relative_to(self.root).parts:
            current = current / part
            if is_link(current):
                raise ValueError("links are excluded")
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("path leaves workspace")
        return read_confined_snapshot(
            self.root, path, self._root_identity, self.max_file_bytes, cached_fingerprint
        )

    def scan(
        self,
        cached: dict[str, SourceFile] | None = None,
        force: bool = False,
        progress: Callable[..., None] | None = None,
    ) -> tuple[dict[str, SourceFile], dict]:
        """Rerun admission and verify handles before reusing cached content."""
        cached = cached or {}
        files: dict[str, SourceFile] = {}
        report = {
            "skipped": 0,
            "truncated": False,
            "diagnostics": [],
            "bytes": 0,
            "read_files": 0,
            "read_bytes": 0,
            "reused_files": 0,
            "policy_reads": 0,
            "policy_read_bytes": 0,
        }

        def diagnostic(path, reason):
            report["skipped"] += 1
            if len(report["diagnostics"]) < 30:
                report["diagnostics"].append(
                    {"file": path.relative_to(self.root).as_posix(), "reason": reason}
                )

        def walk(directory, inherited):
            if report["truncated"]:
                return
            rules = list(inherited)
            policies = {}
            for ignore_name in (".gitignore", ".codesearchignore"):
                ignore = directory / ignore_name
                try:
                    ignore.lstat()
                except FileNotFoundError:
                    continue
                except OSError:
                    diagnostic(ignore, "ignore rules unreadable")
                    return
                try:
                    raw, metadata = self._read_snapshot(ignore)
                    assert raw is not None
                    report["policy_reads"] += 1
                    report["policy_read_bytes"] += len(raw)
                    rules.append(
                        (directory, GitIgnoreSpec.from_lines(raw.decode("utf-8-sig").splitlines()))
                    )
                    policies[ignore] = (raw, metadata)
                except (OSError, ValueError, UnicodeError):
                    diagnostic(ignore, "ignore rules unreadable")
                    return
            try:
                children = sorted(directory.iterdir(), key=lambda p: p.name)
            except OSError:
                diagnostic(directory, "directory unreadable")
                return
            for child in children:
                if report["truncated"]:
                    break
                try:
                    if is_link(child):
                        diagnostic(child, "link excluded")
                        continue
                    is_dir = child.is_dir()
                    name = child.name.lower()
                    if child == self.data_dir or name in DENIED_DIRS:
                        report["skipped"] += 1
                        continue
                    if (
                        name in DENIED_NAMES
                        or child.suffix.lower() in DENIED_SUFFIXES
                        or (name.startswith(".env") and name != ".env.example")
                    ):
                        report["skipped"] += 1
                        continue
                    ignored = False
                    for base, spec in rules:
                        relative = child.relative_to(base).as_posix() + ("/" if is_dir else "")
                        decision = spec.check_file(relative).include
                        if decision is not None:
                            ignored = decision
                    if ignored:
                        report["skipped"] += 1
                        continue
                    if is_dir:
                        walk(child, rules)
                        continue
                    metadata = child.stat()
                    if not stat.S_ISREG(metadata.st_mode):
                        report["skipped"] += 1
                        continue
                    if metadata.st_size > self.max_file_bytes:
                        diagnostic(child, "file exceeds size limit")
                        continue
                    relative = child.relative_to(self.root).as_posix()
                    if progress is not None:
                        progress(
                            current_file=relative,
                            scanned_files=len(files),
                            scanned_bytes=report["bytes"],
                        )
                    previous = None if force else cached.get(relative)
                    if child in policies:
                        raw, identity = policies[child]
                        reused = previous is not None and previous.fingerprint == identity
                    else:
                        raw, identity = self._read_snapshot(
                            child, previous.fingerprint if previous is not None else None
                        )
                        reused = raw is None
                        if raw is not None:
                            report["read_files"] += 1
                            report["read_bytes"] += len(raw)
                    if reused:
                        assert previous is not None
                        content, digest = previous.content, previous.digest
                        report["reused_files"] += 1
                    else:
                        assert raw is not None
                        if b"\x00" in raw:
                            diagnostic(child, "binary file")
                            continue
                        try:
                            content = raw.decode("utf-8-sig")
                        except UnicodeDecodeError:
                            diagnostic(child, "not UTF-8 text")
                            continue
                        digest = hashlib.sha256(raw).hexdigest()
                    if (
                        len(files) >= self.max_files
                        or report["bytes"] + identity[2] > self.max_total_bytes
                    ):
                        report["truncated"] = True
                        break
                    files[relative] = SourceFile(
                        path=relative,
                        content=content,
                        size=identity[2],
                        mtime_ns=identity[3],
                        digest=digest,
                        dev=identity[0],
                        ino=identity[1],
                        ctime_ns=identity[4],
                        reused=reused,
                    )
                    report["bytes"] += identity[2]
                except (OSError, ValueError):
                    diagnostic(child, "file unreadable or changed during scan")

        walk(self.root, [])
        return files, report
