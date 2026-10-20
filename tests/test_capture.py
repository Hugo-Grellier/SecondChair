"""Capture and the wrap (04-canon-memory-capture.md, CAP-04..14, CAN-23; LW-07): candidate facts
quote the GM's notes verbatim, the wrap job routes them by class, and the GM's wrap settles the
session interval, advances the current date and queues the world-turn."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp import Client

from secondchair import cli
from secondchair.cli import main
from secondchair.core import capture, delegation, index, jobs, workspace, world
from secondchair.core.server import build_server
from secondchair.core.workspace import Workspace

SESSION_1 = (Path(__file__).parents[1] / "sample-campaign/sessions/01-dry-bell.md").resolve()
GAUGE = "The party inspected the dry gauge at the Weir and saw it stay at zero while the bell rang."
FEE = "Edda paid the party 12 silver coins for inspecting the bell chain."


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    ws = workspace.init(tmp_path / "campaign", "en", "absalom")
    delegation.change_moment(ws, "between-sessions")
    return ws


def entity(ws: Workspace, name: str) -> str:
    [tool] = [t for t in capture._tools(ws) if t.name == "create_entity"]
    delegation.act(ws, tool, "test", lambda: tool.fn(names=[name]))
    [found] = [e for e in index.search_entities(ws) if e["names"] == [name]]
    return found["id"]


def wrap_job(ws: Workspace, session: int = 1) -> int:
    job = jobs.queue(
        ws,
        playbook="wrap-a-session",
        inputs={"session": str(session), "notes": str(SESSION_1)},
        expected_output="",
        responsibility="memory",
        tier="standard",
    )
    jobs.start(ws, job["id"], {"host": "h", "model": "m", "effort": "e"}, manual=True)
    return job["id"]


def submit(ws: Workspace, job: int, quote: str, **fields: Any) -> dict:
    args: dict = {
        "source": str(SESSION_1),
        "locator": "01-dry-bell.md:7",
        "quote": quote,
        "statement": quote,
        "date": "4726-01-02",
    }
    return capture.capture(ws, job, **(args | fields))


def test_a_candidate_without_a_verbatim_quote_is_dropped_and_a_rerun_yields_only_new_ones(
    ws: Workspace,
) -> None:
    job = wrap_job(ws)

    assert submit(ws, job, "")["status"] == "dropped"
    assert submit(ws, job, "The party paid Edda 12 silver coins.")["status"] == "dropped"
    first = submit(ws, job, GAUGE)
    assert first["status"] == "captured"

    rerun = [submit(ws, job, GAUGE), submit(ws, job, FEE)]

    assert [c["status"] for c in rerun] == ["seen", "captured"]
    assert rerun[0]["key"] == first["key"]
    stored = sorted((ws.root / capture.CAPTURE_DIR).glob("*.yaml"))
    assert [yaml.safe_load(p.read_text())["quote"] for p in stored] == sorted(
        [GAUGE, FEE], key=lambda q: capture.key(str(SESSION_1), q)
    )


def set_memory(ws: Workspace, level: str) -> None:
    table = yaml.safe_load((ws.root / delegation.TABLE_FILE).read_text())
    table["between-sessions"]["memory"]["level"] = level
    (ws.root / delegation.TABLE_FILE).write_text(yaml.safe_dump(table))


def test_a_certain_candidate_is_applied_as_played_with_who_saw_it(ws: Workspace) -> None:
    edda, weir = entity(ws, "Edda Vale"), entity(ws, "Weir")
    job = wrap_job(ws)
    submit(ws, job, GAUGE, entities=[weir], known_by=["party"])
    submit(ws, job, FEE, entities=[edda], known_by=["party", edda])

    done = capture.consolidate(ws, job)

    assert [c["status"] for c in done] == ["applied", "applied"]
    facts = {f["statement"]: f for f in index.search_facts(ws)}
    assert facts[GAUGE]["rank"] == "played"
    assert facts[GAUGE]["origin"] == {
        "kind": "observation",
        "quote": GAUGE,
        "locator": "01-dry-bell.md:7",
    }
    assert facts[FEE]["valid_from"] == "4726-01-02"
    party = {k["fact"] for k in index.search_knowledge(ws, ["party"])}
    assert party == {facts[GAUGE]["id"], facts[FEE]["id"]}
    assert capture.consolidate(ws, job) == []  # nothing new


def test_an_inferred_candidate_is_an_agent_proposal_carrying_its_quote_as_evidence(
    ws: Workspace,
) -> None:
    job = wrap_job(ws)
    submit(ws, job, GAUGE, inferred=True, translation="La jauge reste à zéro.", known_by=["party"])

    [done] = capture.consolidate(ws, job)

    assert done["status"] == "applied"
    [fact] = index.search_facts(ws)
    assert fact["rank"] == "agent_proposal"  # #167: the quote does not make it played
    assert fact["origin"] == {
        "kind": "job",
        "job": str(job),
        "quote": GAUGE,
        "locator": "01-dry-bell.md:7",
        "translation": "La jauge reste à zéro.",
    }
    [known] = index.search_knowledge(ws, ["party"])
    assert known["origin"]["kind"] == "job"
    index.rebuild(ws)  # replayed from the files
    assert index.search_facts(ws)[0]["rank"] == "agent_proposal"


def test_an_inferred_candidate_cannot_close_played_canon_and_its_duplicate_is_a_proposal(
    ws: Workspace,
) -> None:
    edda = entity(ws, "Edda Vale")
    job = wrap_job(ws)
    submit(ws, job, GAUGE)
    [gauge] = capture.consolidate(ws, job)
    submit(ws, job, FEE, inferred=True, closes=[gauge["fact"]])
    told = "The party told Edda that the gauge stayed at zero while the bell rang."
    submit(
        ws,
        job,
        told,
        inferred=True,
        classification="duplicate",
        reason="known",
        duplicate_of=gauge["fact"],
        known_by=[edda],
    )

    done = {c["quote"]: c for c in capture.consolidate(ws, job)}

    # An agent proposal cannot close a played fact (CAN-08): on main it ranked played and did.
    assert done[FEE]["status"] == "failed" and "ranks played" in done[FEE]["error"]
    assert done[told]["status"] == "duplicate"
    [known] = index.search_knowledge(ws, [edda])
    assert (known["rank"], known["origin"]["kind"]) == ("agent_proposal", "job")


def test_an_approved_inferred_question_stays_an_agent_proposal(ws: Workspace) -> None:
    job = wrap_job(ws)
    submit(ws, job, GAUGE, inferred=True, classification="contradiction", reason="?")
    [held] = capture.consolidate(ws, job)
    jobs.end(ws, job)

    delegation.approve(ws, held["entries"][0], "cli", authenticated=True)
    capture.wrap(ws, 1, authenticated=True, end="4726-01-02")

    [fact] = index.search_facts(ws)
    assert (fact["rank"], fact["origin"]["kind"]) == ("agent_proposal", "job")


@pytest.mark.parametrize("level", ["act-then-review", "autonomous"])
def test_a_contradiction_is_always_a_call_whatever_the_memory_level(
    ws: Workspace, level: str
) -> None:
    set_memory(ws, level)
    job = wrap_job(ws)
    submit(
        ws,
        job,
        GAUGE,
        classification="contradiction",
        reason="The gauge moved in canon.",
        known_by=["party"],
    )

    [held] = capture.consolidate(ws, job)
    jobs.end(ws, job)

    assert held["status"] == "held"
    assert index.search_facts(ws) == []
    summary = capture.wrap(ws, 1, authenticated=True, end="4726-01-02")
    [call] = summary["questions"]
    assert summary["settled"] is None  # questions first: nothing settles while one is open
    assert call["kind"] == "proposal"
    assert call["entry"] == held["entries"][0]
    assert "The gauge moved in canon." in call["message"]
    assert delegation.read_entry(ws, call["entry"])["status"] == "pending"


def test_an_approved_question_gets_its_knowledge_and_a_rejected_one_is_dropped(
    ws: Workspace,
) -> None:
    job = wrap_job(ws)
    for quote in (GAUGE, FEE):
        submit(ws, job, quote, classification="contradiction", reason="?", known_by=["party"])
    gauge, fee = sorted(capture.consolidate(ws, job), key=lambda c: c["quote"] != GAUGE)
    jobs.end(ws, job)
    delegation.approve(ws, gauge["entries"][0], "cli", authenticated=True)
    delegation.reject(ws, fee["entries"][0], "contradiction", "cli", authenticated=True)

    summary = capture.wrap(ws, 1, authenticated=True, end="4726-01-02")

    assert summary["questions"] == []
    assert {c["quote"]: c["status"] for c in summary["candidates"]} == {
        GAUGE: "applied",
        FEE: "rejected",
    }
    [fact] = index.search_facts(ws)
    assert [k["fact"] for k in index.search_knowledge(ws, ["party"])] == [fact["id"]]


def test_a_near_miss_holds_even_a_duplicate_and_case_variants_are_known_names(
    ws: Workspace,
) -> None:
    edda = entity(ws, "Edda Vale")
    job = wrap_job(ws)
    submit(ws, job, GAUGE, known_by=["party"])
    [gauge] = capture.consolidate(ws, job)
    submit(
        ws,
        job,
        FEE,
        statement="Eda Vale saw the gauge.",
        classification="duplicate",
        reason="Already canon.",
        duplicate_of=gauge["fact"],
        known_by=[edda],
    )
    with pytest.raises(index.CanonError, match="already name"):
        submit(ws, job, "Table chatter: perhaps the cook", new_names=["edda vale"])

    [dup] = capture.consolidate(ws, job)

    assert (dup["classification"], dup["status"]) == ("blocking_ambiguity", "held")
    assert "Already canon.; near-miss" in dup["reason"]
    assert index.search_knowledge(ws, [edda]) == []


def test_only_a_started_wrap_job_captures_and_a_wrapped_session_stays_settled(
    ws: Workspace,
) -> None:
    other = jobs.queue(
        ws,
        playbook="rebuild-entities-from-a-bible",
        inputs={"bible": str(SESSION_1)},
        expected_output="",
        responsibility="memory",
        tier="standard",
    )["id"]
    jobs.start(ws, other, {"host": "h", "model": "m", "effort": "e"}, manual=True)
    with pytest.raises(delegation.DelegationError, match="not wrap-a-session"):
        capture.capture(
            ws, other, source=str(SESSION_1), locator="", quote=GAUGE, statement="x", date="4726"
        )
    job = wrap_job(ws)
    jobs.end(ws, other)
    interval = "fictional interval 0302-04-25 to 0302-04-26"
    capture.report_interval(ws, job, "4726-01-01", "4726-01-02", interval)
    with pytest.raises(delegation.DelegationError, match="not done"):
        capture.wrap(ws, 1, authenticated=True)
    jobs.end(ws, job)
    capture.wrap(ws, 1, authenticated=True)
    rerun = wrap_job(ws)
    with pytest.raises(delegation.DelegationError, match="already wrapped"):
        capture.report_interval(ws, rerun, "4726-01-01", "4726-01-02", interval)


def test_a_singly_attested_new_name_is_flagged_and_a_second_attestation_creates_it(
    ws: Workspace,
) -> None:
    job = wrap_job(ws)
    submit(ws, job, GAUGE, new_names=["Brannoc"])

    [first] = capture.consolidate(ws, job)

    assert first["status"] == "unattested"
    assert index.search_entities(ws) == []
    assert index.search_facts(ws) == []

    submit(ws, job, FEE, new_names=["Brannoc"])
    done = capture.consolidate(ws, job)

    assert [c["status"] for c in done] == ["applied", "applied"]
    [brannoc] = index.search_entities(ws)
    assert brannoc["names"] == ["Brannoc"]
    assert all(brannoc["id"] in c["entities"] for c in done)


@pytest.mark.parametrize(
    "fields",
    [
        {"statement": "Edda Vail paid the party 12 silver coins."},
        {"new_names": ["Eda Vale"]},
    ],
)
def test_a_near_miss_of_a_known_name_is_a_blocking_question(ws: Workspace, fields: dict) -> None:
    entity(ws, "Edda Vale")
    set_memory(ws, "autonomous")
    job = wrap_job(ws)

    assert submit(ws, job, FEE, **fields)["status"] == "captured"
    [held] = capture.consolidate(ws, job)

    assert held["classification"] == "blocking_ambiguity"
    assert "~ Edda Vale" in held["reason"]
    assert held["status"] == "held"
    assert [e["names"] for e in index.search_entities(ws)] == [["Edda Vale"]]


def test_exact_and_possessive_names_are_not_near_misses() -> None:
    known = ["Edda Vale", "Weir", "Reed Union"]
    text = "Edda Vale's coins; the Reed Union's watch at the Weir."
    assert capture.near_misses(known, text) == []
    assert capture.near_misses(known, "Edda Vail at the Wier") == [
        "Edda Vail ~ Edda Vale",
        "Wier ~ Weir",
    ]


def test_a_duplicate_adds_provenance_and_knowledge_but_no_fact(ws: Workspace) -> None:
    edda = entity(ws, "Edda Vale")
    job = wrap_job(ws)
    submit(ws, job, GAUGE, known_by=["party"])
    [gauge] = capture.consolidate(ws, job)
    told = "The party told Edda that the gauge stayed at zero while the bell rang."
    submit(
        ws,
        job,
        told,
        classification="duplicate",
        reason="The gauge fact is already canon; Edda learns it.",
        duplicate_of=gauge["fact"],
        known_by=[edda],
    )

    [dup] = capture.consolidate(ws, job)

    assert dup["status"] == "duplicate"
    assert dup["fact"] == gauge["fact"]
    assert len(index.search_facts(ws)) == 1
    assert [k["fact"] for k in index.search_knowledge(ws, [edda])] == [gauge["fact"]]


def test_after_the_wrap_the_current_date_is_the_session_end_and_a_world_turn_is_queued(
    ws: Workspace,
) -> None:
    job = wrap_job(ws)
    capture.report_interval(
        ws, job, "4726-01-01", "4726-01-02", "fictional interval 0302-04-25 to 0302-04-26"
    )
    jobs.end(ws, job)

    summary = capture.wrap(ws, 1, authenticated=True)

    assert summary["settled"] == {
        "start": "4726-01-01",
        "end": "4726-01-02",
        "from": "notes",
        "wrapped": True,
    }
    assert capture.time(ws)["current_date"] == "4726-01-02"
    world_turn = summary["job"]
    assert (world_turn["playbook"], world_turn["responsibility"]) == ("world-turn", "living_world")
    assert world_turn["inputs"] == {"until": "4726-01-02", "since": "4726-01-01"}
    assert world_turn["status"] == "queued"
    jobs.start(ws, world_turn["id"], {"host": "h", "model": "m", "effort": "e"}, manual=True)
    assert capture.turn(ws, world_turn["id"]) == []  # no front yet
    assert world.cursor(ws) == "4726-01-02"
    with pytest.raises(delegation.DelegationError, match="already wrapped"):
        capture.wrap(ws, 1, authenticated=True)


def test_the_wrap_asks_for_the_interval_when_unknown_and_refuses_going_back(
    ws: Workspace,
) -> None:
    with pytest.raises(delegation.DelegationError, match="--end"):
        capture.wrap(ws, 1, authenticated=True)
    with pytest.raises(delegation.DelegationError, match="interactive"):
        capture.wrap(ws, 1, authenticated=False, end="4726-01-05")
    capture.wrap(ws, 1, authenticated=True, end="4726-01-05")
    with pytest.raises(delegation.DelegationError, match="before 4726-01-05"):
        capture.wrap(ws, 2, authenticated=True, end="4726-01-04")
    assert capture.time(ws)["current_date"] == "4726-01-05"


def clock(ws: Workspace, session: int, *dates: str) -> None:
    """The VTT clock observed on `dates` during `session` (CAL-12), as the bridge records it."""
    path = ws.root / "observations" / f"{session:06d}.jsonl"
    path.parent.mkdir(exist_ok=True)
    with path.open("a") as f:
        for n, date in enumerate(dates):
            envelope = {
                "id": f"c{n}",
                "session": session,
                "at": f"2026-10-20T20:{n:02d}:00+00:00",
                "scene": None,
                "actor": None,
                "kind": "clock",
                "visibility": "gm",
                "payload": {"date": date, "world_time": n},
            }
            f.write(json.dumps(envelope) + "\n")


def test_with_no_notes_the_observed_clock_settles_the_interval(ws: Workspace) -> None:
    clock(ws, 1, "4726-01-01", "4726-01-03", "4726-01-04")

    summary = capture.wrap(ws, 1, authenticated=True)

    assert summary["settled"] == {
        "start": "4726-01-01",
        "end": "4726-01-04",
        "from": "clock",
        "wrapped": True,
    }
    assert capture.time(ws)["current_date"] == "4726-01-04"


def test_notes_agreeing_with_the_clock_settle_it_and_disagreeing_ask_the_gm(
    ws: Workspace,
) -> None:
    job = wrap_job(ws)
    capture.report_interval(
        ws, job, "4726-01-01", "4726-01-02", "fictional interval 0302-04-25 to 0302-04-26"
    )
    jobs.end(ws, job)
    clock(ws, 1, "4726-01-01", "4726-01-05")

    with pytest.raises(
        delegation.DelegationError, match=r"4726-01-05\. Give the interval \(--start, --end\)"
    ):
        capture.wrap(ws, 1, authenticated=True)
    settled = capture.wrap(ws, 1, authenticated=True, end="4726-01-05")["settled"]

    assert (settled["end"], settled["from"]) == ("4726-01-05", "gm")


def test_notes_the_clock_confirms_settle_the_interval(ws: Workspace) -> None:
    job = wrap_job(ws)
    capture.report_interval(
        ws, job, "4726-01-01", "4726-01-02", "fictional interval 0302-04-25 to 0302-04-26"
    )
    jobs.end(ws, job)
    clock(ws, 1, "4726-01-01", "4726-01-02")

    assert capture.wrap(ws, 1, authenticated=True)["settled"]["from"] == "notes"


def test_the_gm_sets_the_current_date_from_an_interactive_terminal(ws: Workspace) -> None:
    assert capture.set_current_date(ws, "4726-01-09") == "4726-01-09"
    assert capture.time(ws)["current_date"] == "4726-01-09"
    with pytest.raises(delegation.DelegationError, match="calendar"):
        capture.set_current_date(ws, "4726-13-40")


def test_the_wrap_job_captures_and_consolidates_over_mcp(ws: Workspace) -> None:
    job = wrap_job(ws)

    async def run() -> list[Any]:
        async with Client(build_server(ws)) as client:
            base: dict[str, Any] = {"job": job, "source": str(SESSION_1), "statement": GAUGE}
            base |= {"locator": "01-dry-bell.md:7", "date": "4726-01-02", "known_by": ["party"]}
            return [
                await client.call_tool("capture_candidate", base | {"quote": "Not in it."}),
                await client.call_tool("capture_candidate", base | {"quote": GAUGE}),
                await client.call_tool("consolidate_candidates", {"job": job}),
            ]

    dropped, captured, consolidated = asyncio.run(run())

    assert dropped.structured_content["status"] == "dropped"
    assert captured.structured_content["status"] == "captured"
    assert [c["status"] for c in consolidated.structured_content["result"]] == ["applied"]


def test_the_gm_wraps_a_session_from_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = str(tmp_path / "campaign")
    main(["init", root, "--language", "en", "--calendar", "absalom"])
    monkeypatch.setattr(cli, "interactive", lambda: True)
    assert main(["session", "start", "-w", root]) == 0
    assert main(["session", "end", "-w", root, "--notes", str(SESSION_1)]) == 0
    ws = workspace.load(Path(root))
    assert jobs.read(ws, 1)["inputs"] == {"session": "1", "notes": str(SESSION_1)}
    # notes are optional; session is not
    assert main(["jobs", "-w", root, "queue", "wrap-a-session", "--input", "session=1"]) == 0
    notes = f"notes={SESSION_1}"
    assert main(["jobs", "-w", root, "queue", "wrap-a-session", "--input", notes]) == 1
    for job in (1, 2):
        jobs.start(ws, job, {"host": "h", "model": "m", "effort": "e"}, manual=True)
        jobs.end(ws, job)
    capsys.readouterr()

    assert main(["wrap", "1", "-w", root, "--end", "4726-01-03"]) == 0

    out = capsys.readouterr().out
    assert "current date 4726-01-03" in out
    assert "World-turn job 3 queued" in out
    assert capture.time(workspace.load(Path(root)))["current_date"] == "4726-01-03"


def test_the_cli_round_puts_contradictions_first(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    set_memory(ws, "propose")
    job = wrap_job(ws)
    submit(ws, job, FEE)  # held by the table
    submit(ws, job, GAUGE, classification="contradiction", reason="The gauge moved.")
    capture.consolidate(ws, job)
    jobs.end(ws, job)
    monkeypatch.setattr(cli, "interactive", lambda: True)

    assert main(["wrap", "1", "-w", str(ws.root), "--end", "4726-01-02"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert "contradiction" in lines[0] and "The gauge moved." in lines[0]
    assert "held for your approval" in lines[1]
    assert capture.time(ws)["current_date"] is None


def test_a_transcript_quote_is_checked_in_its_segment_as_spoken_with_its_speaker(
    ws: Workspace, tmp_path: Path
) -> None:
    said = 'Edda dit : « Payez-moi » et sonne "la cloche".'
    transcript = tmp_path / "session-1.jsonl"
    transcript.write_text(
        json.dumps({"speaker": "alice_42", "start": 0, "end": 1, "text": "Bonsoir."})
        + "\n"
        + json.dumps({"speaker": "gm_hugo", "start": 2, "end": 4, "text": said})
        + "\n"
    )
    job = capture.queue_wrap(ws, {"session": "1", "transcript": str(transcript)})["id"]
    jobs.start(ws, job, {"host": "h", "model": "m", "effort": "e"}, manual=True)
    at = {"source": str(transcript), "locator": f"{transcript}:2"}

    assert submit(ws, job, "« Payez-moi »", **at | {"locator": f"{transcript}:1"})["status"] == (
        "dropped"  # not in the segment the locator names
    )
    assert submit(ws, job, '\\"la cloche\\"', **at)["status"] == "dropped"  # the raw JSON line
    assert submit(ws, job, "Payez-moi", **at | {"locator": "nowhere"})["status"] == "dropped"
    assert submit(ws, job, said, **at)["status"] == "captured"
    assert submit(ws, job, 'sonne "la cloche"', **at)["status"] == "captured"
    assert {c["speaker"] for c in capture.candidates(ws, 1)} == {"gm_hugo"}
    [done, _] = capture.consolidate(ws, job)
    assert done["origin"]["speaker"] == "gm_hugo"


def test_a_transcript_states_the_interval_in_the_segment_its_locator_names(
    ws: Workspace, tmp_path: Path
) -> None:
    said = 'Nous sommes le « 1er » ; "demain" sera le 2.'
    transcript = tmp_path / "session-1.jsonl"
    transcript.write_text(
        json.dumps({"speaker": "alice_42", "start": 0, "end": 1, "text": "Bonsoir."})
        + "\n"
        + json.dumps({"speaker": "gm_hugo", "start": 2, "end": 4, "text": said})
        + "\n"
    )
    job = capture.queue_wrap(ws, {"session": "1", "transcript": str(transcript)})["id"]
    jobs.start(ws, job, {"host": "h", "model": "m", "effort": "e"}, manual=True)
    dates = ("4726-01-01", "4726-01-02")

    for locator in (None, f"{transcript}:1", "nowhere"):
        with pytest.raises(index.CanonError, match="verbatim"):
            capture.report_interval(ws, job, *dates, said, locator)
    capture.report_interval(ws, job, *dates, '"demain" sera', f"{transcript}:2")
    assert capture.time(ws)["sessions"][1]["end"] == "4726-01-02"
