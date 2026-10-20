"""The scripted fake agent host (BEN-06): CI holds no LLM credentials, so it runs the S0 harness
with this host in place of a real one. Started by the runner like any host, in the workspace, it
takes the rebuild job through the Core in-process instead of over MCP. Its model names the script:

- `scripted`: creates the bible's named entities and one it should not, the festival month;
- `leaky`: the same, with a planted canary in a player-facing description;
- `idle`: takes no action.

Usage: python -m secondchair.bench.fake <job> <model>
"""

import sys
from pathlib import Path

from secondchair.core import canon, delegation, jobs, workspace

NAMES = (
    *("Ada Fen", "Beren Pike", "Cora Sedge", "Dain Wold"),
    *("Mira Pell", "Tovan Reed", "Edda Vale", "Sella Marr", "Orin Doss", "Ilex Venn"),
    *("Lock Council", "Reed Union", "Sounding Circle"),
    *("Reedbank", "Weir", "Toll Archive", "Abandoned Kiln", "Cistern", "Rope Ferry"),
    *("Toll Squeeze", "Silt Choke", "Inspect the Chain", "Replace the Rope", "Find the Satchel"),
    *("The Dry Bell", "brass survey case", "Bellnight"),
)


def main(job: int, model: str) -> None:
    ws = workspace.load(Path.cwd())
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
