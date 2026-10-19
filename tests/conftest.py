import os
import subprocess
import sys
import textwrap
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest

type Serving = Callable[[Path, dict[str, str]], AbstractContextManager[str]]
type InstallBlock = Callable[[str, str], Path]


@pytest.fixture
def machine_config(tmp_path: Path) -> dict[str, str]:
    """A machine configuration asking for an OS-chosen port."""
    config_home = tmp_path / "config"
    (config_home / "secondchair").mkdir(parents=True)
    (config_home / "secondchair" / "config.yaml").write_text("port: 0\n")
    return {**os.environ, "XDG_CONFIG_HOME": str(config_home)}


@contextmanager
def _serving(ws: Path, env: dict[str, str]) -> Generator[str]:
    """Run `secondchair serve` on `ws` and yield its first output line."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "secondchair.cli", "serve", str(ws)],
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        yield proc.stdout.readline().strip()
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture
def serving() -> Serving:
    return _serving


@pytest.fixture
def install_block(tmp_path: Path) -> InstallBlock:
    """Install a block `name` (a module whose `tools` is a `secondchair.tools` entry point)
    into a site directory under `tmp_path`, and return that directory."""
    site = tmp_path / "site"

    def install(name: str, source: str) -> Path:
        site.mkdir(exist_ok=True)
        (site / f"{name}.py").write_text(textwrap.dedent(source))
        dist = site / f"{name}-0.1.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 0.1\n")
        (dist / "entry_points.txt").write_text(f"[secondchair.tools]\n{name} = {name}:tools\n")
        return site

    return install
