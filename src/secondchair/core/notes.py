"""Design notes: optional front matter on `notes/**/*.md` and its pure validator (ADR 0017).

Notes stay outside canon. The validator reports problems and never fixes them; a note without
front matter is an ordinary working note and is ignored."""

import re
from collections import defaultdict

import yaml

from secondchair.core.workspace import Workspace

STATUSES = ("draft", "playtested", "adopted", "rejected", "superseded")
CLOSED = ("rejected", "superseded")
NOTE_ID = re.compile(r"d-[0-9a-f]{8}")
CANON_DIRS = ("entities", "facts", "events")


def front_matter(text: str) -> dict | None:
    """The YAML mapping of a note's front matter, or None when it has none. Raises
    yaml.YAMLError / ValueError when it is present but unreadable."""
    if not text.startswith("---\n") or text.count("---\n") < 2:
        return None
    data = yaml.safe_load(text.split("---\n", 2)[1])
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("the front matter must be a YAML mapping")
    return data


def _ids(value) -> list | None:
    """A field that is one id or a list of ids; None when it is neither."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    ok = isinstance(value, list) and all(isinstance(i, str) for i in value)
    return value if ok else None


def check(ws: Workspace) -> list[str]:
    """One message per problem in the design notes of `notes/`."""
    errors: list[str] = []
    notes: dict[str, tuple[str, dict]] = {}  # id -> (path, front matter)
    canon = {p.stem for d in CANON_DIRS for p in (ws.root / "canon" / d).glob("*.md")}
    for p in sorted((ws.root / "notes").rglob("*.md")):
        if p.is_symlink():
            continue
        path = p.relative_to(ws.root).as_posix()
        try:
            data = front_matter(p.read_text())
        except (yaml.YAMLError, ValueError, UnicodeDecodeError) as e:
            errors.append(f"{path}: unreadable front matter: {e}")
            continue
        if not data or not ({"id", "status"} & data.keys()):
            continue  # a working note
        if not isinstance(data.get("id"), str) or not NOTE_ID.fullmatch(data["id"]):
            errors.append(f"{path}: malformed id {data.get('id')!r} (expected d-<8 hex digits>)")
        elif data["id"] in notes:
            errors.append(f"{path}: duplicate id {data['id']} (also {notes[data['id']][0]})")
        else:
            notes[data["id"]] = (path, data)
        if data.get("status") not in STATUSES:
            errors.append(f"{path}: unknown status {data.get('status')!r} ({'|'.join(STATUSES)})")
    sets = defaultdict(list)
    for nid, (path, data) in notes.items():
        if isinstance(data.get("alternatives"), str) and data["status"] == "adopted":
            sets[data["alternatives"]].append(path)
        elif "alternatives" in data and not isinstance(data["alternatives"], str):
            errors.append(f"{path}: alternatives must be a set name")
        for key in ("supersedes", "cites"):
            if (ids := _ids(data.get(key))) is None:
                errors.append(f"{path}: {key} must be a list of ids")
                continue
            for i in ids:
                if key == "cites" and i not in canon:
                    errors.append(f"{path}: cites {i!r}, which is not in canon")
                elif key == "supersedes" and i not in notes:
                    errors.append(f"{path}: supersedes unknown note {i!r}")
                elif key == "supersedes" and notes[i][1].get("status") != "superseded":
                    errors.append(f"{notes[i][0]}: superseded by {nid} but not marked superseded")
    for name, paths in sets.items():
        if len(paths) > 1:
            errors.append(f"alternatives {name!r}: {len(paths)} adopted notes ({', '.join(paths)})")
    return errors
