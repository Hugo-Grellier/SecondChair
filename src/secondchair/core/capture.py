"""Capture and the wrap (04-canon-memory-capture.md, CAP-04..14, CAN-23; 05, LW-07, CAL-14).

The "wrap a session" job reads the session's Sources (the GM's text notes, the transcript) and
submits **candidate facts**, each quoting its Source verbatim with a locator; the Core drops a
candidate whose quote is not in the Source, and keys the rest by Source and quote so a rerun
yields only what is new. The job classifies each candidate against canon; the Core routes it by
class: certain and non-blocking candidates go through the memory cell of the job's moment, a
duplicate adds provenance and knowledge but no fact, and a contradiction or blocking ambiguity
is always a call on the GM. The Core itself turns a near-miss of a known name into a blocking
question and creates an entity for a new name only once two candidates attest it.

The GM's wrap (`secondchair wrap`) is the grouped round: questions first, then what was applied.
It settles the session's fictional interval, moves the current date to its end and queues the
world-turn job under living world.

Workspace files (docs/contracts/workspace-layout.md): one YAML file per candidate in `capture/`,
and `time.yaml` for the current date and the sessions' intervals.
"""

import hashlib
import json
import re
from collections.abc import Sequence
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml

from secondchair.core import calls, canon, delegation, index, jobs, knowledge, observations
from secondchair.core.calendar import CalendarError
from secondchair.core.delegation import (
    ActionResult,
    DelegationError,
    _for_agent,
    _read_yaml,
    _write,
    locked,
)
from secondchair.core.index import PARTY, CanonError
from secondchair.core.tools import Tool
from secondchair.core.workspace import Workspace

CAPTURE_DIR = "capture"
TIME_FILE = "time.yaml"
PLAYBOOK = "wrap-a-session"
WORLD_TURN = "world-turn"
CLOCK = "clock"  # a VTT clock observation, its payload {"date": a full date, ...} (CAL-12)
CLASSES = (  # CAP-10
    "certain",
    "duplicate",
    "contradiction",
    "blocking_ambiguity",
    "non_blocking_ambiguity",
)
HELD = ("contradiction", "blocking_ambiguity")  # always a call on the GM
NEAR = 0.75  # CAN-23: a name this similar to a known one, but not equal, is a near-miss


def key(source: str, quote: str) -> str:
    """A candidate's key: its Source and quoted span (CAP-06)."""
    return hashlib.sha256(f"{source}\0{quote}".encode()).hexdigest()[:16]


def near_misses(vocabulary: list[str], text: str, names: Sequence[str] = ()) -> list[str]:
    """Each "written ~ known" pair where a capitalised run of words in `text`, or one of `names`,
    is close to a known name without being it (CAN-23, CAP-12).
    ponytail: spelling similarity only; a phonetic match that is spelt apart slips through."""
    words = [re.sub(r"['\u2019]s$", "", w) for w in re.findall(r"[\w'\u2019-]+", text)]
    found = []
    for name in vocabulary:
        size = len(name.split())
        runs = [" ".join(words[i : i + size]) for i in range(len(words) - size + 1)]
        for written in [r for r in runs if r[:1].isupper()] + list(names):
            close = SequenceMatcher(None, written.casefold(), name.casefold()).ratio() >= NEAR
            if close and written.casefold() != name.casefold():
                found.append(f"{written} ~ {name}")
    return sorted(set(found))


def queue_wrap(ws: Workspace, inputs: dict[str, str]) -> dict:
    """Queue the "wrap a session" job on the session's Sources (CAP-09)."""
    return jobs.queue(
        ws,
        playbook=PLAYBOOK,
        inputs=inputs,
        expected_output="The session's candidate facts consolidated into canon.",
        responsibility="memory",
        tier="standard",
    )


def attach_transcript(ws: Workspace, session: int, transcript: Path) -> tuple[dict, bool]:
    """Give the session's wrap job its transcript as the `transcript` input (CAP-01, CAP-04):
    the session's last wrap job takes it, replacing any, while it is queued, since an agent
    reads the contract only when it starts the job. Otherwise a new wrap job is queued, with the
    last one's notes. Returns the job and whether it is a new one."""
    with locked(ws):
        wraps = [
            j
            for j in calls._jobs(ws)
            if j["playbook"] == PLAYBOOK and j["inputs"].get("session") == str(session)
        ]
        inputs = {"session": str(session), "transcript": str(transcript)}
        if wraps and wraps[-1]["status"] == "queued":
            job = wraps[-1]
            job["inputs"] = jobs._licensed(ws, {**job["inputs"], **inputs})
            delegation._save(ws, job, delegation.JOBS_DIR)
            return job, False
        notes = wraps[-1]["inputs"].get("notes") if wraps else None
        return queue_wrap(ws, {**inputs, **({"notes": notes} if notes else {})}), True


def capture(
    ws: Workspace,
    job: int,
    *,
    source: str,
    locator: str,
    quote: str,
    statement: str,
    date: str,
    classification: str = "certain",
    reason: str | None = None,
    entities: list[str] | None = None,
    relation: dict[str, str] | None = None,
    closes: list[str] | None = None,
    known_by: list[str] | None = None,
    duplicate_of: str | None = None,
    new_names: list[str] | None = None,
    inferred: bool = False,
    translation: str | None = None,
) -> dict[str, Any]:
    """Submit one candidate fact for a started wrap job. Returns its key and status: `captured`,
    `seen` (already captured: a rerun) or `dropped` (no verbatim quote, CAP-04)."""
    record, session = _wrap_job(ws, job)
    if source not in record["inputs"].values():
        raise CanonError(f"{source!r} is not a Source of job {job}: {record['inputs']}.")
    if not quote.strip():
        return {"key": None, "status": "dropped", "reason": "no quote, no fact"}
    speaker = None
    if source == record["inputs"].get("transcript"):
        if (segment := _segment(source, locator)) is None:
            return {"key": None, "status": "dropped", "reason": f"{locator} is not a segment"}
        said, speaker = segment["text"], segment["speaker"]
    else:
        said = Path(source).read_text()
    if quote not in said:
        return {"key": None, "status": "dropped", "reason": f"the quote is not in {source}"}
    candidate_key = key(source, quote)
    path = ws.root / CAPTURE_DIR / f"{candidate_key}.yaml"
    if path.exists():
        return {"key": candidate_key, "status": "seen"}
    if classification not in CLASSES:
        raise CanonError(f"classification must be one of {', '.join(CLASSES)}.")
    if classification != "certain" and not (reason and reason.strip()):
        raise CanonError(f"A {classification} candidate needs a reason the GM can read.")
    if not statement.strip():
        raise CanonError("A candidate needs a statement in the campaign language.")
    if (classification == "duplicate") != (duplicate_of is not None):
        raise CanonError("A duplicate names the fact it repeats (duplicate_of), and only it.")
    facts = {f["id"] for f in index.search_facts(ws)}
    if unknown := [f for f in (closes or []) + [duplicate_of or ""] if f and f not in facts]:
        raise CanonError(f"Unknown facts {unknown}.")
    found = index.search_entities(ws)
    known = {e["id"] for e in found} | {PARTY}
    if unknown := [e for e in (entities or []) + (known_by or []) if e not in known]:
        raise CanonError(f"Unknown entities {unknown}; a new name goes in new_names.")
    vocabulary = canon.vocabulary(ws)
    folded = {v.casefold() for v in vocabulary}
    if taken := [n for n in new_names or [] if n.casefold() in folded]:
        raise CanonError(f"{taken} already name entities: give their ids in entities.")
    if near := near_misses(vocabulary, statement, new_names or []):
        reason = "; ".join(filter(None, [reason, f"near-miss of a known name: {near}"]))
        if classification not in HELD:
            classification = "blocking_ambiguity"
    candidate = {
        "key": candidate_key,
        "session": session,
        "job": job,
        "source": source,
        "locator": locator,
        "quote": quote,
        "speaker": speaker,
        "translation": translation,
        "statement": statement.strip(),
        "date": ws.calendar.canonical(date, partial=True),
        "classification": classification,
        "reason": reason,
        "entities": list(entities or []),
        "relation": relation,
        "closes": list(closes or []),
        "known_by": list(known_by or []),
        "duplicate_of": duplicate_of,
        "new_names": list(new_names or []),
        "inferred": inferred,
        "status": "captured",
        "entries": [],
        "error": None,
    }
    with locked(ws):
        path.parent.mkdir(exist_ok=True)
        _write(path, yaml.safe_dump(candidate, sort_keys=False, allow_unicode=True))
    return {"key": candidate_key, "status": "captured"}


def candidates(ws: Workspace, session: int | None = None) -> list[dict]:
    """Every candidate, of one session when given, by key."""
    found = [_read_yaml(p) for p in sorted((ws.root / CAPTURE_DIR).glob("*.yaml"))]
    return [c for c in found if session in (None, c["session"])]


def consolidate(ws: Workspace, job: int) -> list[dict]:
    """Route the session's captured candidates through the Core, for the started wrap job
    (CAP-10, CAP-12). A candidate with a new name attested only once waits, `unattested`, for
    a later consolidation. Returns the candidates handled."""
    _, session = _wrap_job(ws, job)
    every = candidates(ws)
    attested: dict[str, int] = {}
    for c in every:
        for name in set(c["new_names"]):
            attested[name] = attested.get(name, 0) + 1
    act = _actor(ws, job)
    handled = []
    for c in candidates(ws, session):
        if c["status"] not in ("captured", "unattested"):
            continue
        named = c["classification"] not in HELD  # a held candidate creates no entity
        if named and any(attested[n] < 2 for n in c["new_names"]):
            c["status"] = "unattested"  # CAP-12: flagged, no entity
            _save(ws, c)
            handled.append(c)
            continue
        try:
            for name in c["new_names"] if named else []:
                ids = [e["id"] for e in index.search_entities(ws) if name in e["names"]]
                if not ids:
                    act("create_entity", names=[name])
                    ids = [e["id"] for e in index.search_entities(ws) if name in e["names"]]
                c["entities"] = list(dict.fromkeys(c["entities"] + ids[:1]))
            _route(ws, c, job, act)
        except (DelegationError, CanonError) as e:
            c.update(status="failed", error=str(e))
        _save(ws, c)
        handled.append(c)
    return handled


def _route(ws: Workspace, c: dict, job: int, act: Any) -> None:
    c["origin"] = {"kind": "observation", "quote": c["quote"], "locator": c["locator"]}
    if c["inferred"]:  # CAP-05: beyond the quote, an agent proposal
        c["origin"] = {"kind": "job", "job": str(job), **c["origin"]}
    if c["translation"]:
        c["origin"]["translation"] = c["translation"]
    if c.get("speaker"):  # absent from candidates captured before transcripts
        c["origin"]["speaker"] = c["speaker"]
    held = c["classification"] in HELD
    if c["duplicate_of"] is not None and not held:
        _cascade(c, c["duplicate_of"], act)
        return
    args = {
        "statement": c["statement"],
        "entities": c["entities"],
        "origin": c["origin"],
        "relation": c["relation"],
        "valid_from": None if c["closes"] else c["date"],
    }
    # CAP-10: a contradiction or blocking question is always a call, whatever the memory level.
    hold = f"{c['classification']} ({c['key']}): {c['reason']}" if held else None
    done = act("record_fact", hold=hold, **args)
    c["entries"].append(done["entry"])
    if done["status"] == "applied":
        _cascade(c, _written(ws, done["entry"]), act)
    else:  # a call on the GM; the wrap finishes the candidate once the GM approves it
        c["status"] = "held" if held else done["status"]


def _cascade(c: dict, fact: str, act: Any) -> None:
    """What follows a candidate's fact: the played event closing `closes`, then who learned it
    (CAP-08: said or shown to the table)."""
    c["fact"] = fact
    if c["closes"] and not c["duplicate_of"]:
        event = act(
            "record_event",
            description=c["statement"],
            date=c["date"],
            origin=c["origin"],
            kind="played",
            opens=[fact],
            closes=c["closes"],
        )
        c["entries"].append(event["entry"])
    for knower in c["known_by"]:
        done = act("record_knowledge", knower=knower, fact=fact, origin=c["origin"], date=c["date"])
        c["entries"].append(done["entry"])
    c["status"] = "duplicate" if c["duplicate_of"] else "applied"


def _actor(ws: Workspace, job: int | None) -> Any:
    """Take a Core memory action for the wrap, under `job` when given."""
    tools = {t.name: t for t in _tools(ws)}

    def act(tool: str, hold: str | None = None, **args: Any) -> ActionResult:
        fn = tools[tool].fn
        return delegation.act(ws, tools[tool], "wrap", lambda: fn(**args), job, hold=hold)

    return act


def _written(ws: Workspace, entry: int) -> str:
    """The id of the canon document an action log entry writes."""
    return Path(delegation.read_entry(ws, entry)["target"]).stem


def _answered(ws: Workspace, session: int) -> None:
    """Finish the session's candidates whose call the GM answered: an approved fact gets its
    event and knowledge (CAP-08), a rejected one is dropped."""
    act = _actor(ws, None)
    for c in candidates(ws, session):
        if c["status"] not in ("held", "pending"):
            continue
        status = delegation.read_entry(ws, c["entries"][0])["status"]
        if status == "applied":
            try:
                _cascade(c, _written(ws, c["entries"][0]), act)
            except (DelegationError, CanonError) as e:
                c.update(status="failed", error=str(e))
        elif status in ("rejected", "undone", "refused", "failed"):
            c["status"] = "rejected"
        else:
            continue
        _save(ws, c)


def time(ws: Workspace) -> dict:
    """`time.yaml`: the current date (null until set) and each session's interval."""
    path = ws.root / TIME_FILE
    data = _read_yaml(path) if path.exists() else {}
    return {"current_date": data.get("current_date"), "sessions": data.get("sessions") or {}}


def set_current_date(ws: Workspace, date: str) -> str:
    """Set the current date: a GM gesture (CAL-14, LW-05), outside the wrap."""
    try:
        date = ws.calendar.canonical(date)
    except CalendarError as e:
        raise DelegationError(f"Not a date of the campaign calendar: {e}") from e
    with locked(ws):
        data = time(ws)
        data["current_date"] = date
        _write_time(ws, data)
    return date


def observed_interval(ws: Workspace, session: int) -> dict[str, str] | None:
    """The session's fictional interval as the VTT clock observed it: its first and last clock
    observation in that live session, None when none was (CAL-14)."""
    dates = [
        o["payload"]["date"]
        for o in observations.of_session(ws, session)
        if o["kind"] == CLOCK and isinstance(o["payload"].get("date"), str)
    ]
    try:
        return _interval(ws, dates[0], dates[-1]) if dates else None
    except CalendarError, CanonError:
        return None  # a clock set back by hand: the GM gives the interval


def report_interval(
    ws: Workspace, job: int, start: str, end: str, quote: str, locator: str | None = None
) -> dict:
    """The session's fictional interval as the job's Source states it, quoted (CAL-14); in the
    transcript, in the segment `locator` names."""
    record, session = _wrap_job(ws, job)
    transcript = record["inputs"].get("transcript")
    segment = _segment(transcript, locator) if transcript and locator else None
    if not quote.strip() or not (
        (segment is not None and quote in segment["text"])
        or any(
            Path(s).is_file() and quote in Path(s).read_text()
            for s in record["inputs"].values()
            if s != transcript
        )
    ):
        raise CanonError("Quote the interval verbatim from one of the job's Sources.")
    with locked(ws):
        data = time(ws)
        if data["sessions"].get(session, {}).get("wrapped"):
            raise DelegationError(f"Session {session} is already wrapped.")
        interval = _interval(ws, start, end)
        data["sessions"][session] = {**interval, "from": "notes", "wrapped": False}
        _write_time(ws, data)
    return data["sessions"][session]


def wrap(
    ws: Workspace,
    session: int,
    authenticated: bool,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """The GM's grouped round (CAP-13): the session's open questions first. With none left, it
    settles the session's interval (the GM's dates over the notes', CAL-14), moves the current
    date to its end and queues the world-turn job under living world (CAP-14, LW-07)."""
    if not authenticated:
        raise DelegationError("The wrap moves fictional time: run it in an interactive terminal.")
    if delegation.current_moment(ws)[0] == "live-session":
        raise DelegationError("The wrap runs between sessions only: end the session first.")
    if running := [
        j["id"]
        for j in jobs.pending(ws)
        if j["playbook"] == PLAYBOOK and j["inputs"].get("session") == str(session)
    ]:
        raise DelegationError(
            f"Wrap jobs {running} for session {session} are not done: run them first "
            "(secondchair jobs)."
        )
    _answered(ws, session)
    found = candidates(ws, session)
    if waiting := [c["key"] for c in found if c["status"] == "captured"]:
        raise DelegationError(f"Candidates {waiting} are not consolidated yet.")
    held = {c["entries"][0] for c in found if c["status"] in ("held", "pending")}
    if not time(ws)["sessions"].get(session, {}).get("wrapped"):
        with locked(ws):
            held |= delegation.hold_whispers(ws, session)
    questions = [c for c in calls.read_calls(ws) if c["status"] == "open" and c["entry"] in held]
    summary = {"questions": questions, "candidates": found, "settled": None, "job": None}
    if questions:
        return summary
    with locked(ws):
        data = time(ws)
        noted = data["sessions"].get(session, {})
        if noted.get("wrapped"):
            raise DelegationError(f"Session {session} is already wrapped.")
        by_gm = start is not None or end is not None
        observed = observed_interval(ws, session)  # the VTT clock proposes (CAL-14)
        if by_gm or noted.get("end"):
            end = end or noted["end"]
            interval = _interval(ws, start or noted.get("start") or end, end)
            source = "gm" if by_gm else "notes"
            if not by_gm and observed and observed != interval:
                raise DelegationError(
                    f"Session {session}: the notes give {interval['start']} to "
                    f"{interval['end']}, the VTT clock observed {observed['start']} to "
                    f"{observed['end']}. Give the interval (--start, --end)."
                )
        elif observed:
            interval, source = observed, "clock"
        else:
            raise DelegationError(
                f"Session {session}'s interval is unknown: give its end date (--end)."
            )
        now = data["current_date"]
        if now and index.date_key(ws.calendar, interval["end"]) < index.date_key(ws.calendar, now):
            raise DelegationError(f"The session ends on {interval['end']}, before {now}.")
        data["current_date"] = interval["end"]
        data["sessions"][session] = {
            **interval,
            "from": source,
            "wrapped": True,
        }
        _write_time(ws, data)
    summary["settled"] = data["sessions"][session]
    summary["job"] = jobs.queue(
        ws,
        playbook=WORLD_TURN,
        inputs={"until": interval["end"], "since": interval["start"]},
        expected_output="The world advanced to the current date.",
        responsibility="living_world",
        tier="fast",  # the world-turn playbook's tier (ARC-25)
    )
    return summary


def agent_tools(ws: Workspace) -> list:
    """What the wrap job's session calls, served by the Core."""

    def capture_candidate(
        job: int,
        source: str,
        locator: str,
        quote: str,
        statement: str,
        date: str,
        classification: str = "certain",
        reason: str | None = None,
        entities: list[str] | None = None,
        relation: dict[str, str] | None = None,
        closes: list[str] | None = None,
        known_by: list[str] | None = None,
        duplicate_of: str | None = None,
        new_names: list[str] | None = None,
        inferred: bool = False,
        translation: str | None = None,
    ) -> dict[str, Any]:
        """Submit one candidate fact from a Source of your started wrap job. `quote` is the
        Source's exact words, in its language, with `locator` (file:line); with no verbatim quote
        the candidate is dropped. In a transcript, the line is the segment's and the quote is in
        its `text`; the Core records the segment's speaker. `statement` is the fact in the campaign
        language; `translation` the quote in it, when the Source is in another language.
        `date` is the campaign date it happened (the session end unless the Source says).
        `classification` against canon: certain, duplicate (name the fact in `duplicate_of`),
        contradiction, blocking_ambiguity or non_blocking_ambiguity, with a `reason` for all but
        certain. `entities` and `known_by` ("party" for what the table saw or heard, entity ids
        for NPCs or factions told) are canon ids; a name canon does not know goes in
        `new_names`. `closes`: facts this played event ends. `inferred`: the statement goes
        beyond the quote. A rerun returns `seen` for what is already captured."""
        with _for_agent():
            return capture(
                ws,
                job,
                source=source,
                locator=locator,
                quote=quote,
                statement=statement,
                date=date,
                classification=classification,
                reason=reason,
                entities=entities,
                relation=relation,
                closes=closes,
                known_by=known_by,
                duplicate_of=duplicate_of,
                new_names=new_names,
                inferred=inferred,
                translation=translation,
            )

    def report_session_interval(
        job: int, start: str, end: str, quote: str, locator: str | None = None
    ) -> dict[str, Any]:
        """Report the session's fictional interval (campaign dates) as a Source of your wrap job
        states it, quoting the Source's words; from the transcript, give the segment's `locator`
        (file:line) too."""
        with _for_agent():
            return report_interval(ws, job, start, end, quote, locator)

    def consolidate_candidates(job: int) -> list[dict[str, Any]]:
        """Once every candidate is submitted, have the Core route them: certain ones applied at
        the memory level, duplicates added as provenance, contradictions and blocking questions
        held for the GM. Returns each candidate's outcome."""
        with _for_agent():
            return consolidate(ws, job)

    def run_world_turn(job: int) -> list[dict[str, Any]]:
        """Run the world-turn a started world-turn job asks for: the Core advances the world to
        the job's `until` date. Returns the occurrences it recorded."""
        with _for_agent():
            return turn(ws, job)

    return [capture_candidate, report_session_interval, consolidate_candidates, run_world_turn]


def turn(ws: Workspace, job: int) -> list[dict]:
    """The world-turn a wrap queued (LW-07): over `]cursor, until]`, from the session's start
    when the world has no cursor yet. The computation is the Core's (LW-04); the job only
    starts it."""
    from secondchair.core import world  # it builds on canon, which builds on delegation

    record = jobs.read(ws, job)
    if record["playbook"] != WORLD_TURN or record["status"] != "started":
        raise DelegationError(f"Job {job} is not a started {WORLD_TURN} job.")
    since = None if world.cursor(ws) else record["inputs"]["since"]
    return world.world_turn(ws, record["inputs"]["until"], since=since)


def _segment(transcript: str, locator: str) -> dict | None:
    """The transcript segment a `<file>:<line>` locator names (CAP-04), None when none."""
    try:
        n = int(locator.rpartition(":")[2])
        segment = json.loads(Path(transcript).read_text().splitlines()[n - 1] if n > 0 else "")
        return segment if isinstance(segment["text"], str) and segment["speaker"] else None
    except ValueError, IndexError, KeyError, TypeError:
        return None


def _wrap_job(ws: Workspace, job: int) -> tuple[dict, int]:
    """A started wrap job and the session it wraps."""
    record = jobs.read(ws, job)
    if record["playbook"] != PLAYBOOK:
        raise DelegationError(f"Job {job} is a {record['playbook']} job, not {PLAYBOOK}.")
    if record["status"] != "started":
        raise DelegationError(f"Job {job} is {record['status']}, not started.")
    return record, int(record["inputs"]["session"])


def _tools(ws: Workspace) -> list[Tool]:
    return [*canon.tools(ws), *knowledge.tools(ws)]


def _interval(ws: Workspace, start: str, end: str) -> dict[str, str]:
    start, end = ws.calendar.canonical(start), ws.calendar.canonical(end)
    if index.date_key(ws.calendar, end) < index.date_key(ws.calendar, start):
        raise CanonError(f"The session cannot end ({end}) before it starts ({start}).")
    return {"start": start, "end": end}


def _save(ws: Workspace, c: dict) -> None:
    with locked(ws):
        path = ws.root / CAPTURE_DIR / f"{c['key']}.yaml"
        _write(path, yaml.safe_dump(c, sort_keys=False, allow_unicode=True))


def _write_time(ws: Workspace, data: dict) -> None:
    _write(ws.root / TIME_FILE, yaml.safe_dump(data, sort_keys=False))
