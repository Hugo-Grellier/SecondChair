"""The mystery graph (BVE-02), transplanted from v3 (pf2e-open-campaign, bible/mysteries.py)
onto facts. A mystery is an entity; its graph lives in `canon/mysteries/<entity id>.md`:
conclusions and clues are facts, nodes are entities (or a proactive fact, such as a front's
agenda step, that brings the party in while it holds). The graph holds no state of its own:

- a clue is *lost* when its fact no longer holds (closed by an event, or retconned);
- a clue is *found*, and a conclusion *solved*, when the party knows its fact;
- a proactive node is an entry while its fact holds.

`check` is the pure algorithm: the graph's problems (references that do not resolve), and the
v3 warnings (three-clue rule, inverted rule, reachability from the entries, single point of
failure), optionally simulating the loss of some clues.
"""

from collections import deque
from collections.abc import Collection, Sequence
from typing import Any

from secondchair.core import index
from secondchair.core.index import CanonError
from secondchair.core.tools import Change, Tool
from secondchair.core.workspace import Workspace

MYSTERIES_DIR = "canon/mysteries"


def _items(doc: dict, key: str, problems: list[str]) -> list[dict]:
    value = doc.get(key) or []
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        problems.append(f"{key} must be a list of mappings")
        return []
    return value


def check(
    doc: dict,
    facts: dict[str, dict],
    entities: set[str],
    known: Collection[str] = frozenset(),
    lose: Sequence[str] = (),
) -> dict[str, Any]:
    """The mystery's report. `facts` are canon facts by id, retconned ones included (with their
    `status` and `valid_to`); `known` the fact ids the party knows; `lose` clue ids whose loss
    is simulated (nothing is written). Problems are reported, never raised; a bad `lose` is."""
    problems: list[str] = []
    if not isinstance(doc, dict):
        doc, problems = {}, ["a mystery must be a mapping"]
    seen: set[str] = set()

    def local(item: dict, what: str) -> str | None:
        lid = item.get("id")
        if not (isinstance(lid, str) and lid):
            problems.append(f"{what}: an id is required")
            return None
        if lid in seen:
            problems.append(f"{lid}: id used twice in this mystery")
        seen.add(lid)
        return lid

    def holds(fact_id: str) -> bool:
        f = facts[fact_id]
        return f["status"] == "canon" and f["valid_to"] is None

    def fact_of(lid: str, value: Any) -> str | None:
        if not isinstance(value, str) or value not in facts:
            problems.append(f"{lid}: fact {value} is not in canon")
            return None
        return value

    conclusions: dict[str, dict] = {}
    for c in _items(doc, "conclusions", problems):
        if (cid := local(c, "conclusion")) and (fact := fact_of(cid, c.get("fact"))):
            state = "solved" if fact in known else "unknown"
            conclusions[cid] = {"id": cid, "fact": fact, "state": state}
    nodes: dict[str, dict] = {}
    roots: set[str] = set()
    for n in _items(doc, "nodes", problems):
        if not (nid := local(n, "node")):
            continue
        entity, proactive = n.get("entity"), n.get("proactive")
        if not entity and not proactive:
            problems.append(f"{nid}: an entity or a proactive fact is required")
        if entity and (not isinstance(entity, str) or entity not in entities):
            problems.append(f"{nid}: entity {entity} is not in canon")
        if proactive and fact_of(nid, proactive) and holds(proactive):
            roots.add(nid)
        if n.get("entry") is True:
            roots.add(nid)
        nodes[nid] = {
            "id": nid,
            "entity": entity,
            "proactive": proactive,
            "entry": n.get("entry") is True,
        }
    clues: list[dict] = []
    for c in _items(doc, "clues", problems):
        if not (lid := local(c, "clue")):
            continue
        fact = fact_of(lid, c.get("fact"))
        on = c.get("on")
        if not isinstance(on, str):
            problems.append(f"{lid}: on must be a node id")
            continue
        if on not in nodes:
            problems.append(f"{lid}: on {on} is not a node of this mystery")
            continue
        raw = c.get("points_to") or []
        if not isinstance(raw, list) or not all(isinstance(t, str) for t in raw):
            problems.append(f"{lid}: points_to must be a list of ids")
            raw = [t for t in raw if isinstance(t, str)] if isinstance(raw, list) else []
        for t in raw:
            if t not in nodes and t not in conclusions:
                problems.append(f"{lid}: points_to {t} is neither a node nor a conclusion here")
        state = "hidden"
        if fact is not None:
            state = "found" if fact in known else "hidden" if holds(fact) else "lost"
        clues.append(
            {
                "id": lid,
                "fact": fact,
                "on": on,
                "points_to": raw,
                "mobile": c.get("mobile") is True,
                "state": state,
            }
        )
    by_id = {c["id"]: c for c in clues}
    for lid in lose:
        if lid not in by_id:
            raise CanonError(f"There is no clue {lid} in this mystery.")
        if by_id[lid]["state"] == "found":
            raise CanonError(f"{lid} was found: what the party knows stays known, it is not lost.")
        if by_id[lid]["state"] == "lost":
            raise CanonError(f"{lid} is already lost.")
        by_id[lid]["state"] = "lost"

    live = [c for c in clues if c["state"] != "lost"]
    reachable, queue = set(roots), deque(roots)
    while queue:
        current = queue.popleft()
        for c in live:
            if c["on"] == current:
                for t in c["points_to"]:
                    if t in nodes and t not in reachable:
                        reachable.add(t)
                        queue.append(t)

    def pointing(target: str) -> list[dict]:
        return [c for c in live if target in c["points_to"]]

    warnings: list[dict] = []
    if any(c["state"] != "solved" for c in conclusions.values()):  # a mystery still open
        warnings = _warnings(nodes, conclusions, roots, reachable, pointing)
    found_targets = {t for c in clues if c["state"] == "found" for t in c["points_to"]}
    return {
        "mystery": doc.get("id"),
        "conclusions": [
            {
                **c,
                "live_clues": len(p := pointing(cid)),
                "unreachable_clues": sum(x["on"] not in reachable for x in p),
                "found_clues": sum(x["state"] == "found" for x in p),
                "nodes": len({x["on"] for x in p}),
            }
            for cid, c in conclusions.items()
        ],
        "nodes": [
            {
                **n,
                "reachable": nid in reachable,
                "within_reach": nid in roots or nid in found_targets,
                "incoming_clues": len(pointing(nid)),
            }
            for nid, n in nodes.items()
        ],
        "clues": clues,
        "problems": problems,
        "warnings": warnings,
        "simulated_loss": list(lose),
    }


def _warnings(nodes, conclusions, roots, reachable, pointing) -> list[dict]:
    def warn(code: str, message: str) -> dict:
        return {"code": code, "message": message}

    if not roots:
        return [
            warn(
                "mystery-entry",
                "no entry node and no proactive fact holds: nothing brings "
                "the party into the investigation",
            )
        ]
    out = []
    for nid, node in nodes.items():
        if nid not in reachable:
            out.append(
                warn(
                    "mystery-unreachable",
                    f"{nid} is unreachable from the entries through clues that are not lost",
                )
            )
        if not node["entry"] and not node["proactive"] and (n := len(pointing(nid))) < 3:
            out.append(
                warn(
                    "mystery-node-clues",
                    f"{nid}: {n} clue(s) point to it, 3 expected (inverted three-clue rule)",
                )
            )
    for cid, conclusion in conclusions.items():
        if conclusion["state"] == "solved":
            continue
        p = pointing(cid)
        on_reachable = [c for c in p if c["on"] in reachable]
        if not on_reachable:
            out.append(warn("mystery-conclusion", f"{cid}: no live clue on a reachable node"))
        elif len(p) < 3:
            out.append(warn("mystery-three-clues", f"{cid}: {len(p)} live clue(s), 3 expected"))
        elif len(on_reachable) < 3:
            out.append(
                warn(
                    "mystery-three-clues",
                    f"{cid}: {len(on_reachable)} clue(s) on a reachable node, 3 expected",
                )
            )
        spots = {c["on"] for c in p}
        if len(p) >= 2 and len(spots) == 1:
            out.append(
                warn(
                    "mystery-single-node",
                    f"{cid}: all its clues are on {next(iter(spots))} (single point of failure)",
                )
            )
    return out


def tools(ws: Workspace) -> list[Tool]:
    """Recording and checking a mystery, bound to the served workspace."""

    def report(doc: dict, lose: list[str]) -> dict[str, Any]:
        facts = {f["id"]: f for f in index.search_facts(ws, include_retconned=True)}
        entities = {e["id"] for e in index.search_entities(ws)}
        known: set[str] = set()  # ponytail: what the party knows comes with knowers (#39)
        return check(doc, facts, entities, known, lose)

    def record_mystery(
        mystery: str,
        conclusions: list[dict[str, Any]],
        nodes: list[dict[str, Any]] | None = None,
        clues: list[dict[str, Any]] | None = None,
        notes: str = "",
    ) -> Change:
        """Record (or rewrite) the graph of a mystery, an entity you created first. Ids are
        yours, unique within the mystery. `conclusions`: [{"id", "fact"}], what the party may
        conclude, each a fact id. `nodes`: [{"id", "entity", "entry"}], where the party
        investigates (a place, a person, a faction), `entry: true` when the party is led there;
        or [{"id", "proactive"}], a fact (a front's agenda step) that brings the party in while
        it holds. `clues`: [{"id", "fact", "on", "points_to", "mobile"}], discoverable evidence
        (a fact) on a node, pointing to node and conclusion ids. A lost clue is a closed fact;
        a found clue a fact the party knows. Refused if a reference does not resolve; run
        check_mystery for the three-clue and reachability warnings."""
        if mystery not in {e["id"] for e in index.search_entities(ws)}:
            raise CanonError(f"No entity {mystery!r} in canon; create the mystery first.")
        front = {
            "id": mystery,
            "conclusions": conclusions,
            "nodes": nodes or [],
            "clues": clues or [],
        }
        if problems := report(front, [])["problems"]:
            raise CanonError("; ".join(problems))
        return Change(path=f"{MYSTERIES_DIR}/{mystery}.md", after=index.join_doc(front, notes))

    def check_mystery(mystery: str, lose: list[str] | None = None) -> dict[str, Any]:
        """A mystery's graph as canon stands: each conclusion, node and clue with its state
        (clues hidden, found or lost; conclusions unknown or solved), the nodes reachable from
        the entries, the problems (references that no longer resolve) and the warnings: three
        clues per conclusion, three clues to each node that is not an entry (inverted rule),
        reachability, single point of failure. `lose` simulates losing those clues; nothing is
        written."""
        path = ws.root / MYSTERIES_DIR / f"{mystery}.md"
        known_ids = {e["id"] for e in index.search_entities(ws)}  # never a path from the caller
        if mystery not in known_ids or not path.is_file():
            raise CanonError(f"No mystery {mystery!r} in canon.")
        front, _ = index.split_doc(path.read_text())
        return report(front, lose or [])

    return [
        Tool(fn=record_mystery, responsibility="prep", delegated_action=True, reversible=True),
        Tool(fn=check_mystery, responsibility="prep", delegated_action=False, reversible=True),
    ]
