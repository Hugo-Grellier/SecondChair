"""Journal application (ADR 0016, ADR 0023 layer 5): the roll-forward journal of a world-turn
occurrence, its application and its recovery. It writes through the gateway's primitives in
`delegation` and calls `calls` to open an exception call.
"""

import hashlib
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Any

import yaml

from secondchair.core import calls
from secondchair.core.delegation import (
    CANON_DIR,
    JOURNAL_DIR,
    LOG_DIR,
    OCCURRENCES_DIR,
    TABLE_FILE,
    _forget,
    _read_yaml,
    _save,
    _sync_dir,
    _write,
    current_moment,
    dump,
)
from secondchair.core.workspace import Workspace, WorkspaceError

# The roll-forward journal of a world-turn occurrence (ADR 0016)

# A fault-injection hook for tests, called at each step of a journal: "plan" before it is
# written, "journal" once it is, each path it writes, "commit" before it is deleted.
_fault: Callable[[str], None] = lambda step: None  # noqa: E731


def journal_path(ws: Workspace, key: str) -> Path:
    return ws.root / JOURNAL_DIR / f"{hashlib.sha256(key.encode()).hexdigest()[:16]}.yaml"


def _journals(ws: Workspace) -> list[tuple[Path, dict]]:
    return [(p, _read_yaml(p)) for p in sorted((ws.root / JOURNAL_DIR).glob("*.yaml"))]


def _journaled(ws: Workspace, relative: str) -> Path:
    """A journal's write target: a canon file, a log entry or an occurrence record, nothing
    else, whatever the journal file says."""
    path = (ws.root / relative).resolve()
    if (
        Path(relative).is_absolute()
        or not path.is_relative_to(ws.root.resolve())
        or path.relative_to(ws.root.resolve()).parts[0] not in (CANON_DIR, LOG_DIR, OCCURRENCES_DIR)
    ):
        raise WorkspaceError(f"A journal writes canon, the action log and occurrences: {relative}")
    return path


def _read(path: Path) -> str | None:
    return path.read_text() if path.exists() else None


def _put(path: Path, content: str | None) -> None:
    if content is None:
        _forget(path.parent)
        path.unlink(missing_ok=True)
        _sync_dir(path.parent)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, content)


def inputs_digest(ws: Workspace, journal: dict) -> str:
    """What the plan read but does not write (ADR 0016): workspace.yaml, delegation.yaml, the
    canon files it read, its entity's occurrence records that are not its targets, its targets'
    `before` contents and the action log before its first entry."""
    digest = hashlib.sha256()

    def feed(relative: str, content: bytes | None) -> None:
        digest.update(relative.encode() + b"\0")
        digest.update(b"absent" if content is None else hashlib.sha256(content).digest())

    for relative in ("workspace.yaml", TABLE_FILE, *journal["reads"]):
        path = ws.root / relative
        feed(relative, path.read_bytes() if path.is_file() else None)
    targets = {w["path"] for w in journal["writes"]}
    for p in sorted((ws.root / OCCURRENCES_DIR).glob("*.yaml")):
        relative = p.relative_to(ws.root).as_posix()
        if relative not in targets and _read_yaml(p).get("entity") == journal["entity"]:
            feed(relative, p.read_bytes())
    for w in journal["writes"]:
        feed(w["path"], None if w["before"] is None else w["before"].encode())
    first = min(
        (int(Path(w["path"]).stem) for w in journal["writes"] if w["path"].startswith(LOG_DIR)),
        default=None,
    )
    for p in sorted((ws.root / LOG_DIR).glob("*.yaml")):
        if p.stem.isdigit() and (first is None or int(p.stem) < first):
            feed(p.relative_to(ws.root).as_posix(), p.read_bytes())
    return digest.hexdigest()


def new_journal(ws: Workspace, key: str, entity: str, reads: list[str], writes: list[dict]) -> dict:
    """A journal for one occurrence and its cascade: `writes` in order, each {path, before,
    after}, the occurrence's own record last, its commit marker. Callers hold the lock."""
    journal: dict[str, Any] = {"key": key, "version": version("secondchair"), "entity": entity}
    journal |= {"reads": sorted(set(reads)), "writes": writes, "stopped": None}
    return {**journal, "inputs_digest": inputs_digest(ws, journal)}


def apply_journal(ws: Workspace, journal: dict) -> None:
    """Write the journal durably, then each of its writes in order, then delete it: once its
    last write, the commit marker, has landed (ADR 0016). Callers hold the lock."""
    _fault("plan")
    directory = ws.root / JOURNAL_DIR
    if not directory.is_dir():
        directory.mkdir(parents=True)
        _sync_dir(directory.parent)
    path = journal_path(ws, journal["key"])
    _write(path, dump(journal))
    _fault("journal")
    _roll_forward(ws, journal)
    _fault("commit")
    _put(path, None)


def _roll_forward(ws: Workspace, journal: dict) -> None:
    """Each write in order, skipped once it holds its `after`: idempotent."""
    for w in journal["writes"]:
        target = _journaled(ws, w["path"])
        if _read(target) != w["after"]:
            _put(target, w["after"])
            _fault(w["path"])


def recover(ws: Workspace, force: bool = False) -> list[str]:
    """Finish or roll back every journal left by an interrupted world-turn, one message each
    (ADR 0016). Its inputs unchanged, it rolls forward; changed, it rolls back and calls on the
    GM, whose next world-turn plans the occurrence afresh. A target holding neither its before
    nor its after stops it: the journal is kept behind an exception call, and retried only
    `force`d (`secondchair recover`). Reads no index. Callers hold the lock."""
    done = []

    def call(message: str) -> int:
        moment = current_moment(ws)[0]
        return calls.open_call(
            ws,
            kind="exception",
            responsibility="living_world",
            table_moment=moment,
            blocking=False,
            message=message,
        )["id"]

    for path, journal in _journals(ws):
        key = journal["key"]
        if journal.get("stopped") is not None and not force:
            continue
        torn = []
        for w in journal["writes"]:
            target = _journaled(ws, w["path"])
            target.with_name(target.name + ".tmp").unlink(missing_ok=True)  # a torn write
            if (current := _read(target)) not in (w["before"], w["after"]):
                torn.append((w, current))
        if torn:
            w, current = torn[0]
            journal["stopped"] = call(
                f"Occurrence {key} was interrupted and {w['path']} changed since: it holds "
                f"neither its content before nor after. Make it one of them, then run "
                f"`secondchair recover`.\nBefore:\n{w['before']}\nAfter:\n{w['after']}\n"
                f"Now:\n{current}"
            )
            _write(path, dump(journal))
            done.append(f"{key}: stopped, {w['path']} changed (call {journal['stopped']}).")
            continue
        if inputs_digest(ws, journal) == journal["inputs_digest"]:
            _roll_forward(ws, journal)
            planned, now = journal["version"], version("secondchair")
            same = planned == now
            done.append(f"{key}: completed" + ("." if same else f", planned by {planned} ({now})."))
        else:
            for w in reversed(journal["writes"]):
                target = _journaled(ws, w["path"])
                if _read(target) != w["after"]:
                    continue
                if w["path"].startswith(f"{LOG_DIR}/"):
                    entry = yaml.safe_load(w["after"])
                    if entry.get("kind") == "action":  # its target is back to before
                        _put(target, dump({**entry, "status": "undone", "reason": "recovery"}))
                else:
                    _put(target, w["before"])
            message = (
                f"Occurrence {key} was interrupted and what it read changed since: it was "
                "rolled back, and the next world-turn plans it afresh."
            )
            called = call(message)
            record = _journaled(ws, journal["writes"][-1]["path"])
            if record.exists():  # queued again, behind the call
                _save(ws, {**_read_yaml(record), "call": called}, OCCURRENCES_DIR)
            done.append(f"{key}: rolled back (call {called}).")
        _put(path, None)
    return done
