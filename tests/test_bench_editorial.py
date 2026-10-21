"""Editorial metrics (#182): the aggregator, the diff size and the abandoned-prep count."""

from pathlib import Path

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
