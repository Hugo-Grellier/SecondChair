"""`check_prep`: a deterministic linter over a prep file's YAML index block (workspace layout,
`prep/`). It reports, never fixes. It lives in the System extension because the encounter and
treasure maths are PF2e's; the Core only parses the block."""

import re
from typing import Any

import yaml

from secondchair.core import index, prep, vtt
from secondchair.core.index import CanonError
from secondchair.core.tools import Tool
from secondchair.core.workspace import Workspace
from secondchair_pf2e.calculators import CalculatorError, encounter, treasure

KEY = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _clue_ids(ws: Workspace) -> set[str]:
    """Clue ids of the canon mysteries and of draft notes carrying the same graph in their
    front matter."""
    ids: set[str] = set()
    for folder in ("canon/mysteries", "notes"):
        for path in (ws.root / folder).rglob("*.md"):
            try:
                front, _ = index.split_doc(path.read_text())
            except CanonError, yaml.YAMLError, OSError, UnicodeDecodeError:
                continue
            clues = front.get("clues")
            if isinstance(clues, list):
                ids |= {c["id"] for c in clues if isinstance(c, dict) and "id" in c}
    return ids


def check_prep_tool(ws: Workspace) -> Tool:
    def check_prep(path: str) -> dict[str, Any]:
        """Lint a prep note's index block, the last fenced `yaml` block of the file: `creatures`
        and each encounter creature `{uuid, name, level}` resolve through the connector's
        compendium search (reported `unchecked` when no GM client is connected, never a
        failure); each `encounters` entry `{id, level, party_size, creatures, xp?, threat?}` has
        its XP and threat recomputed (GM Core) and compared with any it states; each `treasure`
        entry `{level, party_size, total_gp}` stays within the level's budget; each of `clues`
        exists in a canon mystery or a draft note; each of `scenes` has a desired state in
        `scenes/`. Returns `{ok, problems, unchecked, encounters, treasure}`; it fixes nothing."""
        block = prep.index_block(prep.read_prep(ws, path))
        problems: list[str] = []
        unchecked: list[str] = []
        computed: list[dict[str, Any]] = []
        budgets: list[dict[str, Any]] = []

        def items(key: str) -> list[Any]:
            value = block.get(key) or []
            if not isinstance(value, list):
                problems.append(f"{key}: must be a list")
                return []
            return value

        def mapping(key: str, item: Any) -> dict[str, Any] | None:
            if isinstance(item, dict):
                return item
            problems.append(f"{key}: {item!r} must be a mapping")
            return None

        creatures = [
            (c, "creatures")
            for c in map(lambda i: mapping("creatures", i), items("creatures"))
            if c
        ]
        specs = [e for e in map(lambda i: mapping("encounters", i), items("encounters")) if e]
        for spec in specs:
            inner = spec.get("creatures")
            if not isinstance(inner, list) or not inner:
                problems.append(f"encounter {spec.get('id')}: creatures must be a non-empty list")
                spec["creatures"] = []
            creatures += [(c, f"encounter {spec.get('id')}") for c in spec["creatures"]]

        offline, found = False, {}
        for c, where in creatures:
            if not isinstance(c, dict) or not isinstance(c.get("uuid"), str):
                problems.append(f"{where}: a creature needs a uuid")
                continue
            uuid, name = c["uuid"], c.get("name")
            if not name:
                unchecked.append(f"{uuid} ({where}): no name to look it up by")
                continue
            if offline:
                unchecked.append(f"{uuid} ({where}): no GM client connected")
                continue
            try:
                if name not in found:
                    entries = vtt.read("search_compendium", {"query": name, "limit": 100})
                    found[name] = {e["uuid"]: e for e in entries}
            except vtt.VttError:
                offline = True
                unchecked.append(f"{uuid} ({where}): no GM client connected")
                continue
            if uuid not in found[name]:
                problems.append(f"{uuid} ({where}): not found in the compendium searching {name!r}")
            else:
                level = found[name][uuid].get("level")
                if None not in (level, c.get("level")) and level != c["level"]:
                    problems.append(
                        f"{uuid} ({where}): level {c['level']} but the entry is {level}"
                    )

        for spec in specs:
            try:
                levels = [c.get("level") for c in spec["creatures"] if isinstance(c, dict)]
                result = encounter(spec.get("level"), spec.get("party_size"), levels)  # ty: ignore
            except (CalculatorError, TypeError) as e:
                problems.append(f"encounter {spec.get('id')}: {e}")
                continue
            computed.append(
                {"id": spec.get("id"), "xp": result["total"], "threat": result["threat"]}
            )
            if spec.get("xp") not in (None, result["total"]):
                problems.append(
                    f"encounter {spec.get('id')}: states {spec['xp']} XP, GM Core gives "
                    f"{result['total']}"
                )
            if spec.get("threat") not in (None, result["threat"]):
                problems.append(
                    f"encounter {spec.get('id')}: states {spec['threat']} threat, GM Core gives "
                    f"{result['threat']}"
                )

        for t in (m for m in map(lambda i: mapping("treasure", i), items("treasure")) if m):
            try:
                budget = treasure(t.get("level"), t.get("party_size"))["budget_gp"]  # ty: ignore
                total = t["total_gp"]
                budgets.append({"level": t["level"], "total_gp": total, "budget_gp": budget})
                if total > budget:
                    problems.append(
                        f"treasure level {t['level']}: {total} gp over the {budget} gp budget"
                    )
            except (CalculatorError, KeyError, TypeError) as e:
                problems.append(f"treasure {t}: {e!r}")

        clues = _clue_ids(ws)
        problems += [
            f"clue {c} is in no mystery or draft note" for c in items("clues") if c not in clues
        ]
        for key in items("scenes"):
            if not (isinstance(key, str) and KEY.match(key)):
                problems.append(f"scene {key!r}: not a scene key")
            elif not (ws.root / "scenes" / f"{key}.yaml").is_file():
                problems.append(f"scene {key}: no desired state in scenes/")

        return {
            "ok": not problems,
            "problems": problems,
            "unchecked": unchecked,
            "encounters": computed,
            "treasure": budgets,
        }

    return Tool(fn=check_prep, responsibility="prep", delegated_action=False, reversible=True)
