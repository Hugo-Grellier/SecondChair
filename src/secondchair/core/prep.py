"""Prep notes: the Markdown the GM reads to run a session, written under `prep/` (ARC-23).

Prep is a desired state, never canon (ADR 0007): what a handoff says becomes canon only once it
is played and wrapped. The files are the GM's to read, edit or delete; an agent writes them
through `write_prep`, a delegated action the Core logs and can undo (ARC-04).
"""

import re
from typing import Any

import yaml

from secondchair.core import knowledge
from secondchair.core.index import PARTY, CanonError
from secondchair.core.tools import Change, Tool
from secondchair.core.workspace import Workspace

PREP_DIR = "prep"
PATH = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*(/[a-z0-9]+(-[a-z0-9]+)*)*\.md$")
FENCE = "```yaml\n"
GUIDE = "players-guide.md"
# The fixed notice of an adventure's players' guide (#178), verbatim from prepare-an-adventure.
UNOFFICIAL = (
    "Options in this guide written by a model are unofficial: they are not published rules, "
    "and the GM decides whether the table uses them."
)


def read_prep(ws: Workspace, path: str) -> str:
    """The text of the prep note `path` (relative to `prep/`), never a path outside it."""
    if not PATH.match(path) or not (ws.root / PREP_DIR / path).is_file():
        raise CanonError(f"No prep note {path!r}: give its path relative to `prep/`.")
    return (ws.root / PREP_DIR / path).read_text()


def index_block(text: str) -> dict[str, Any]:
    """The YAML index a prep file ends with: its last fenced `yaml` block, which must close the
    file (the GM may edit it by hand). Empty when the file has none; `CanonError` when the block
    is not a mapping."""
    body = text.rstrip()
    start = body.rfind(FENCE)
    if start < 0 or not body.endswith("```"):
        return {}
    try:
        block = yaml.safe_load(body[start + len(FENCE) : -3])
    except yaml.YAMLError as e:
        raise CanonError(f"The index block is not valid YAML: {e}") from e
    if block is None:
        return {}
    if not isinstance(block, dict):
        raise CanonError("The index block must be a YAML mapping.")
    return block


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
    def check_prep_guide(path: str, at: str | None = None) -> dict[str, Any]:
        """Check a whole prep note, such as an adventure's players' guide, before the GM shares
        it with the players: the audience guard (as for check_audience_content) run for the
        party over the entire file. Refused when the text carries a canary or a name the party
        holds no fact about, or when the `cites` of its index block (the ids of the facts it
        uses; flavour with no truth value cites nothing) name an unknown fact or one the party
        does not know. A players' guide (a file named `players-guide.md`) is also refused
        without its fixed notice, verbatim: "Options in this guide written by a model are
        unofficial: they are not published rules, and the GM decides whether the table uses
        them." A read: it changes nothing. Returns the mode each cited fact is held in."""
        text = read_prep(ws, path)
        cites = index_block(text).get("cites") or []
        if not (isinstance(cites, list) and all(isinstance(c, str) for c in cites)):
            raise CanonError("`cites` in the index block must be a list of fact ids.")
        notice = ""
        if path.rsplit("/", 1)[-1] == GUIDE and UNOFFICIAL not in " ".join(text.split()):
            notice = f"A players' guide must carry the notice, verbatim: {UNOFFICIAL!r}."
        try:
            held = knowledge.guard(ws, PARTY, text, cites, at)
        except knowledge.AudienceRefused as e:
            raise knowledge.AudienceRefused(f"{e} {notice}".strip()) from e
        if notice:
            raise knowledge.AudienceRefused(notice)
        return held

    return [
        Tool(fn=write_prep, responsibility="prep", delegated_action=True, reversible=True),
        Tool(fn=check_prep_guide, responsibility="prep", delegated_action=False, reversible=True),
    ]
