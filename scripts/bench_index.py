"""Measure index connection costs in fictional workspaces; SQLite page I/O is excluded."""

import argparse
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from secondchair.bench import synth
from secondchair.core import canon, delegation, index, workspace
from secondchair.core.workspace import STATE_DIR


def _workspace(size: int | str, root: Path) -> workspace.Workspace:
    if isinstance(size, str):  # S, M or L: the synthetic campaign of #195, shared with its benches
        return synth.generate(root, size).ws
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
    size: int | str, unchanged_paths: set[Path] | None = None, full_paths: set[Path] | None = None
) -> tuple[int, int, set[Path], list[tuple[float, int]]]:
    """Cold, unchanged with the stat cache removed (full hashing: every read before #172),
    unchanged with it, and after a hand edit; the paths each unchanged connect reads."""
    with TemporaryDirectory(prefix="secondchair-index-bench-") as directory:
        root = Path(directory) / "workspace"
        ws = _workspace(size, root)
        files = [path for path in root.rglob("*") if path.is_file()]
        file_count = len(files)
        byte_count = sum(path.stat().st_size for path in files)
        inputs = {p for d in index.FINGERPRINTED for p in (root / d).rglob("*") if p.is_file()}
        # Written a while ago, as a campaign between sessions: outside the mtime granularity.
        settled = time.time_ns() - 2 * index.MTIME_GRANULARITY_NS
        for path in inputs:
            os.utime(path, ns=(settled, settled))
        cold = _measure(lambda: index.connect(ws))
        (root / STATE_DIR / index.STAT_CACHE).unlink()
        full = _measure(lambda: index.connect(ws), full_paths)
        unchanged = _measure(lambda: index.connect(ws), unchanged_paths)

        document = next((root / index.ENTITIES_DIR).glob("*.md"))
        document.write_text(document.read_text() + "A hand edit.\n")
        edited = _measure(lambda: index.connect(ws))
        return file_count, byte_count, inputs, [cold, full, unchanged, edited]


def main(sizes: list[int | str]) -> None:
    print(
        "| Size | Workspace files | Workspace bytes | Cold connect (ms / bytes read) | "
        "Unchanged connect, full hash (ms / bytes read) | "
        "Unchanged connect, stat cache (ms / bytes read) | Edited connect (ms / bytes read) |"
    )
    print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for size in sizes:
        files, byte_count, _, measurements = benchmark(size)
        rendered = [f"{ms:.2f} / {count}" for ms, count in measurements]
        print(f"| {size} | {files} | {byte_count} | " + " | ".join(rendered) + " |")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        default="10,100,1000",
        help="entity counts, or S, M, L for the synthetic campaigns of secondchair.bench.synth",
    )
    arguments = parser.parse_args()
    parsed_sizes = [
        value if value in synth.SIZES else int(value) if value.isdigit() else 0
        for value in arguments.sizes.split(",")
    ]
    if not parsed_sizes or 0 in parsed_sizes:
        parser.error("sizes must be positive integers, or S, M, L")
    main(parsed_sizes)
