"""Read using anchored directory descriptors or verified Windows handles."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def _windows_handle_path(fd: int) -> Path:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    function = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    function.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    function.restype = wintypes.DWORD
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(fd))
    capacity = function(handle, None, 0, 0)
    if not capacity:
        raise OSError(ctypes.get_last_error(), "Cannot verify opened file path")
    buffer = ctypes.create_unicode_buffer(capacity + 1)
    length = function(handle, buffer, len(buffer), 0)
    if not length or length >= len(buffer):
        raise OSError("Cannot verify opened file path")
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


Fingerprint = tuple[int, int, int, int, int]


def fingerprint(metadata: os.stat_result) -> Fingerprint:
    """Identity and mutation metadata from the opened file handle."""
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def read_confined_snapshot(
    root: Path,
    path: Path,
    root_identity: tuple[int, int],
    limit: int,
    cached_fingerprint: Fingerprint | None = None,
) -> tuple[bytes | None, Fingerprint]:
    """Read a stable handle, or validate it for reuse without reading content."""
    relative = path.relative_to(root)
    if not relative.parts or ".." in relative.parts:
        raise ValueError("Expected a workspace file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    if os.name == "nt":
        fd = os.open(path, flags)
        try:
            final_path = _windows_handle_path(fd)
            # Use the path of the OPEN handle, not a second lookup of the input path.
            if final_path != path or not final_path.is_relative_to(root):
                raise ValueError("Opened file leaves workspace or traverses a link")
            metadata = root.stat()
            if (metadata.st_dev, metadata.st_ino) != root_identity:
                raise ValueError("Workspace root changed")
        except BaseException:
            os.close(fd)
            raise
    else:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory_fd = os.open(root, directory_flags)
        try:
            metadata = os.fstat(directory_fd)
            if (metadata.st_dev, metadata.st_ino) != root_identity:
                raise ValueError("Workspace root changed")
            for part in relative.parts[:-1]:
                next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
            fd = os.open(relative.parts[-1], flags | os.O_NOFOLLOW, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("not a regular file")
        before_fingerprint = fingerprint(before)
        if before.st_size > limit:
            raise ValueError("file exceeds size limit")
        content = None if before_fingerprint == cached_fingerprint else stream.read(limit + 1)
        after_fingerprint = fingerprint(os.fstat(stream.fileno()))
        if before_fingerprint != after_fingerprint:
            raise ValueError("file changed during read")
        if content is not None:
            if len(content) > limit:
                raise ValueError("file exceeds size limit")
            if len(content) != before.st_size:
                raise ValueError("file changed during read")
    return content, before_fingerprint


def read_confined(root: Path, path: Path, root_identity: tuple[int, int], limit: int) -> bytes:
    content, _ = read_confined_snapshot(root, path, root_identity, limit)
    assert content is not None
    return content
