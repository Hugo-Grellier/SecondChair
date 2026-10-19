"""The machine configuration (PKG-13): what belongs to the GM's machine, never to a workspace."""

import os
import secrets
from pathlib import Path

TOKEN_FILE = "foundry-token"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "secondchair"


def foundry_token() -> str | None:
    """The token the Foundry module authenticates with (PKG-08), or None before `secondchair
    token` created it. Read on each use, so a token created while `serve` runs is picked up."""
    try:
        return (config_dir() / TOKEN_FILE).read_text().strip() or None
    except FileNotFoundError:
        return None


def ensure_foundry_token() -> str:
    """The Foundry token, generated on first use in a file only its owner can read (mode 0600)."""
    if token := foundry_token():
        return token
    path = config_dir() / TOKEN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)  # an existing empty file keeps its mode through O_CREAT
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    return token
