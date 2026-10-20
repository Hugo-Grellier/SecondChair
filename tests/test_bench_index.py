"""The index benchmark reports its measurements and captures today's full fingerprint reads."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bench_index", Path(__file__).parents[1] / "scripts/bench_index.py"
)
assert spec is not None and spec.loader is not None
bench_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench_index)


def test_benchmark_reports_columns_and_unchanged_connect_reads_all_inputs(capsys) -> None:
    bench_index.main([2])

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == (
        "| Size | Workspace files | Workspace bytes | Cold connect (ms / bytes read) | "
        "Unchanged connect (ms / bytes read) | Edited connect (ms / bytes read) |"
    )
    assert lines[1] == "| ---: | ---: | ---: | ---: | ---: | ---: |"
    assert lines[2].startswith("| 2 | ")

    # The unchanged call currently hashes every canon and action-log file. #172 will change this.
    _, _, input_bytes, measurements = bench_index.benchmark(2)
    assert measurements[1][1] >= input_bytes
