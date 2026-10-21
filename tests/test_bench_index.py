"""The index benchmark reports its measurements: an unchanged connect reads every input without
the stat cache and none with it (#172)."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bench_index", Path(__file__).parents[1] / "scripts/bench_index.py"
)
assert spec is not None and spec.loader is not None
bench_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench_index)


def test_benchmark_reports_columns_and_the_stat_cache_spares_unchanged_reads(capsys) -> None:
    bench_index.main([2])

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == (
        "| Size | Workspace files | Workspace bytes | Cold connect (ms / bytes read) | "
        "Unchanged connect, full hash (ms / bytes read) | "
        "Unchanged connect, stat cache (ms / bytes read) | Edited connect (ms / bytes read) |"
    )
    assert lines[1] == "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    assert lines[2].startswith("| 2 | ")

    unchanged_paths: set[Path] = set()
    full_paths: set[Path] = set()
    _, _, inputs, _ = bench_index.benchmark(2, unchanged_paths, full_paths)
    assert inputs
    assert inputs <= full_paths
    assert not inputs & unchanged_paths


def test_benchmark_takes_the_synthetic_campaign_by_size_name() -> None:
    files, byte_count, inputs, measurements = bench_index.benchmark("S")
    assert files > 100 and byte_count > 0 and inputs
    assert len(measurements) == 4
