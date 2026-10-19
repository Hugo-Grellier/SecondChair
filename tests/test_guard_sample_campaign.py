import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
GUARD = ROOT / "scripts" / "guard_sample_campaign.py"


def _guard(*paths: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), *paths],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )


def test_sample_passes() -> None:
    result = _guard()
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize("term", ["Golarion", "sArEnRaE", "Absalom", "Calistril", "Cayden Cailean"])
def test_planted_setting_term_fails(tmp_path: Path, term: str) -> None:
    nested = tmp_path / "sessions"
    nested.mkdir()
    (nested / "planted.md").write_text(f"An original scene.\nThe name is {term}.\n")
    result = _guard(str(tmp_path))
    assert result.returncode == 1
    assert "planted.md:2:" in result.stdout and term in result.stdout


def test_whole_terms_and_all_sample_files(tmp_path: Path) -> None:
    # Ordinary substrings must not create false positives (Geb / together).
    (tmp_path / "note.md").write_text("Together we mend the rope. A firedaydream.\n")
    assert _guard(str(tmp_path)).returncode == 0
    (tmp_path / "gold.yaml").write_text('secret_name: "Otari"\n')
    assert _guard(str(tmp_path)).returncode == 1


def test_missing_or_empty_sample_fails(tmp_path: Path) -> None:
    assert _guard(str(tmp_path / "missing")).returncode == 1
    assert _guard(str(tmp_path)).returncode == 1
