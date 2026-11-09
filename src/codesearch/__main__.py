"""Command-line entrypoint for stdio and Streamable HTTP."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from . import __version__


def main():
    parser = argparse.ArgumentParser(description="Local read-only MCP code search")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--workspace", type=Path, default=os.environ.get("CODESEARCH_WORKSPACE", ".")
    )
    parser.add_argument("--data-dir", type=Path, default=os.environ.get("CODESEARCH_DATA_DIR"))
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--scan-interval", type=float, default=2)
    parser.add_argument("--max-file-bytes", type=int, default=1024 * 1024)
    parser.add_argument("--max-files", type=int, default=50_000)
    parser.add_argument("--max-total-bytes", type=int, default=128 * 1024 * 1024)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    root = args.workspace.expanduser().resolve()
    fingerprint = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    data_dir = args.data_dir or Path.home() / ".cache" / "codesearch" / fingerprint
    from .server import create_server
    from .service import CodeSearchService

    try:
        service = CodeSearchService(
            root,
            data_dir,
            scan_interval=args.scan_interval,
            max_file_bytes=args.max_file_bytes,
            max_files=args.max_files,
            max_total_bytes=args.max_total_bytes,
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    try:
        server = create_server(service)
        options = (
            {}
            if args.transport == "stdio"
            else {
                "host": args.host,
                "port": args.port,
                "path": "/mcp",
                "stateless_http": True,
            }
        )
        server.run(transport=args.transport, show_banner=False, **options)
    finally:
        service.close()


if __name__ == "__main__":
    main()
