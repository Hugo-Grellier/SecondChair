"""The scaling bench (#195, no model): what the Core costs at each synthetic campaign size.

Per size S, M, L (`synth.SIZES`): the workspace's files and bytes (the derived `.secondchair/`
state excluded), a full index rebuild, an unchanged `connect` (a stat of every canon and
action-log file against the stat cache, then a SQLite open: the cost of every query, #172),
`search_facts` and `what_knows` at p50 and p95 over a fixed set of probes, and `world.state`.
Wall time on the machine it runs on: compare runs of one machine, not machines.
"""

import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from secondchair.bench import synth
from secondchair.core import index, knowledge, world
from secondchair.core.workspace import STATE_DIR

PROBES = 20


def _ms(call: Callable[[], object]) -> float:
    start = time.perf_counter()
    call()
    return (time.perf_counter() - start) * 1000


def _percentiles(times: list[float]) -> str:
    ordered = sorted(times)
    p50, p95 = (
        ordered[len(ordered) // 2],
        ordered[min(len(ordered) - 1, round(0.95 * len(ordered)))],
    )
    return f"{p50:.1f} / {p95:.1f}"


def measure(size: str, seed: int = 0) -> dict[str, str]:
    """One size's row of the report."""
    with tempfile.TemporaryDirectory(prefix="secondchair-scale-") as tmp:
        root = Path(tmp) / "workspace"
        start = time.perf_counter()
        made = synth.generate(root, size, seed)
        generated = time.perf_counter() - start
        ws = made.ws
        files = [p for p in root.rglob("*") if p.is_file() and STATE_DIR not in p.parts]
        step = max(1, len(made.npcs) // PROBES)
        npcs = made.npcs[::step][:PROBES]
        return {
            "Size": f"{size} ({made.sessions})",
            "Files": str(len(files)),
            "Bytes": str(sum(p.stat().st_size for p in files)),
            "Rebuild (ms)": f"{_ms(lambda: index.rebuild(ws)):.0f}",
            "Unchanged connect (ms)": f"{_ms(lambda: index.connect(ws).close()):.0f}",
            "search_facts p50 / p95 (ms)": _percentiles(
                [_ms(lambda n=n: index.search_facts(ws, text=n["name"])) for n in npcs]
            ),
            "what_knows p50 / p95 (ms)": _percentiles(
                [_ms(lambda n=n: knowledge.known(ws, n["id"])) for n in npcs]
                + [_ms(lambda: knowledge.known(ws, "party"))]
            ),
            "world.state (ms)": f"{_ms(lambda: world.state(ws)):.0f}",
            "Generation (s)": f"{generated:.0f}",
        }


def run(sizes: list[str], seed: int = 0) -> str:
    """The Markdown report for `sizes`."""
    rows = [measure(size, seed) for size in sizes]
    header = list(rows[0])
    return "\n".join(
        [
            f"# Scaling bench (seed {seed}, no model)",
            "",
            "Wall time; sizes are sessions. Files and bytes exclude the derived `.secondchair/`.",
            "",
            "| " + " | ".join(header) + " |",
            "| --- | " + " | ".join("---:" for _ in header[1:]) + " |",
            *("| " + " | ".join(row.values()) + " |" for row in rows),
            "",
        ]
    )
