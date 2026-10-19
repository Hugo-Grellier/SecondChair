"""Every Foundry module is a valid, catalogue-compliant Foundry v14 package (PKG-18, LIC-15/16)."""

import json
from pathlib import Path

import pytest

FOUNDRY = Path(__file__).parent.parent / "foundry"
MODULES = sorted(p.parent for p in FOUNDRY.glob("*/module.json"))
REPO = "https://github.com/Hugo-Grellier/SecondChair"


def test_the_library_module_is_there() -> None:
    assert FOUNDRY / "secondchair-foundry" in MODULES


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_the_manifest_is_catalogue_compliant(module: Path) -> None:
    manifest = json.loads((module / "module.json").read_text())
    assert manifest["id"] == module.name
    for key in ("title", "description", "version", "url", "bugs", "readme"):
        assert manifest[key], key
    assert manifest["authors"] and all(a["name"] for a in manifest["authors"])
    assert manifest["compatibility"]["minimum"] == "14"
    assert manifest["compatibility"]["verified"].startswith("14")
    # Installed by manifest URL, downloaded from a GitHub release (PKG-18).
    assert manifest["manifest"].endswith(f"/foundry/{module.name}/module.json")
    assert manifest["download"].startswith(f"{REPO}/releases/download/")
    assert manifest["download"].endswith(f"/{module.name}.zip")
    for script in manifest.get("esmodules", []):
        assert (module / script).is_file(), script


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_the_module_is_apache_licensed(module: Path) -> None:
    manifest = json.loads((module / "module.json").read_text())
    licence = module / manifest["license"]
    assert "Apache License" in licence.read_text()
    assert "Version 2.0" in licence.read_text()
