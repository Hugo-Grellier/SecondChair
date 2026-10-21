"""Editorial metrics (#182): the aggregator, the diff size and the abandoned-prep count."""

from pathlib import Path

import pytest
import yaml

from secondchair.bench import editorial
from secondchair.cli import main
from secondchair.core import workspace


def test_metrics_report_what_the_artifact_carries_and_hide_nothing(tmp_path) -> None:
    main(["init", str(tmp_path / "camp"), "--language", "en", "--calendar", "absalom"])
    ws = workspace.load(tmp_path / "camp")
    artifact = {"draft": "a\nb\nc", "adopted": "a\nB\nc\nd", "mystery": "nope", "job": 99}
    got = editorial.metrics(ws, artifact)
    assert got["diff_lines"] == 3  # b -> B is one removal and one addition, plus d
    assert got["mystery_warnings"].startswith("error:")
    assert got["cost"].startswith("error:")
    assert "guard" not in got
    table = editorial.markdown({"x1": got})
    assert "| x1 | " in table and "diff_lines" in table


def test_abandoned_prep_is_prepared_minus_played(tmp_path) -> None:
    log = tmp_path / "log.yaml"
    log.write_text(yaml.safe_dump({"prep": {"prepared": ["a", "b", "c"], "used": ["b"]}}))
    assert editorial.abandoned_prep(log) == ["a", "c"]
    template = Path(__file__).parent.parent / "docs/bench/editorial/table-log.yaml"
    assert editorial.abandoned_prep(template) == []  # the shipped template parses


def _cands() -> list[dict]:
    return [
        {
            "id": f"c{i}",
            "provenance": {"model": m, "host": "codex-cli", "tier": "deep"},
            "text": (
                f"---\nmodel: {m}\n---\n<!-- by {m} -->\n"
                f"# The Ember Court\nWritten by {m.upper()} on codex-cli."
            ),
        }
        for i, m in enumerate(["opus-x", "sonnet-y", "onepass-z"])
    ]


def test_blind_render_hides_provenance_and_seals_key_apart(tmp_path) -> None:
    out, key = tmp_path / "out", tmp_path / "key.yaml"
    letters = editorial.blind(_cands(), out, key, seed=7)
    assert sorted(p.name for p in out.iterdir()) == ["A.md", "B.md", "C.md"]
    for p in out.iterdir():
        text = p.read_text().lower()
        assert text.startswith("# candidate") and "ember court" in text
        assert not any(w in text for w in ("opus", "sonnet", "onepass", "codex", "deep", "model:"))
    sealed = yaml.safe_load(key.read_text())
    assert {k: v["id"] for k, v in sealed.items()} == letters
    assert sealed["A"]["provenance"]["model"] in {"opus-x", "sonnet-y", "onepass-z"}
    with pytest.raises(ValueError):
        editorial.blind(_cands(), out, out / "key.yaml", seed=7)


def test_blind_order_is_stable_per_seed_and_input_order(tmp_path) -> None:
    run = lambda c, s, n: editorial.blind(c, tmp_path / n, tmp_path / f"{n}.yaml", seed=s)  # noqa: E731
    assert run(_cands(), 1, "a") == run(list(reversed(_cands())), 1, "b")
    assert any(run(_cands(), s, f"s{s}") != run(_cands(), 1, f"t{s}") for s in range(2, 12))
