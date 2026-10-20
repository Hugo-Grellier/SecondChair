"""The scripted fake agent host (BEN-06): CI holds no LLM credentials, so it runs the S0 harness
and S2 harnesses with this host in place of a real one. Started by the runner like any host, in
the workspace, it takes the job through the Core in-process instead of over MCP. Its model names
the script:

- `scripted`: creates the bible's named entities and one it should not, the festival month, then
  records the bible's faction memberships and situations as facts;
- `leaky`: the same, with a planted canary in a player-facing description;
- `idle`: takes no action;
- `prep` (S2): prepares each encounter of the job as a scene, and one it was not asked for, then
  opens a door with no GM client connected, a failed action.

Whatever its model, on an `answer-probes` job it replies with the answers canon holds for the
factions and situations probes.

Usage: python -m secondchair.bench.fake <job> <model>
"""

import json
import sys
from contextlib import suppress
from pathlib import Path

from secondchair.core import canon, delegation, index, jobs, workspace, world
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


def record_facts(ws: Workspace, job: int) -> None:
    """The bible's faction memberships and situations, as the rebuild playbook records them."""
    [tool] = [t for t in canon.tools(ws) if t.name == "record_fact"]
    ids = {n: e["id"] for e in index.search_entities(ws) for n in e["names"]}
    bible = jobs.read(ws, job)["inputs"]["bible"]

    def record(statement: str, page: str, **fields: object) -> None:
        origin = {"kind": "source", "source": bible, "page": page}
        delegation.act(
            ws, tool, "fake", lambda: tool.fn(statement=statement, origin=origin, **fields), job
        )

    for npc, faction, page in MEMBERS:
        relation = {"type": "member_of", "subject": ids[npc], "object": ids[faction]}
        record(f"{npc} belongs to the {faction}.", page, entities=[], relation=relation)
    for situation, stage, deadline, page in SITUATIONS:
        value = {"stage": stage, "deadline": deadline}
        state = {"of": ids[situation], "key": "situation", "value": value}
        record(f"{situation} is {stage}.", page, entities=[ids[situation]], state=state)


def answer_probes(ws: Workspace) -> None:
    """Reply to the probes with what canon holds, in workspace entity ids: the factions and the
    situations; every other probe goes unanswered."""
    factions: dict[str, list[str]] = {}
    for f in index.search_facts(ws, relation="member_of"):
        factions.setdefault(f["relation"]["object"], []).append(f["relation"]["subject"])
    situations = {
        s: v
        for s, v in world.state(ws)["situations"].items()
        if v["stage"] in ("active", "available")
    }
    print(json.dumps({"factions": factions, "situations": situations}))


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
