"""Reproduce source-read savings using generated, disposable local code."""

import json
import tempfile
import time
from pathlib import Path

from codesearch.store import IndexStore
from codesearch.workspace import Workspace


def main():
    with tempfile.TemporaryDirectory(prefix="codesearch-benchmark-") as directory:
        base = Path(directory)
        root = base / "workspace"
        root.mkdir()
        for number in range(250):
            (root / f"module_{number}.py").write_text(
                f"def operation_{number}(value):\n    return value + {number}\n"
                + "# generated filler for repeatable read accounting\n" * 200,
                encoding="utf-8",
            )
        store = IndexStore(Workspace(root, base / "data"))
        measurements = {}

        def measure(name, **kwargs):
            started = time.perf_counter()
            report = store.refresh(**kwargs)
            measurements[name] = {
                key: report[key]
                for key in ("read_files", "read_bytes", "reused_files", "updated", "policy_reads")
            }
            measurements[name]["seconds"] = round(time.perf_counter() - started, 4)

        try:
            measure("cold")
            measure("unchanged")
            (root / "module_0.py").write_text("def changed(value): return value * 2\n")
            measure("one_edit")
            measure("forced", force=True)
        finally:
            store.close()
        print(json.dumps(measurements, indent=2))


if __name__ == "__main__":
    main()
