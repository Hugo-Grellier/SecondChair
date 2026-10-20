"""Measure index connection costs in fictional, temporary workspaces."""

import argparse
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from secondchair.core import canon, delegation, index, workspace


def _workspace(size: int, root: Path) -> workspace.Workspace:
    ws = workspace.init(root, "en", "absalom")
    create_entity = next(tool for tool in canon.tools(ws) if tool.name == "create_entity")
    for number in range(size):
        delegation.act(
            ws,
            create_entity,
            "bench-agent",
            lambda number=number: create_entity.fn(names=[f"Fictional person {number}"]),
        )
    return ws


def _measure(call) -> tuple[float, int]:
    total = 0
    read_bytes = Path.read_bytes

    def counted(path: Path) -> bytes:
        nonlocal total
        data = read_bytes(path)
        total += len(data)
        return data

    start = time.perf_counter()
    with patch.object(Path, "read_bytes", counted):
        conn = call()
        conn.close()
    return (time.perf_counter() - start) * 1000, total


def benchmark(size: int) -> tuple[int, int, int, list[tuple[float, int]]]:
    with TemporaryDirectory(prefix="secondchair-index-bench-") as directory:
        root = Path(directory) / "workspace"
        ws = _workspace(size, root)
        files = [path for path in root.rglob("*") if path.is_file()]
        file_count = len(files)
        byte_count = sum(path.stat().st_size for path in files)
        inputs = [*(root / "canon").rglob("*"), *(root / "action-log").rglob("*")]
        input_bytes = sum(path.stat().st_size for path in inputs if path.is_file())
        cold = _measure(lambda: index.connect(ws))
        unchanged = _measure(lambda: index.connect(ws))

        document = next((root / index.ENTITIES_DIR).glob("*.md"))
        document.write_text(document.read_text() + "A hand edit.\n")
        edited = _measure(lambda: index.connect(ws))
        return file_count, byte_count, input_bytes, [cold, unchanged, edited]


def main(sizes: list[int]) -> None:
    print(
        "| Size | Workspace files | Workspace bytes | Cold connect (ms / bytes read) | "
        "Unchanged connect (ms / bytes read) | Edited connect (ms / bytes read) |"
    )
    print("| ---: | ---: | ---: | ---: | ---: | ---: |")
    for size in sizes:
        files, byte_count, _, measurements = benchmark(size)
        rendered = [f"{ms:.2f} / {count}" for ms, count in measurements]
        print(f"| {size} | {files} | {byte_count} | " + " | ".join(rendered) + " |")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="10,100,1000")
    arguments = parser.parse_args()
    parsed_sizes = [int(value) for value in arguments.sizes.split(",")]
    if not parsed_sizes or any(size < 1 for size in parsed_sizes):
        parser.error("sizes must be positive integers")
    main(parsed_sizes)
