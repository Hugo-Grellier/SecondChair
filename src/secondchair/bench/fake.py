"""The scripted fake agent host (BEN-06): CI holds no LLM credentials, so it runs the S0 harness
and S2 harnesses with this host in place of a real one. Started by the runner like any host, in
the workspace, it takes the job through the Core in-process instead of over MCP. Its model names
the script:

- `scripted`: creates the bible's named entities and one it should not, the festival month, then
  records the bible's faction memberships and situations as facts, who knows what at start and
  the mystery graph;
- `leaky`: the same, with a planted canary in a player-facing description;
- `idle`: takes no action;
- `prep` (S2): prepares each encounter of the job as a scene, and one it was not asked for, then
  opens a door with no GM client connected, a failed action.

Whatever its model, on an `answer-probes` job it replies with the answers canon holds for the
factions, situations and mystery-structure probes and the knowledge probes.

Usage: python -m secondchair.bench.fake <job> <model>
"""

import json
import sys
from contextlib import suppress
from pathlib import Path

from secondchair.core import canon, delegation, index, jobs, knowledge, mystery, workspace, world
from secondchair.core.delegation import DelegationError
from secondchair.core.workspace import Workspace

NAMES = (
    *("Ada Fen", "Beren Pike", "Cora Sedge", "Dain Wold"),
    *("Mira Pell", "Tovan Reed", "Edda Vale", "Sella Marr", "Orin Doss", "Ilex Venn"),
    *("Lock Council", "Reed Union", "Sounding Circle"),
    *("Reedbank", "Weir", "Toll Archive", "Abandoned Kiln", "Cistern", "Rope Ferry"),
    *("Toll Squeeze", "Silt Choke", "Inspect the Chain", "Replace the Rope", "Find the Satchel"),
    *("The Dry Bell", "brass survey case", "Bellnight"),
)


def prep(ws: Workspace, job: int) -> None:
    from secondchair_foundry import tools  # the bench, not the Core, reaches the connector

    found = {t.name: t for t in tools.tools(ws)}
    scene, door = found["prepare_scene"], found["set_door"]
    encounters = jobs.read(ws, job)["inputs"]["encounters"].split(";")
    for key in [e.split(":")[0].strip() for e in encounters] + ["bonus-ambush"]:
        delegation.act(
            ws, scene, "fake", lambda k=key: scene.fn(key=k, scene={"name": k}, items=[]), job
        )
    with suppress(DelegationError):
        delegation.act(ws, door, "fake", lambda: door.fn(door="Scene.x.Wall.y", state="open"), job)


MEMBERS = (  # npc, faction, bible paragraph
    ("Mira Pell", "Lock Council", "B04"),
    ("Tovan Reed", "Reed Union", "B05"),
    ("Edda Vale", "Sounding Circle", "B06"),
    ("Ilex Venn", "Sounding Circle", "B11"),
)
SITUATIONS = (  # situation, stage, deadline, bible paragraph
    ("Inspect the Chain", "active", "0302-05-01", "B07"),
    ("Replace the Rope", "available", "0302-06-03", "B08"),
    ("Find the Satchel", "available", None, "B09"),
)


START = "0302-04-25"  # the bible's starting date
RESIDENTS = ("Mira Pell", "Tovan Reed", "Edda Vale", "Sella Marr", "Orin Doss")  # of Reedbank
# The common-knowledge probe's terms (its answer shape), by the statement the fake records.
TERMS = {
    "The warning bell rings on dry nights.": "bell-ringing",
    "The Lock Council controls the gate.": "council-controls-gate",
    "A cracked pressure relay at the Cistern rings the bell.": "bell-cause",
}
CLUES = (  # clue, node, place, evidence, conclusion, as the bible's table lists them
    ("clue-1", "node-weir", "Weir", "The dry gauge stays at zero.", "conclusion-relay"),
    ("clue-2", "node-weir", "Weir", "A pulse runs down the Cistern conduit.", "conclusion-relay"),
    ("clue-3", "node-archive", "Toll Archive", "The repair account is empty.", "conclusion-ledger"),
    ("clue-4", "node-archive", "Toll Archive", "Mira signed the transfer.", "conclusion-ledger"),
    ("clue-5", "node-kiln", "Abandoned Kiln", "A spare relay bears it.", "conclusion-ledger"),
    (
        "clue-6",
        "node-kiln",
        "Abandoned Kiln",
        "A test log ties bells to a crack.",
        "conclusion-relay",
    ),
    ("clue-7", "node-cistern", "Cistern", "The relay's crack pulses.", "conclusion-relay"),
)


def record_facts(ws: Workspace, job: int) -> None:
    """The bible's faction memberships, situations, who knows what at start and the mystery
    graph, as the rebuild playbook records them."""
    tools = {t.name: t for t in [*canon.tools(ws), *knowledge.tools(ws), *mystery.tools(ws)]}
    ids = {n: e["id"] for e in index.search_entities(ws) for n in e["names"]}
    bible = jobs.read(ws, job)["inputs"]["bible"]

    def act(tool: str, **args: object) -> str:
        """The id of what the action wrote."""
        found = tools[tool]
        done = delegation.act(ws, found, "fake", lambda: found.fn(**args), job)
        return Path(delegation.read_entry(ws, done["entry"])["target"]).stem

    def record(statement: str, page: str, **fields: object) -> str:
        origin = {"kind": "source", "source": bible, "page": page}
        return act("record_fact", statement=statement, origin=origin, **{"entities": [], **fields})

    def learn(knower: str, fact: str, page: str, mode: str = "knows") -> None:
        origin = {"kind": "source", "source": bible, "page": page}
        act("record_knowledge", knower=ids[knower], fact=fact, mode=mode, date=START, origin=origin)

    for npc, faction, page in MEMBERS:
        relation = {"type": "member_of", "subject": ids[npc], "object": ids[faction]}
        member = record(f"{npc} belongs to the {faction}.", page, relation=relation)
        if page == "B11":  # the secret membership, not the faction's own knowledge
            learn("Ilex Venn", member, page)
            learn("Edda Vale", member, page)
    for situation, stage, deadline, page in SITUATIONS:
        value = {"stage": stage, "deadline": deadline}
        state = {"of": ids[situation], "key": "situation", "value": value}
        record(f"{situation} is {stage}.", page, entities=[ids[situation]], state=state)
    for npc in RESIDENTS:
        relation = {"type": "lives_in", "subject": ids[npc], "object": ids["Reedbank"]}
        record(f"{npc} lives in Reedbank.", "B01", relation=relation)
    ringing, gate, cause = TERMS
    for statement in (ringing, gate):
        learn("Reedbank", record(statement, "B02"), "B02")  # common knowledge
    name = record("The Cistern maintainer's only name is Ilex Venn.", "B10")
    learn("Ilex Venn", name, "B10")
    learn("Edda Vale", name, "B10")
    relay = record(cause, "B12")
    learn("Ilex Venn", relay, "B12")
    ledger = record("Mira diverted the relay repair fund into an unofficial toll reserve.", "B13")
    learn("Mira Pell", ledger, "B13")
    belief = record("The Circle rings false warnings on purpose.", "B14", never_true=True)
    learn("Tovan Reed", belief, "B14", mode="believes")
    act(
        "record_mystery",
        mystery=ids["The Dry Bell"],
        conclusions=[
            {"id": "conclusion-relay", "fact": relay},
            {"id": "conclusion-ledger", "fact": ledger},
        ],
        nodes=[{"id": n, "entity": ids[p]} for n, p in {c[1]: c[2] for c in CLUES}.items()],
        clues=[
            {"id": c, "fact": record(evidence, "secret-mystery"), "on": node, "points_to": [to]}
            for c, node, _, evidence, to in CLUES
        ],
    )


def answer_probes(ws: Workspace) -> None:
    """Reply to the probes with what canon holds, in workspace entity ids: the factions, the
    situations, the mystery's structure and who knows what at start; every other probe goes
    unanswered."""
    ids = {n: e["id"] for e in index.search_entities(ws) for n in e["names"]}
    facts = index.search_facts(ws)
    factions: dict[str, list[str]] = {}
    for f in index.search_facts(ws, relation="member_of"):
        factions.setdefault(f["relation"]["object"], []).append(f["relation"]["subject"])
    situations = {
        s: v
        for s, v in world.state(ws)["situations"].items()
        if v["stage"] in ("active", "available")
    }
    answers: dict = {"factions": factions, "situations": situations}
    [check] = [t for t in mystery.tools(ws) if t.name == "check_mystery"]
    with suppress(KeyError, index.CanonError):  # no mystery recorded
        graph = check.fn(mystery=ids["The Dry Bell"])
        answers["mystery-structure"] = {
            k: [x["id"] for x in graph[k]] for k in ("conclusions", "nodes", "clues")
        }
    page = {f["origin"].get("page"): f["id"] for f in facts}
    if {"B10", "B12", "B13"} <= page.keys():

        def held(name: str) -> set[str]:
            return set(knowledge.known(ws, ids[name], START))

        edda, circle = held("Edda Vale"), held("Sounding Circle")
        both = held("Sella Marr") & held("Orin Doss")
        terms = {f["id"]: TERMS[f["statement"]] for f in facts if f["statement"] in TERMS}
        beliefs = {f["id"] for f in facts if f["never_true"]}
        answers |= {
            "edda-knowledge": {
                "name": page["B10"] in edda,
                "cause": page["B12"] in edda,
                "diversion": page["B13"] in edda,
            },
            "circle-knowledge": {"name": page["B10"] in circle, "cause": page["B12"] in circle},
            "common-knowledge": {
                "both_know": [t for f, t in terms.items() if f in both],
                "both_do_not_know": [t for f, t in terms.items() if f not in both],
            },
            "belief": {
                "ever_true": not beliefs,
                "believers": [
                    k["knower"]
                    for k in index.search_knowledge(ws, list(ids.values()))
                    if k["fact"] in beliefs and k["mode"] == "believes"
                ],
            },
        }
    print(json.dumps(answers))


def main(job: int, model: str) -> None:
    ws = workspace.load(Path.cwd())
    if jobs.read(ws, job)["playbook"] == "answer-probes":
        answer_probes(ws)
        jobs.end(ws, job)
        return
    if model == "prep":
        prep(ws, job)
        jobs.end(ws, job)
        return
    [tool] = [t for t in canon.tools(ws) if t.name == "create_entity"]
    for name in NAMES if model != "idle" else ():
        leaky = model == "leaky" and name == "Ilex Venn"
        description = "Keeps the Cistern. CANARY-identity-1" if leaky else ""
        delegation.act(
            ws, tool, "fake", lambda n=name, d=description: tool.fn(names=[n], description=d), job
        )
    if model != "idle":
        record_facts(ws, job)
    jobs.end(ws, job)


if __name__ == "__main__":
    main(int(sys.argv[1]), sys.argv[2])
