"""The situation card's latency on a generated campaign (#188 D1, live-director.md: p95 <= 500 ms
from gesture to what the Desk renders)."""

import statistics
import time
from pathlib import Path

from secondchair.bench import synth
from secondchair.core import delegation, observations
from secondchair_foundry import desk

TARGET = 0.5  # seconds, p95
MARGIN = 3  # a shared CI runner is slower and noisier than the GM's machine
PULLS = 20


def test_the_situation_card_is_assembled_within_its_latency_target(tmp_path: Path) -> None:
    made = synth.generate(tmp_path / "workspace", "S")
    ws = made.ws
    delegation.start_session(ws)
    session = delegation.current_session(ws)
    here = made.npcs[:5]
    for i, said in enumerate(
        [{"kind": "scene", "payload": {"action": "activate", "name": "Hall"}}]
        + [{"kind": "chat", "payload": {"speaker": n["name"], "text": "Hm."}} for n in here]
    ):
        envelope = {"id": f"o{i}", "session": session, "at": f"2026-10-21T20:00:{i:02d}Z"}
        envelope |= {"scene": "Scene.hall", "actor": None, "visibility": "players"}
        assert observations.record(ws, envelope | said) is None

    took = []
    for _ in range(PULLS):  # gesture -> the desk message that carries the card
        start = time.perf_counter()
        assert desk.take(ws, {"type": "gesture", "id": "g", "gesture": "situation"})["ok"]
        card = desk.state(ws)["situation"]
        took.append(time.perf_counter() - start)

    assert {n["id"] for n in card["npcs"]} == {n["id"] for n in here}
    p95 = statistics.quantiles(took, n=20)[-1]
    print(f"situation card p95 {p95 * 1000:.0f} ms over {PULLS} pulls")
    assert p95 <= TARGET * MARGIN, f"p95 {p95:.3f} s"
