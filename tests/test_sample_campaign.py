"""Integrity checks for the authored S0 reference; no rebuild agent or LLM judge."""

import hashlib
import re
from collections import Counter
from pathlib import Path

import yaml

from secondchair.core.calendar import from_config

SAMPLE = Path(__file__).parent.parent / "sample-campaign"
GOLD = yaml.safe_load((SAMPLE / "gold.yaml").read_text())
BIBLE = (SAMPLE / "bible.md").read_text()


def test_real_sample_calendar_and_authored_date_answers() -> None:
    config = yaml.safe_load((SAMPLE / "campaign.yaml").read_text())
    calendar = from_config(config["calendar"])
    assert config["campaign_language"] == "en"
    assert len(calendar.months) == 10 and len(calendar.weekdays) == 6
    assert calendar.months[4].days == 1
    assert calendar.leap is not None and calendar.leap.interval == 5
    for probe in GOLD["calendar_probes"]:
        operation = getattr(calendar, probe["operation"])
        args = [probe["date"]]
        if "duration" in probe:
            args.append(probe["duration"])
        assert operation(*args) == probe["expected"], probe
    # Exercise the actual supplied definition across the festival and year boundary.
    for start in ("0302-04-25", "0302-10-28", "0303-10-28"):
        for days in range(20):
            end = calendar.add(start, f"{days}d")
            assert calendar.diff(start, end) == days
            assert calendar.add(end, f"-{days}d") == start


def test_reference_inventory_and_secret_zones() -> None:
    kinds = Counter(entity["kind"] for entity in GOLD["entities"].values())
    assert kinds["faction"] == 3 and kinds["npc"] == 6 and kinds["pc"] == 4
    assert kinds["front"] == 2 and kinds["situation"] == 3
    hidden = GOLD["entities"]["npc-hidden"]
    assert hidden["names"] == ["Ilex Venn"]
    assert hidden["public_names"] == hidden["aliases"] == []
    mystery = GOLD["mystery"]
    assert len(mystery["conclusions"]) == 2 and len(mystery["nodes"]) == 4
    clues = [clue for node in mystery["nodes"].values() for clue in node["clues"]]
    supported = [clue for item in mystery["conclusions"].values() for clue in item["supported_by"]]
    assert len(set(clues)) == len(clues) == 7 and set(supported) == set(clues)
    sections = dict(re.findall(r"^### (secret-[\w-]+)\n(.*?)(?=^### |\Z)", BIBLE, re.M | re.S))
    assert sections.keys() == GOLD["secret_zones"].keys()
    for zone, section in sections.items():
        markers = re.findall(r"CANARY-[a-z]+-\d+", section)
        assert markers == [GOLD["secret_zones"][zone]["marker"]]
    assert set(re.findall(r"\*\*(B\d+)\*\*", BIBLE)) == GOLD["facts"].keys()
    for fact in GOLD["facts"].values():
        assert fact["source"].split("#")[1] in GOLD["facts"]


def test_capture_quotes_are_in_the_real_notes_and_cover_numbered_events() -> None:
    candidates = GOLD["capture"]["candidates"]
    assert len(candidates) == 8
    expected_lines = {}
    for relative in GOLD["inputs"]["wrap_material"]:
        text = (SAMPLE / relative).read_text()
        for label, quote in re.findall(r"^- \*\*(S\d-\d+)\*\*: (.+)$", text, re.M):
            expected_lines[label] = (relative, quote)
    assert {candidate["line_id"] for candidate in candidates} == expected_lines.keys()
    for candidate in candidates:
        assert (candidate["source"], candidate["quote"]) == expected_lines[candidate["line_id"]]
        assert candidate["expected"]
    assert set(GOLD["scripted_gm"]["admit_candidates"]) == {c["id"] for c in candidates}
    for rejected in GOLD["capture"]["reject_as_new_facts"]:
        assert rejected["text"] in (SAMPLE / rejected["source"]).read_text()


def test_freeze_binds_the_complete_material_and_reference_set() -> None:
    assert GOLD["status"] == "frozen"
    assert GOLD["review"]["mode"] == "agent-emulated-gm"
    assert GOLD["review"]["human_signoff"] is True
    assert GOLD["review"]["gold_authorship"] == "agent"
    manifest = {}
    for line in (SAMPLE / "frozen.sha256").read_text().splitlines():
        digest, relative = line.split("  ", 1)
        manifest[relative] = digest
    actual = {
        p.relative_to(SAMPLE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in SAMPLE.rglob("*")
        if p.is_file() and p.name != "frozen.sha256"
    }
    assert actual == manifest, "Frozen S0 changed; review and version any intentional amendment."
