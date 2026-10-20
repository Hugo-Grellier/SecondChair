"""S0 scores its fact and knowledge probes against the frozen gold set, reports continuity errors
(MET-01: from the workspace and its action log only; MET-03: no LLM judge) and fails on any leak
(the leak invariant)."""

from pathlib import Path

import pytest
import yaml

from secondchair.bench import s0
from secondchair.core import (
    canon,
    capture,
    delegation,
    index,
    jobs,
    knowledge,
    mystery,
    workspace,
    world,
)
from secondchair.core.workspace import Workspace

SAMPLE = Path(__file__).parents[1] / "sample-campaign"
GOLD = yaml.safe_load((SAMPLE / "gold.yaml").read_text())
START = GOLD["start"]["date"]
NAMES = (
    "Mira Pell",
    "Tovan Reed",
    "Edda Vale",
    "Sella Marr",
    "Orin Doss",
    "Ilex Venn",
    "Lock Council",
    "Reed Union",
    "Sounding Circle",
    "Reedbank",
    "Cistern",
)


def bible(page: str) -> dict[str, str]:
    return {"kind": "source", "source": "sample-campaign/bible.md", "page": page}


def act(ws: Workspace, tool: str, **args: object) -> None:
    [found] = [t for t in core_tools(ws) if t.name == tool]
    delegation.act(ws, found, "s0-rebuild", lambda: found.fn(**args))


def record(ws: Workspace, statement: str, page: str, **fields: object) -> str:
    act(ws, "record_fact", statement=statement, origin=bible(page), **{"entities": [], **fields})
    [found] = [f for f in index.search_facts(ws, text=statement) if f["statement"] == statement]
    return found["id"]


def learn(ws: Workspace, knower: str, fact: str, mode: str = "knows") -> None:
    """Who knows it at start, as the fact's own bible paragraph states."""
    [cited] = [f for f in index.search_facts(ws) if f["id"] == fact]
    origin = bible(cited["origin"]["page"])
    act(ws, "record_knowledge", knower=knower, fact=fact, mode=mode, date=START, origin=origin)


def rebuild(tmp_path: Path) -> tuple[Workspace, dict[str, str], dict[str, str]]:
    """What the rebuild playbook writes from the bible, through the Core: the faction and
    residence paragraphs, the secrets and who knows them. Returns the workspace, entity ids by
    name, and fact ids by the evaluator's vocabulary."""
    config = yaml.safe_load((SAMPLE / "campaign.yaml").read_text())
    ws = workspace.init(tmp_path / "s0", config["campaign_language"], config["calendar"])
    for name in NAMES:
        act(ws, "create_entity", names=[name])
    ids = {e["names"][0]: e["id"] for e in index.search_entities(ws)}
    for npc, faction, page in (
        ("Mira Pell", "Lock Council", "B04"),
        ("Tovan Reed", "Reed Union", "B05"),
        ("Edda Vale", "Sounding Circle", "B06"),
    ):
        record(
            ws,
            f"{npc} belongs to the {faction}.",
            page,
            relation={"type": "member_of", "subject": ids[npc], "object": ids[faction]},
        )
    for npc in ("Mira Pell", "Tovan Reed", "Edda Vale", "Sella Marr", "Orin Doss"):
        record(
            ws,
            f"{npc} lives in Reedbank.",
            "B01",
            relation={"type": "lives_in", "subject": ids[npc], "object": ids["Reedbank"]},
        )
    hidden, edda = ids["Ilex Venn"], ids["Edda Vale"]
    facts = {
        "bell-ringing": record(ws, "The warning bell rings on dry nights.", "B02"),
        "council-controls-gate": record(ws, "The Lock Council controls the gate.", "B02"),
        "secret-name": record(ws, "The Cistern maintainer's only name is Ilex Venn.", "B10"),
        "secret-member": record(
            ws,
            "Ilex Venn belongs to the Sounding Circle.",
            "B11",
            relation={"type": "member_of", "subject": hidden, "object": ids["Sounding Circle"]},
        ),
        "bell-cause": record(ws, "A cracked pressure relay rings the bell.", "B12"),
        "fund-diversion": record(ws, "Mira diverted the relay repair fund.", "B13"),
        "false-warnings": record(
            ws, "The Circle rings false warnings on purpose.", "B14", never_true=True
        ),
    }
    for f in ("bell-ringing", "council-controls-gate"):
        learn(ws, ids["Reedbank"], facts[f])  # common knowledge
    for knower in (hidden, edda):
        learn(ws, knower, facts["secret-name"])
        learn(ws, knower, facts["secret-member"])
    learn(ws, hidden, facts["bell-cause"])
    learn(ws, ids["Mira Pell"], facts["fund-diversion"])
    learn(ws, ids["Tovan Reed"], facts["false-warnings"], mode="believes")
    ids["The Dry Bell"] = rebuild_mystery(ws)
    return ws, ids, facts


MYSTERY = "sample-campaign/bible.md#secret-mystery"
CONCLUSIONS = {
    "conclusion-relay": "A cracked pressure relay at the Cistern causes the dry-night bell.",
    "conclusion-ledger": "Mira diverted the relay repair fund into an unofficial toll reserve.",
}
CLUES = {  # id: (node, place, evidence, conclusion), as the bible's table lists them
    "clue-1": ("node-weir", "Weir", "The dry gauge stays at zero.", "conclusion-relay"),
    "clue-2": ("node-weir", "Weir", "A pressure pulse runs down the conduit.", "conclusion-relay"),
    "clue-3": ("node-archive", "Toll Archive", "The repair account is empty.", "conclusion-ledger"),
    "clue-4": ("node-archive", "Toll Archive", "Mira signed the transfer.", "conclusion-ledger"),
    "clue-5": (
        "node-kiln",
        "Abandoned Kiln",
        "A spare relay bears the account number.",
        "conclusion-ledger",
    ),
    "clue-6": (
        "node-kiln",
        "Abandoned Kiln",
        "A test log ties bells to a crack.",
        "conclusion-relay",
    ),
    "clue-7": (
        "node-cistern",
        "Cistern",
        "The relay's crack pulses with the bell.",
        "conclusion-relay",
    ),
}


def rebuild_mystery(ws: Workspace) -> str:
    """What the rebuild playbook writes for the secret-mystery section, through the Core."""
    origin = {"kind": "source", "source": "sample-campaign/bible.md", "page": "secret-mystery"}
    for name in ("The Dry Bell", "Weir", "Toll Archive", "Abandoned Kiln"):  # Cistern exists
        act(ws, "create_entity", names=[name])
    ids = {e["names"][0]: e["id"] for e in index.search_entities(ws)}

    def fact(statement: str) -> str:
        act(ws, "record_fact", statement=statement, entities=[], origin=origin)
        [found] = index.search_facts(ws, text=statement)
        return found["id"]

    nodes = {node: ids[place] for node, place, _, _ in CLUES.values()}
    act(
        ws,
        "record_mystery",
        mystery=ids["The Dry Bell"],
        conclusions=[{"id": c, "fact": fact(s)} for c, s in CONCLUSIONS.items()],
        nodes=[{"id": n, "entity": e} for n, e in nodes.items()],
        clues=[
            {"id": c, "fact": fact(evidence), "on": node, "points_to": [to]}
            for c, (node, _, evidence, to) in CLUES.items()
        ],
    )
    return ids["The Dry Bell"]


def structure_answer(ws: Workspace, mystery: str) -> dict[str, list[str]]:
    """The structured answer an agent reads from check_mystery."""
    [check] = [t for t in core_tools(ws) if t.name == "check_mystery"]
    report = check.fn(mystery=mystery)
    return {k: [x["id"] for x in report[k]] for k in ("conclusions", "nodes", "clues")}


def core_tools(ws: Workspace) -> list:
    return [*canon.tools(ws), *knowledge.tools(ws), *mystery.tools(ws)]


def answers(ws: Workspace, ids: dict[str, str], facts: dict[str, str]) -> dict:
    """Structured answers read from canon, as an agent answers with search_facts and what_knows."""
    factions: dict[str, list[str]] = {}
    for f in index.search_facts(ws, relation="member_of"):
        factions.setdefault(f["relation"]["object"], []).append(f["relation"]["subject"])
    edda = knowledge.known(ws, ids["Edda Vale"], START)
    circle = knowledge.known(ws, ids["Sounding Circle"], START)
    both = (
        knowledge.known(ws, ids["Sella Marr"], START).keys()
        & knowledge.known(ws, ids["Orin Doss"], START).keys()
    )
    vocabulary = {fact: word for word, fact in facts.items()}
    belief = facts["false-warnings"]
    [lie] = [f for f in index.search_facts(ws) if f["id"] == belief]
    return {
        "factions": factions,
        "mystery-structure": structure_answer(ws, ids["The Dry Bell"]),
        "hidden-name": {"secret_name": "Ilex Venn", "public_name": None},
        "mystery-answer": {
            "cause": "cracked-pressure-relay",
            "money": "unofficial-toll-reserve",
            "sabotage": False,
        },
        "planned-treasure": {
            "treasure-fee": ids["Edda Vale"],
            "treasure-case": "unclaimed",
            "party_owns": [],
        },
        "situations": GOLD["probes"][-1]["expected"],
        "edda-knowledge": {
            "name": facts["secret-name"] in edda,
            "cause": facts["bell-cause"] in edda,
            "diversion": facts["fund-diversion"] in edda,
        },
        "circle-knowledge": {
            "name": facts["secret-name"] in circle,
            "cause": facts["bell-cause"] in circle,
        },
        "common-knowledge": {
            "both_know": [vocabulary[f] for f in both],
            "both_do_not_know": [w for w in ("bell-cause",) if facts[w] not in both],
        },
        "belief": {
            "ever_true": not lie["never_true"],
            "believers": [
                i
                for i in ids.values()
                if knowledge.known(ws, i).get(belief, {}).get("mode") == "believes"
            ],
        },
    }


def test_probes_pass_and_nothing_leaks_when_canon_answers_them(tmp_path: Path) -> None:
    ws, ids, facts = rebuild(tmp_path)

    report = s0.score_probes(ws, GOLD, answers(ws, ids, facts))

    assert report["probes"] == dict.fromkeys(s0.PROBES, True)
    assert report["continuity_errors"]["total"] == 0
    assert report["leaks"] == []
    assert report["passed"]


def test_a_knower_inherits_but_a_faction_never_inherits_from_its_members(tmp_path: Path) -> None:
    ws, ids, facts = rebuild(tmp_path)
    sella = knowledge.known(ws, ids["Sella Marr"], START)
    assert {f: h["via"] for f, h in sella.items()} == {
        facts["bell-ringing"]: ids["Reedbank"],
        facts["council-controls-gate"]: ids["Reedbank"],
    }
    assert knowledge.known(ws, ids["Sounding Circle"]) == {}


def test_any_leak_fails_s0(tmp_path: Path) -> None:
    ws, ids, facts = rebuild(tmp_path)
    marked = record(ws, "CANARY-mystery-1 The relay hides under the Cistern.", "B12")
    learn(ws, "party", marked)
    learn(ws, ids["Tovan Reed"], facts["secret-name"])
    learn(ws, "party", facts["fund-diversion"])

    report = s0.score_probes(ws, GOLD, answers(ws, ids, facts))

    assert not report["passed"]
    assert sorted(report["leaks"]) == sorted(
        [
            f"CANARY-mystery-1 reaches party ({marked})",
            f"B12 known by party at start ({marked})",
            f"'Ilex Venn' reaches npc-tovan ({facts['secret-name']})",
            f"B13 known by party at start ({facts['fund-diversion']})",
        ]
    )


def test_mystery_probes_score_the_graph_recorded_in_canon(tmp_path: Path) -> None:
    ws, ids, _ = rebuild(tmp_path)
    bell = ids["The Dry Bell"]
    structure = structure_answer(ws, bell)
    # Each conclusion has three clues or more, on two nodes or more; the bible marks no entry.
    [check] = [t for t in core_tools(ws) if t.name == "check_mystery"]
    report = check.fn(mystery=bell)
    assert report["problems"] == []
    assert [w["code"] for w in report["warnings"]] == ["mystery-entry"]

    assert s0.score_probes(ws, GOLD, {"mystery-structure": structure})["probes"][
        "mystery-structure"
    ]
    short = {**structure, "clues": structure["clues"][:-1]}
    assert not s0.score_probes(ws, GOLD, {"mystery-structure": short})["probes"][
        "mystery-structure"
    ]


def test_failed_probes_and_refused_contradictions_are_continuity_errors(tmp_path: Path) -> None:
    ws, ids, facts = rebuild(tmp_path)
    given = answers(ws, ids, facts)
    wrong = {"factions": {**given["factions"], ids["Lock Council"]: [ids["Edda Vale"]]}}
    seen = {"kind": "observation", "quote": "Edda paid 12 silver.", "locator": "S1-02"}
    act(ws, "record_fact", statement="Edda paid 12 silver.", entities=[], origin=seen)
    [fee] = index.search_facts(ws, text="silver")
    with pytest.raises(delegation.DelegationError, match="played"):
        act(
            ws,
            "correct_fact",
            fact=fee["id"],
            statement="Edda paid 20 silver.",
            entities=[],
            origin={"kind": "job", "job": "s0-rebuild"},
        )

    report = s0.score_probes(ws, GOLD, wrong)

    assert report["probes"]["factions"] is False
    assert report["probes"]["hidden-name"] is False  # no answer is a failure
    errors = report["continuity_errors"]
    assert errors["refused_contradictions"] == 1
    assert errors["failed_probes"] == len(s0.PROBES)
    assert errors["total"] == 1 + len(s0.PROBES)
    assert report["passed"]  # continuity is reported, not gated, until floors exist (MET-05a)


def test_the_s0_report_measures_language_drift_without_blocking_it(tmp_path: Path) -> None:
    ws, _, _ = rebuild(tmp_path)
    clean = s0.score_probes(ws, GOLD, {})["language_drift"]
    assert clean == {"share": 0.0, "drifted": []}

    french = "Mira Pell garde la caisse des réparations dans une réserve secrète du péage."
    fact = record(ws, french, "B04")  # applied, not blocked

    report = s0.score_probes(ws, GOLD, {})
    drift = report["language_drift"]
    assert drift["drifted"] == [{"id": fact, "language": "fr"}]
    assert 0 < drift["share"] < 1
    assert report["passed"]  # tracked, never gated
    assert drift == s0.score_probes(ws, GOLD, {})["language_drift"]  # deterministic


# Living-world probes (BEN-07): each world_turn_probes case from a fresh rebuild.

WORLD = (
    "Toll Squeeze",
    "Silt Choke",
    "Inspect the Chain",
    "Replace the Rope",
    "Find the Satchel",
)


def state(ws: Workspace, of: str, key: str, value: object, page: str) -> str:
    return record(
        ws,
        f"{of} {key}: {value}",
        page,
        entities=[of],
        state={"of": of, "key": key, "value": value},
    )


def rebuild_world(tmp_path: Path, with_b17: bool = True) -> tuple[Workspace, dict[str, str]]:
    """The bible's living-world paragraphs (B07-B09, B15-B17), written through the Core."""
    ws, ids, _ = rebuild(tmp_path)
    for name in WORLD:
        act(ws, "create_entity", names=[name])
    ids = {e["names"][0]: e["id"] for e in index.search_entities(ws)}
    for front, carrier, who, unless, step, page in (
        ("Toll Squeeze", "Lock Council", "Mira Pell", None, "draft-toll-increase", "B15"),
        (
            "Silt Choke",
            "Reed Union",
            "Tovan Reed",
            "the bypass is open",
            "prepare-dredging-petition",
            "B16",
        ),
    ):
        rule = {"carrier": ids[carrier], "participants": [ids[who]], "capacity": 4}
        rule |= {"every": "1w", "anchor": START, "unless": unless}
        state(ws, ids[front], "front", rule, page)
        state(ws, ids[front], "clock", 0, page)
        state(ws, ids[front], "agenda", {"id": step, "when": {"clock_gte": 2}}, page)
    for name, stage, deadline, who, page in (
        ("Inspect the Chain", "active", "0302-05-01", [], "B07"),
        ("Replace the Rope", "available", "0302-06-03", [ids["Orin Doss"]], "B08"),
        ("Find the Satchel", "available", None, [], "B09"),
    ):
        value = {"stage": stage, "deadline": deadline, "participants": who}
        state(ws, ids[name], "situation", value, page)
    if with_b17:
        closed = record(ws, "The bypass is closed.", "B17", valid_from=START)
        for knower in ("party", ids["Tovan Reed"], ids["Reed Union"]):
            learn(ws, knower, closed)
    return ws, ids


@pytest.mark.parametrize("case", ["pristine-one-week", "pristine-two-weeks", "unresolved-unless"])
def test_s0_scores_its_living_world_clock_probes(tmp_path: Path, case: str) -> None:
    [spec] = [c for c in GOLD["world_turn_probes"] if c["id"] == case]
    ws, _ = rebuild_world(tmp_path, with_b17=spec["initial"] != "bible-with-B17-omitted")
    delegation.change_moment(ws, spec["moment"])
    bypass = [f["id"] for f in index.search_facts(ws, text="bypass is closed")]

    world.world_turn(ws, spec["now"], since=spec["cursor"])
    for r in world.occurrences(ws):  # the settle-an-unless jobs, as the assumptions say
        if r["status"] == "queued" and r["class"] == "derived":
            jobs.start(ws, r["job"], {"host": "h", "model": "m", "effort": "e"}, manual=True)
            world.settle_unless(ws, r["key"], False if bypass else None, bypass, r["job"])

    report = s0.score_world_turn(ws, GOLD, case)
    assert report["probes"]["clocks"]
    assert report["probes"] == dict.fromkeys(report["probes"], True)
    assert report["unscored"] == []


def test_a_wrong_clock_fails_its_living_world_probe(tmp_path: Path) -> None:
    ws, _ = rebuild_world(tmp_path)
    world.world_turn(ws, "0302-05-01", since=START)  # the Silt Choke tick is never settled

    report = s0.score_world_turn(ws, GOLD, "pristine-one-week")

    assert report["probes"]["clocks"] is False
    assert report["probes"]["unless_evidence"] is False


# What a wrap agent captures from each note's numbered lines: (line, statement, knowers by
# name). The quote is the line's text, verbatim.
NOTES = {
    "01-dry-bell.md": [
        ("S1-01", "The dry gauge at the Weir stayed at zero while the bell rang.", ["party"]),
        ("S1-02", "Edda Vale paid the party 12 silver coins.", ["party", "Edda Vale"]),
        ("S1-03", "Edda Vale learned that the gauge stayed at zero.", ["Edda Vale"]),
        ("S1-04", "Orin Doss offered free crossings for a new rope.", ["party", "Orin Doss"]),
    ],
    "02-bypass.md": [
        ("S2-01", "The party opened the bypass at the Weir.", ["party"]),
        ("S2-02", "Tovan Reed told the Reed Union of the bypass.", ["Tovan Reed", "Reed Union"]),
        ("S2-03", "Mira Pell signed the transfer of the relay fund.", ["party"]),
        ("S2-04", "The party keeps the transfer from Edda Vale.", ["party"]),
    ],
}
CHATTER = "perhaps the cook is secretly behind everything?"


def wrap_notes(
    ws: Workspace, ids: dict[str, str], notes: dict = NOTES, chatter: bool = False
) -> None:
    """Both notes captured in order, one wrap job each, as the wrap playbook does."""
    for session, (name, lines) in enumerate(notes.items(), start=1):
        path = SAMPLE / "sessions" / name
        job = jobs.queue(
            ws,
            playbook="wrap-a-session",
            inputs={"session": str(session), "notes": str(path)},
            expected_output="",
            responsibility="memory",
            tier="standard",
        )["id"]
        jobs.start(ws, job, {"host": "h", "model": "m", "effort": "e"}, manual=True)
        date = "0302-04-26" if session == 1 else "0302-05-01"
        text = path.read_text()
        submitted = [
            (line, text.split(f"**{line}**: ")[1].split("\n")[0], statement, knowers)
            for line, statement, knowers in lines
        ]
        if chatter and session == 1:
            submitted.append(("chatter", CHATTER, "The cook is behind everything.", []))
        for line, quote, statement, knowers in submitted:
            result = capture.capture(
                ws,
                job,
                source=str(path),
                locator=f"{name}#{line}",
                quote=quote,
                statement=statement,
                date=date,
                known_by=[ids.get(k, k) for k in knowers],
            )
            assert result["status"] == "captured"
        capture.consolidate(ws, job)


def test_s0_reports_capture_recall_and_precision_against_the_gold_set(tmp_path: Path) -> None:
    ws, ids, _ = rebuild(tmp_path)
    assert s0.capture_coverage(ws, GOLD)["recall"] == 0.0

    wrap_notes(ws, ids)

    report = s0.score_probes(ws, GOLD, {})["capture_coverage"]
    assert (report["recall"], report["precision"], report["missed"]) == (1.0, 1.0, [])
    assert all(c["status"] == "applied" for c in capture.candidates(ws))


def test_chatter_and_wrong_knowers_lower_capture_coverage(tmp_path: Path) -> None:
    ws, ids, _ = rebuild(tmp_path)
    gauge, *rest = NOTES["01-dry-bell.md"]
    wrong = {**NOTES, "01-dry-bell.md": [(*gauge[:2], ["party", "Edda Vale"]), *rest]}

    wrap_notes(ws, ids, wrong, chatter=True)

    report = s0.capture_coverage(ws, GOLD)
    assert report["missed"] == ["capture-gauge"]
    assert (report["recall"], report["precision"]) == (7 / 8, 7 / 9)


# The narrative-direction invariant and the drift ratio (10-success-bench.md, DEL-08, LW-08)

CONFIG = {"host": "h", "model": "m", "effort": "e"}


def narrative_job(ws: Workspace, ids: dict[str, str]) -> int:
    """The started job for the engaged Inspect the Chain deadline, new narrative."""
    world.world_turn(ws, "0302-05-01", since=START)
    [r] = [r for r in world.occurrences(ws) if r["class"] == "narrative"]
    jobs.start(ws, r["job"], CONFIG, manual=True)
    return r["job"]


def job_act(ws: Workspace, tool: str, job: int, **args: object) -> delegation.ActionResult:
    [found] = [t for t in core_tools(ws) if t.name == tool]
    return delegation.act(ws, found, "s0-agent", lambda: found.fn(**args), job=job)


def test_a_narrative_direction_action_held_at_propose_keeps_s0_passing(tmp_path: Path) -> None:
    ws, ids = rebuild_world(tmp_path)
    job = narrative_job(ws, ids)
    chain = ids["Inspect the Chain"]
    origin = {"kind": "job", "job": str(job)}
    held = job_act(
        ws, "record_fact", job, statement="The chain snaps.", entities=[chain], origin=origin
    )

    delegation.approve(ws, held["entry"], "cli", authenticated=True)  # the GM decides

    report = s0.score_probes(ws, GOLD, {})
    assert report["narrative_direction"] == []
    assert report["passed"]


def test_a_narrative_direction_action_that_passes_fails_s0(tmp_path: Path) -> None:
    ws, ids = rebuild_world(tmp_path)
    table = yaml.safe_load((ws.root / "delegation.yaml").read_text())
    table["prep"]["narrative_direction"]["level"] = "autonomous"
    (ws.root / "delegation.yaml").write_text(yaml.safe_dump(table))
    job = narrative_job(ws, ids)
    origin = {"kind": "job", "job": str(job)}

    with pytest.MonkeyPatch.context() as mp:  # a Core that lost its cap
        mp.setattr(delegation, "CAPS", {})
        passed = job_act(
            ws,
            "record_fact",
            job,
            statement="The chain snaps.",
            entities=[ids["Inspect the Chain"]],
            origin=origin,
        )

    report = s0.score_probes(ws, GOLD, {})
    assert passed["status"] == "applied"
    assert report["narrative_direction"] == [
        f"entry {passed['entry']}: narrative direction at act-then-review, applied without the "
        "GM's approval"
    ]
    assert not report["passed"]


@pytest.mark.parametrize("living_world", ["act-then-review", "propose"])
def test_s0_reports_the_drift_ratio_without_gating_it(tmp_path: Path, living_world: str) -> None:
    ws, ids = rebuild_world(tmp_path)
    table = yaml.safe_load((ws.root / "delegation.yaml").read_text())
    table["prep"]["living_world"]["level"] = living_world
    (ws.root / "delegation.yaml").write_text(yaml.safe_dump(table))
    assert s0.score_probes(ws, GOLD, {})["drift_ratio"] == {"agent": 0, "gm": 0, "ratio": None}
    world.world_turn(ws, "0302-05-01", since=START)
    [silt] = [r for r in world.occurrences(ws) if r["class"] == "derived"]
    jobs.start(ws, silt["job"], CONFIG, manual=True)
    bypass = [f["id"] for f in index.search_facts(ws, text="bypass is closed")]
    world.settle_unless(ws, silt["key"], False, bypass, silt["job"])  # an agent decision
    if living_world == "propose":  # the GM accepting it does not make it the GM's
        for r in world.occurrences(ws):
            if r["status"] == "queued" and r["class"] != "narrative":
                world.decide(ws, r["key"], "accept", authenticated=True)
    world.set_active(ws, ids["Toll Squeeze"], False, "0302-05-01", authenticated=True)  # the GM's

    report = s0.score_probes(ws, GOLD, {})
    assert report["drift_ratio"] == {"agent": 1, "gm": 1, "ratio": 1.0}
    assert report["passed"]
