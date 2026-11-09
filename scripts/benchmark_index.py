"""Reproduce source-read savings using generated, disposable local code."""

import argparse
import json
import tempfile
import time
from pathlib import Path

from codesearch.store import IndexStore
from codesearch.workspace import Workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=250)
    parser.add_argument("--file-bytes", type=int, default=10_000)
    parser.add_argument("--max-total-bytes", type=int, default=128 * 1024 * 1024)
    parser.add_argument("--text-only", action="store_true", help="Isolate scan/storage costs")
    args = parser.parse_args()
    if args.files < 1 or args.file_bytes < 128 or args.max_total_bytes < 1:
        parser.error("files/total bytes must be positive and file bytes must be at least 128")
    with tempfile.TemporaryDirectory(prefix="codesearch-benchmark-") as directory:
        base = Path(directory)
        root = base / "workspace"
        root.mkdir()
        suffix = "txt" if args.text_only else "py"
        for number in range(args.files):
            header = f"def operation_{number}(value):\n    return value + {number}\n".encode()
            filler = b"# generated filler for repeatable read accounting\n"
            padding = (filler * (args.file_bytes // len(filler) + 1))[
                : max(0, args.file_bytes - len(header))
            ]
            (root / f"module_{number}.{suffix}").write_bytes(header + padding)
        store = IndexStore(Workspace(root, base / "data", max_total_bytes=args.max_total_bytes))
        measurements = {}

        def measure(name, **kwargs):
            started = time.perf_counter()
            report = store.refresh(**kwargs)
            measurements[name] = {
                key: report[key]
                for key in (
                    "status",
                    "files",
                    "bytes",
                    "truncated",
                    "read_files",
                    "read_bytes",
                    "reused_files",
                    "updated",
                    "policy_reads",
                )
            }
            measurements[name]["seconds"] = round(time.perf_counter() - started, 4)

        try:
            measure("cold")
            measure("unchanged")
            (root / f"module_0.{suffix}").write_text("def changed(value): return value * 2\n")
            measure("one_edit")
            measure("forced", force=True)
        finally:
            store.close()
        print(json.dumps(measurements, indent=2))


if __name__ == "__main__":
    main()
