"""The campaign workspace: its layout and `workspace.yaml` (docs/contracts/workspace-layout.md)."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SCHEMA_VERSION = 1
CONFIG_FILE = "workspace.yaml"
STATE_DIR = ".secondchair"

# ponytail: shape check of a BCP 47 tag (language, then subtags), not a registry lookup.
_BCP47 = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")


class WorkspaceError(Exception):
    """A workspace that cannot be created or served, with a message for the GM."""


@dataclass(frozen=True)
class Workspace:
    root: Path
    schema_version: int
    campaign_language: str


def init(root: Path, language: str) -> Workspace:
    """Create a campaign workspace in `root`. The campaign language is fixed from then on."""
    config = root / CONFIG_FILE
    if config.exists():
        existing = _read(config).get("campaign_language")
        raise WorkspaceError(
            f"{root} is already a campaign workspace (campaign language {existing!r}); "
            "the campaign language is fixed at creation and cannot be changed."
        )
    if not _BCP47.match(language):
        raise WorkspaceError(f"{language!r} is not a BCP 47 language tag (for example: en, fr).")

    (root / STATE_DIR).mkdir(parents=True, exist_ok=True)
    config.write_text(
        yaml.safe_dump(
            {"schema_version": SCHEMA_VERSION, "campaign_language": language}, sort_keys=False
        )
    )
    gitignore = root / ".gitignore"
    lines = gitignore.read_text().splitlines() if gitignore.exists() else []
    if f"{STATE_DIR}/" not in lines:
        gitignore.write_text("\n".join([*lines, f"{STATE_DIR}/"]) + "\n")
    return load(root)


def load(root: Path) -> Workspace:
    """Open the workspace in `root`, refusing a schema this version cannot serve."""
    config = root / CONFIG_FILE
    if not config.is_file():
        raise WorkspaceError(f"{root} is not a campaign workspace: {CONFIG_FILE} is missing.")
    data = _read(config)
    version = data.get("schema_version")
    if not isinstance(version, int):
        raise WorkspaceError(f"{config} has no integer schema_version.")
    if version > SCHEMA_VERSION:
        raise WorkspaceError(
            f"{config} declares schema version {version}, newer than the {SCHEMA_VERSION} "
            "this SecondChair supports. Upgrade SecondChair to serve this workspace."
        )
    if version < SCHEMA_VERSION:
        raise WorkspaceError(
            f"{config} declares schema version {version}, older than {SCHEMA_VERSION}. "
            "Run `secondchair upgrade` to migrate it first."
        )
    language = data.get("campaign_language")
    if not isinstance(language, str):
        raise WorkspaceError(f"{config} has no campaign_language.")
    return Workspace(root=root, schema_version=version, campaign_language=language)


def _read(config: Path) -> dict:
    try:
        data = yaml.safe_load(config.read_text())
    except yaml.YAMLError as e:
        raise WorkspaceError(f"{config} is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise WorkspaceError(f"{config} must be a YAML mapping.")
    return data
