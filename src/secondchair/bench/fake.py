"""The scripted fake agent host (BEN-06): CI holds no LLM credentials, so it runs the S0 harness
and S2 harnesses with this host in place of a real one. Started by the runner like any host, in
the workspace, it takes the job through the Core in-process instead of over MCP. Its model names
the script:

- `scripted`: creates the bible's named entities and one it should not, the festival month;
- `leaky`: the same, with a planted canary in a player-facing description;
- `idle`: takes no action;
- `prep` (S2): prepares each encounter of the job as a scene, and one it was not asked for, then
  opens a door with no GM client connected, a failed action.

Usage: python -m secondchair.bench.fake <job> <model>
"""

import sys
from contextlib import suppress
from pathlib import Path

from secondchair.core import canon, delegation, jobs, workspace
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


def main(job: int, model: str) -> None:
    ws = workspace.load(Path.cwd())
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
    jobs.end(ws, job)


if __name__ == "__main__":
    main(int(sys.argv[1]), sys.argv[2])
