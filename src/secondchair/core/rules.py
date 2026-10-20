"""Rules checks, discrepancies and house rules (RUL-14, RUL-17, RUL-23, RUL-24, ADR 0011).

The Core knows no game system: a System extension registers its rules checks through the
`secondchair.rules_checks` entry point, a function `(observation, earlier) -> [(check, text)]`
where `earlier()` gives the observation's session in capture order. Each newly recorded
observation goes through every registered checker; a failed check is a **discrepancy**, a call
on the GM under rules_and_combat, held for the break by default (the cell's deadline mode can
force now). It names no module (RUL-17): the observation keeps the user and the module flags.

Fixing a discrepancy is a proposal, never automatic: `propose_fix` holds the fixing VTT action at
propose whatever the level. Marking it intended records a named **house rule**
(`house-rules.yaml`) that silences that kind of check until it is removed.
"""

import functools
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import entry_points
from typing import Any

import yaml

from secondchair.core import calls, delegation
from secondchair.core.delegation import (
    CALLS_DIR,
    DelegationError,
    _interaction,
    _read_yaml,
    _write,
    current_moment,
    locked,
)
from secondchair.core.tools import Tool, VttAction
from secondchair.core.workspace import Workspace, WorkspaceError

ENTRY_POINT_GROUP = "secondchair.rules_checks"
HOUSE_RULES_FILE = "house-rules.yaml"
RESPONSIBILITY = "rules_and_combat"

type Checker = Callable[[dict, Callable[[], list[dict]]], list[tuple[str, str]]]


@functools.cache
def checkers() -> tuple[Checker, ...]:
    return tuple(ep.load() for ep in entry_points(group=ENTRY_POINT_GROUP))


def check(ws: Workspace, observation: dict) -> list[dict]:
    """Run every rules check on a newly recorded observation; the discrepancies raised. A check
    a house rule silences raises none. A checker that breaks is reported, never fatal: the
    observation is already recorded."""
    from secondchair.core import observations  # it records, then calls this

    session = observation["session"]
    found = []
    for checker in checkers():
        try:
            found += checker(observation, lambda: observations.of_session(ws, session))
        except Exception as e:  # a payload the checker cannot read: no check, no discrepancy
            print(f"SecondChair: rules check failed on {observation['id']}: {e}", file=sys.stderr)
    if not found:
        return []
    raised = []
    with locked(ws):
        silenced = {rule["check"] for rule in house_rules(ws)}
        for kind, text in found:
            if kind in silenced:
                continue
            raised.append(
                calls.open_call(
                    ws,
                    kind="discrepancy",
                    responsibility=RESPONSIBILITY,
                    table_moment=current_moment(ws)[0],
                    blocking=False,
                    message=text,
                    check=kind,
                    observation=observations.locator(observation),
                )
            )
    return raised


def house_rules(ws: Workspace) -> list[dict]:
    """The campaign's house rules, each {name, check, call, at}."""
    path = ws.root / HOUSE_RULES_FILE
    rules = _read_yaml(path).get("house_rules", []) if path.is_file() else []
    if not isinstance(rules, list):
        raise WorkspaceError(f"{path}: house_rules must be a list.")
    return rules


def _open_discrepancy(ws: Workspace, call_id: int) -> dict:
    path = ws.root / CALLS_DIR / f"{call_id:06d}.yaml"
    call = _read_yaml(path) if path.is_file() else None
    if call is None or call["kind"] != "discrepancy" or call["status"] != "open":
        raise DelegationError(f"Call {call_id} is not an open discrepancy.")
    return call


def _write_rules(ws: Workspace, rules: list[dict]) -> None:
    text = yaml.safe_dump({"house_rules": rules}, sort_keys=False, allow_unicode=True)
    _write(ws.root / HOUSE_RULES_FILE, text)


def mark_intended(
    ws: Workspace, call_id: int, name: str, channel: str, authenticated: bool
) -> dict:
    """The GM marks an open discrepancy as intended: a house rule named `name` silences its kind
    of check, and the call is answered. It turns a check off, so only an authenticated Surface
    may (ARC-13)."""
    if not authenticated:
        raise DelegationError(
            "A house rule turns a rules check off: record it from an authenticated Surface (the "
            "CLI in an interactive terminal)."
        )
    name = name.strip()
    if not name:
        raise DelegationError("A house rule needs a name.")
    with locked(ws):
        call = _open_discrepancy(ws, call_id)
        rules = house_rules(ws)
        if any(rule["name"] == name for rule in rules):
            raise DelegationError(f"A house rule is already named {name!r}.")
        rule = {
            "name": name,
            "check": call["check"],
            "call": call_id,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        _write_rules(ws, [*rules, rule])
        calls.close(ws, call_id)
        _interaction(
            ws,
            "add_house_rule",
            None,
            channel,
            authenticated,
            None,
            None,
            house_rule={k: rule[k] for k in ("name", "check", "call")},
        )
        return rule


def remove_house_rule(ws: Workspace, name: str, channel: str, authenticated: bool) -> dict:
    """Remove a house rule: its kind of check runs again. Accepted from any Surface."""
    with locked(ws):
        rules = house_rules(ws)
        rule = next((r for r in rules if r["name"] == name), None)
        if rule is None:
            raise DelegationError(f"No house rule is named {name!r}.")
        _write_rules(ws, [r for r in rules if r is not rule])
        _interaction(
            ws,
            "remove_house_rule",
            None,
            channel,
            authenticated,
            None,
            None,
            house_rule={k: rule[k] for k in ("name", "check", "call")},
        )
        return rule


def fix_discrepancy(discrepancy: int, op: str, target: str, params: dict[str, Any]) -> VttAction:
    """Propose the VTT action that fixes discrepancy `discrepancy`: `op` on `target` (a
    document UUID) setting `params`, as the VTT connector names them. It is held for the GM's
    approval whatever the delegation level (RUL-17)."""
    return VttAction(op=op, target=target, params=params, source=f"discrepancy {discrepancy}")


FIX = Tool(
    fn=fix_discrepancy, responsibility=RESPONSIBILITY, delegated_action=True, reversible=True
)


def propose_fix(
    ws: Workspace,
    discrepancy: int,
    op: str,
    target: str,
    params: dict[str, Any],
    agent: str,
    job: int | None = None,
) -> delegation.ActionResult:
    """Hold a fix for an open discrepancy at propose: the discrepancy's call is answered by the
    proposal's, which carries it as its message."""
    with locked(ws):
        call = _open_discrepancy(ws, discrepancy)
        hold = f"fix for discrepancy {discrepancy}: {call['message']}"
        done = delegation.act(
            ws, FIX, agent, lambda: FIX.fn(discrepancy, op, target, params), job, hold=hold
        )
        calls.close(ws, discrepancy)
        return done


def agent_tools(ws: Workspace) -> list[Callable[..., Any]]:
    """The MCP tool an agent proposes a discrepancy's fix with."""

    def fix_discrepancy(
        discrepancy: int,
        op: str,
        target: str,
        params: dict[str, Any],
        agent: str,
        job: int | None = None,
    ) -> delegation.ActionResult:
        """Propose the VTT action that fixes an open rules discrepancy (a call of kind
        discrepancy): `op` on `target` (a document UUID) setting `params`, such as the PF2e
        adapter's `set_actor` with {"system.attributes.hp.value": 12}. It is never applied
        automatically: the GM approves or rejects it. `agent`: your name; `job`: the job you
        run, if any."""
        with delegation._for_agent():
            return propose_fix(ws, discrepancy, op, target, params, agent, job)

    return [fix_discrepancy]
