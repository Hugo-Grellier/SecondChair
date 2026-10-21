import functools
import os
import socket
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
    return {
        **os.environ,
        "XDG_CONFIG_HOME": str(config_home),
        "XDG_DATA_HOME": str(tmp_path / "data"),
    }


@functools.cache
def _loopback() -> bool:
    """Whether this process can listen on and connect to 127.0.0.1 (a sandbox may forbid it)."""
    try:
        with socket.create_server(("127.0.0.1", 0)) as server:
            socket.create_connection(server.getsockname(), timeout=2).close()
    except OSError:
        return False
    return True


@contextmanager
def _serving(ws: Path, env: dict[str, str]) -> Generator[str]:
    """Run `secondchair serve` on `ws` and yield its first output line.
    Skips the test where loopback is unavailable, rather than hang reading that line."""
    if not _loopback():
        pytest.skip("no loopback network in this environment")
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
