import subprocess
import sys
from pathlib import Path

GUARD = Path(__file__).parent.parent / "scripts" / "guard_no_workspace.py"


def _guard(*paths: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), *paths],
        capture_output=True,
        text=True,
        check=False,
        cwd=GUARD.parent.parent,
    )


def test_guard_fails_on_a_workspace_outside_the_sample_folder() -> None:
    result = _guard("src/secondchair/workspace.py", "campaigns/westerhold/workspace.yaml")
    assert result.returncode == 1
    assert "campaigns/westerhold/workspace.yaml" in result.stdout


def test_guard_fails_on_a_derived_index() -> None:
    assert _guard("my-campaign/.secondchair/index.sqlite").returncode == 1


def test_guard_fails_on_sources() -> None:
    result = _guard("recordings/session-03.flac", "worlds/beginner-box/world.json")
    assert result.returncode == 1
    assert result.stdout.count("looks like a Source") == 2


def test_guard_exempts_the_sample_campaign() -> None:
    assert _guard("sample-campaign/workspace.yaml", "README.md").returncode == 0


def test_guard_passes_on_the_repository_itself() -> None:
    assert _guard().returncode == 0
