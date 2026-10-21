"""The worked NPC dossiers of the sample campaign (#176): ADR 0017 front matter, the required
sections, and no secret reaching text a player can hear."""

import re
from pathlib import Path

import pytest
from test_s0_probes import GOLD, SAMPLE, rebuild

from secondchair.core import index, knowledge

DOSSIERS = sorted((SAMPLE / "notes/npcs").glob("*.md"))
SECTIONS = (
    "Desire, need, fear, contradiction",
    "Relationships",
    "Current attitude",
    "Voice and body",
    "Improvisation rules",
    "Change triggers",
)
SECRETS = [*GOLD["leak_checks"]["forbidden_party_strings"], "diverted", "toll reserve"]


def test_three_dossiers_have_the_front_matter_and_sections() -> None:
    assert [p.stem for p in DOSSIERS] == ["npc-edda", "npc-mira", "npc-tovan"]
    labels = set(re.findall(r"\*\*(B\d\d)\*\*", (SAMPLE / "bible.md").read_text()))
    for path in DOSSIERS:
        front, body = index.split_doc(path.read_text())
        assert re.fullmatch(r"d-[0-9a-f]{8}", front["id"])
        assert front["status"] == "draft"
        assert front["cites"] and set(front["cites"]) <= labels
        assert all(f"## {s}" in body for s in SECTIONS)


@pytest.mark.parametrize("path", DOSSIERS, ids=lambda p: p.stem)
def test_no_secret_is_restated_and_every_spoken_line_passes_the_party_guard(
    path: Path, tmp_path: Path
) -> None:
    ws, _, facts = rebuild(tmp_path)
    text = path.read_text()
    assert not [s for s in SECRETS if s.lower() in text.lower()]
    spoken = re.findall(r'(?:Opening line|If asked[^:]*): "([^"]+)"', text)
    assert len(spoken) >= 2
    common = [facts["bell-ringing"], facts["council-controls-gate"]]
    for line in spoken:
        knowledge.guard(ws, knowledge.PARTY, line, [])  # canaries and names the party lacks
    # The guard is live: the secret name in a line is refused.
    with pytest.raises(knowledge.AudienceRefused):
        knowledge.guard(ws, knowledge.PARTY, "Ilex Venn keeps it.", common)
