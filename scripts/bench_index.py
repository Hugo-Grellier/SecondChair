"""Measure index connection costs in fictional workspaces; SQLite page I/O is excluded."""

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


def _measure(call, paths_read: set[Path] | None = None) -> tuple[float, int]:
    total = 0
    read_bytes = Path.read_bytes
    read_text = Path.read_text

    def counted(path: Path) -> bytes:
        nonlocal total
        data = read_bytes(path)
        total += len(data)
        if paths_read is not None:
            paths_read.add(path)
        return data

    def counted_text(path: Path, *args, **kwargs) -> str:
        nonlocal total
        data = read_text(path, *args, **kwargs)
        total += len(data.encode("utf-8"))
        if paths_read is not None:
            paths_read.add(path)
        return data

    start = time.perf_counter()
    with patch.object(Path, "read_bytes", counted), patch.object(Path, "read_text", counted_text):
        conn = call()
        conn.close()
    return (time.perf_counter() - start) * 1000, total


def benchmark(
    size: int, unchanged_paths: set[Path] | None = None
) -> tuple[int, int, set[Path], list[tuple[float, int]]]:
    with TemporaryDirectory(prefix="secondchair-index-bench-") as directory:
        root = Path(directory) / "workspace"
        ws = _workspace(size, root)
        files = [path for path in root.rglob("*") if path.is_file()]
        file_count = len(files)
        byte_count = sum(path.stat().st_size for path in files)
        inputs = {p for d in ("canon", "action-log") for p in (root / d).rglob("*") if p.is_file()}
        cold = _measure(lambda: index.connect(ws))
        unchanged = _measure(lambda: index.connect(ws), unchanged_paths)

        document = next((root / index.ENTITIES_DIR).glob("*.md"))
        document.write_text(document.read_text() + "A hand edit.\n")
        edited = _measure(lambda: index.connect(ws))
        return file_count, byte_count, inputs, [cold, unchanged, edited]


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
