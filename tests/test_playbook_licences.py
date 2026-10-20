"""Every playbook ships under Apache-2.0 with its folder's own LICENSE (LIC table, LICENSING.md)."""

import json
from pathlib import Path

import pytest
import yaml

SRC = Path(__file__).parent.parent / "src"
PLAYBOOK_FOLDERS = sorted(SRC.glob("*/playbooks"))


def test_every_package_with_playbooks_is_covered() -> None:
    assert {p.parent.name for p in PLAYBOOK_FOLDERS} >= {
        "secondchair",
        "secondchair_foundry",
        "secondchair_pf2e",
    }


@pytest.mark.parametrize("folder", PLAYBOOK_FOLDERS, ids=lambda p: p.parent.name)
def test_the_playbooks_folder_is_apache_licensed(folder: Path) -> None:
    assert "Apache License" in (folder / "LICENSE").read_text()
    plugin = json.loads((folder / ".claude-plugin" / "plugin.json").read_text())
    assert plugin["license"] == "Apache-2.0"
    skills = sorted(folder.glob("skills/*/SKILL.md"))
    assert skills
    for skill in skills:
        front = yaml.safe_load(skill.read_text().split("---")[1])
        assert front["license"] == "Apache-2.0", skill
