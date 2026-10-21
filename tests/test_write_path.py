"""One domain operation traced from the MCP call to the derived read model (#184, acceptance 1;
the seams are named in ADR 0023): an agent's `record_fact` goes through `delegation.wrap` and
`act`, which runs the tool's function under the lock; the function admits the origin and
describes the change; `act` writes the file, then appends the action log entry; the next read
rebuilds the index, finds no hand edit, and `search_facts` serves the fact. A forged origin is
refused at the same seam, with nothing written and nothing logged."""

import sqlite3
from contextlib import closing
from pathlib import Path

import jsonschema
from test_canon import JOB, SCHEMA, act, call, read, refused, ws  # noqa: F401 (ws is a fixture)

from secondchair.core import delegation, index, journal
from secondchair.core.index import FACTS_DIR, INDEX_FILE
from secondchair.core.workspace import STATE_DIR, Workspace

STATEMENT = "The ferry to Saltmere runs only at dawn."


def stamp(ws: Workspace) -> str | None:  # noqa: F811
    """The workspace fingerprint the derived index was last built from."""
    path = ws.root / STATE_DIR / INDEX_FILE
    if not path.exists():
        return None
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("select value from meta where key = 'fingerprint'").fetchone()[0]


def facts(ws: Workspace) -> list[Path]:  # noqa: F811
    return sorted((ws.root / FACTS_DIR).glob("*.md"))


def test_record_fact_is_traceable_from_mcp_call_to_search(ws: Workspace) -> None:  # noqa: F811
    logged_before, _ = delegation.read_log(ws)

    # MCP call -> wrap -> act: applied at the default table level, under one log entry.
    result = act(ws, "record_fact", statement=STATEMENT, entities=[], origin=JOB)
    assert result["status"] == "applied"

    # The action log entry, appended after the write, says who did what at which level.
    logged, errors = delegation.read_log(ws)
    assert errors == []
    [entry] = [e for e in logged if e not in logged_before]
    assert entry["id"] == result["entry"] == logged[-1]["id"]
    jsonschema.validate(entry, SCHEMA)
    assert entry["kind"] == "action"
    assert (entry["tool"], entry["responsibility"], entry["agent"]) == (
        "record_fact",
        "memory",
        "claude-prep",
    )
    assert (entry["status"], entry["approval"]) == ("applied", None)
    assert entry["before"] is None
    assert entry["target"].startswith(f"{FACTS_DIR}/f-")

    # The file write: the canon file holds exactly the entry's `after`, ranked from its origin.
    [written] = facts(ws)
    assert written.relative_to(ws.root).as_posix() == entry["target"]
    assert written.read_text() == entry["after"]
    front, body = index.split_doc(written.read_text())
    assert (front["rank"], front["origin"], body) == ("agent_proposal", JOB, STATEMENT)

    # The derived read model: the index predates the write, so the next read rebuilds it. The
    # rebuild logs hand edits first, and finds none: the log explains every canon file.
    built = stamp(ws)
    assert built is not None
    index.connect(ws).close()
    assert stamp(ws) != built
    assert delegation.read_log(ws)[0] == logged

    # The read the agent makes serves the fact as written.
    [found] = read(ws, "search_facts", text="ferry Saltmere")
    assert (found["id"], found["rank"]) == (front["id"], "agent_proposal")


def test_a_forged_origin_is_refused_at_the_same_seam(ws: Workspace) -> None:  # noqa: F811
    logged_before, _ = delegation.read_log(ws)

    # Only the world-turn writes a rule effect; an agent that claims one is refused while the
    # tool describes the change, before anything is written or logged.
    forged = {"kind": "rule", "fact": "f-00000000", "key": "front:1"}
    message = refused(ws, "record_fact", statement=STATEMENT, entities=[], origin=forged)
    assert "Only the world-turn writes a rule effect" in message
    assert facts(ws) == []
    assert delegation.read_log(ws)[0] == logged_before

    # The GM's words relayed by an agent rank as an agent proposal, never a GM decision.
    act(ws, "record_fact", statement=STATEMENT, entities=[], origin={"kind": "gm", "words": "x"})
    [found] = read(ws, "search_facts", text="ferry Saltmere")
    assert found["rank"] == "agent_proposal"
    # TODO(#232): once admission lands, an observation origin whose quote the Core cannot find
    # is refused here too (ADR 0015); on main it still ranks played.


def test_a_crash_between_apply_and_append_is_one_hand_edit_at_the_next_rebuild(
    ws: Workspace,  # noqa: F811
    monkeypatch,
) -> None:
    """Stage 0 of ADR 0023: the file is written, the process dies before the log entry exists.
    The Markdown stays authoritative; the next rebuild logs one `hand_edit` at agent_proposal,
    once, and the fact is served. Nothing is applied twice."""

    class Crash(Exception):
        pass

    append = delegation._append

    def die_before_logging(ws: Workspace, entry: dict, *args, **kwargs):
        if entry.get("kind") == "action":
            raise Crash
        return append(ws, entry, *args, **kwargs)

    logged_before, _ = delegation.read_log(ws)
    with monkeypatch.context() as crashed:
        crashed.setattr(delegation, "_append", die_before_logging)
        outcome = call(
            ws, "record_fact", agent="claude-prep", statement=STATEMENT, entities=[], origin=JOB
        )
        assert outcome.is_error

    # The write happened, the log did not: the canon file is the only record.
    [written] = facts(ws)
    assert delegation.read_log(ws)[0] == logged_before
    text = written.read_text()

    # The next read rebuilds: one hand edit, ranked agent_proposal, holding the file as written.
    index.connect(ws).close()
    logged, errors = delegation.read_log(ws)
    assert errors == []
    [edit] = [e for e in logged if e not in logged_before]
    assert edit["kind"] == "hand_edit"
    assert (edit["rank"], edit["before"], edit["after"]) == ("agent_proposal", None, text)
    assert edit["target"] == written.relative_to(ws.root).as_posix()

    # Another rebuild, and a recovery, add nothing; the file is untouched and still one fact.
    index.connect(ws).close()
    with delegation.locked(ws):
        assert journal.recover(ws) == []
    assert delegation.read_log(ws)[0] == logged
    assert facts(ws) == [written] and written.read_text() == text
    [found] = read(ws, "search_facts", text="ferry Saltmere")
    assert found["rank"] == "agent_proposal"
