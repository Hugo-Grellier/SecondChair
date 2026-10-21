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
        assert "<!--" not in text and "---" not in text
        assert not any(w in text for w in ("opus", "sonnet", "onepass", "codex", "deep", "model:"))
    sealed = yaml.safe_load(key.read_text())
    assert {k: v["id"] for k, v in sealed.items()} == letters
    by_id = {c["id"]: c for c in _cands()}
    for entry in sealed.values():
        assert entry["provenance"] == by_id[entry["id"]]["provenance"]


def test_blind_refuses_bad_key_and_bad_input_before_writing(tmp_path) -> None:
    out = tmp_path / "out"
    for key in (out, out / "key.yaml", out / "sub" / "key.yaml"):
        with pytest.raises(ValueError, match="outside"):
            editorial.blind(_cands(), out, key, seed=1)
    many = [{"id": f"c{i}", "provenance": {}, "text": "x"} for i in range(27)]
    bad = [
        many,
        [{"id": "a", "provenance": {}, "text": "x"}] * 2,
        [{"id": "a", "provenance": {"m": ["x"]}, "text": "x"}],
        [{"id": "a", "provenance": {"m": "ab"}, "text": "x"}],
    ]
    for cands in bad:
        with pytest.raises(ValueError):
            editorial.blind(cands, out, tmp_path / "k.yaml", seed=1)
    assert not out.exists() and not (tmp_path / "k.yaml").exists()
    out.mkdir()
    (out / "stale.md").write_text("old")
    with pytest.raises(ValueError, match="not empty"):
        editorial.blind(_cands(), out, tmp_path / "k.yaml", seed=1)


def test_blind_redacts_loosely_longest_first_and_handles_front_matter_shapes(tmp_path) -> None:
    c = {
        "id": "a",
        "provenance": {"model": "opus", "full": "Opus 4", "blank": "  "},
        "text": "﻿ \r\n---\r\nmodel: Opus_4\r\n---\r\nBy opus-4 and OPUS.\r\n",
    }
    editorial.blind([c], tmp_path / "o", tmp_path / "k.yaml", seed=0)
    text = (tmp_path / "o/A.md").read_text()
    assert "opus" not in text.lower() and "model:" not in text
    assert text.count("[redacted]") == 2  # 'opus-4' is one match, not '[redacted]-4'
    eof = {"id": "b", "provenance": {}, "text": "---\nsecret: yes\n---"}
    editorial.blind([eof], tmp_path / "p", tmp_path / "k2.yaml", seed=0)
    assert "secret" not in (tmp_path / "p/A.md").read_text()


def test_blind_value_only_in_front_matter_and_order_stable(tmp_path) -> None:
    fm = {"id": "z", "provenance": {"model": "zeta-9"}, "text": "---\nmodel: zeta-9\n---\nBody."}
    editorial.blind([fm], tmp_path / "f", tmp_path / "fk.yaml", seed=0)
    assert "zeta" not in (tmp_path / "f/A.md").read_text()
    a, b = tmp_path / "a", tmp_path / "b"
    la = editorial.blind(_cands(), a, tmp_path / "a.yaml", seed=1)
    lb = editorial.blind(list(reversed(_cands())), b, tmp_path / "b.yaml", seed=1)
    assert la == lb
    files = lambda d: {p.name: p.read_text() for p in d.iterdir()}  # noqa: E731
    assert files(a) == files(b)
    assert (tmp_path / "a.yaml").read_text() == (tmp_path / "b.yaml").read_text()
    other = [
        editorial.blind(_cands(), tmp_path / f"s{s}", tmp_path / f"s{s}.yaml", seed=s)
        for s in range(2, 12)
    ]
    assert any(o != la for o in other)
