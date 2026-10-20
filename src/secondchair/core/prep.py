"""Prep notes: the Markdown the GM reads to run a session, written under `prep/` (ARC-23).

Prep is a desired state, never canon (ADR 0007): what a handoff says becomes canon only once it
is played and wrapped. The files are the GM's to read, edit or delete; an agent writes them
through `write_prep`, a delegated action the Core logs and can undo (ARC-04).
"""

import re

from secondchair.core.tools import Change, Tool
from secondchair.core.workspace import Workspace

PREP_DIR = "prep"
PATH = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*(/[a-z0-9]+(-[a-z0-9]+)*)*\.md$")


def write_prep(path: str, text: str) -> Change:
    """Write one prep note, a Markdown file under the workspace's `prep/` the GM reads to run
    the table: a session's handoff (`session-3/handoff.md`), a handout's text, an improvised
    NPC card (`session-3/improv.md`). `path` is relative to `prep/`, lowercase words joined by
    dashes, folders allowed, ending in `.md`; `text` the whole new content, in the campaign
    language. Writing the same text again changes nothing. Prep is not canon: what it says
    becomes canon only once played and wrapped. To add to a note, read it first and write it
    whole: this replaces it."""
    if not PATH.match(path):
        raise ValueError(
            f"Prep path {path!r}: lowercase words joined by dashes, folders allowed, ending in "
            "`.md`, for example `session-3/handoff.md`."
        )
    if not text.strip():
        raise ValueError("A prep note needs some text; ask the GM before deleting one.")
    return Change(path=f"{PREP_DIR}/{path}", after=text if text.endswith("\n") else text + "\n")


def tools(ws: Workspace) -> list[Tool]:
    return [Tool(fn=write_prep, responsibility="prep", delegated_action=True, reversible=True)]
