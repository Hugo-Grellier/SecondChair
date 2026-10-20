"""The VTT connector slot: how the Core has a `VttAction` taken (ARC-04, ARC-16), reads what only
the VTT knows, and tells the VTT a session started.

The connector serving this campaign plugs its functions in when `serve` starts; the Core never
talks to a VTT itself. One process serves one campaign (ARC-18), so there is one slot.
"""

from collections.abc import Callable
from typing import Any


class VttError(Exception):
    """A failed action, or a read the VTT could not answer, with a message for the GM."""


class CeilingRefusal(VttError):
    """The VTT's ceiling refused the action (DEL-19): a failed action and a call (DEL-20)."""


# perform(op, target, params, expect, level) -> (before, after): take the action at the delegation
# `level` (None for the GM's undo), refusing it if the document's fields differ from `expect`
# (when not None); raise VttError when it fails, CeilingRefusal when the ceiling refused it.
type Perform = Callable[[str, str, dict, dict | None, str | None], tuple[dict, dict]]
# read(op, params) -> the VTT's answer; raise VttError when it cannot answer.
type Read = Callable[[str, dict], Any]
# session_started() -> a message for the GM on what the VTT did for the new live session.
type SessionStarted = Callable[[], str]

NO_VTT = (
    "No GM client is connected: `secondchair serve` this campaign and open its world as GM in "
    "the VTT."
)

_perform: Perform | None = None
_read: Read | None = None
_session_started: SessionStarted | None = None


def connect(
    perform: Perform | None,
    read: Read | None = None,
    session_started: SessionStarted | None = None,
) -> None:
    global _perform, _read, _session_started
    _perform, _read, _session_started = perform, read, session_started


def perform(
    op: str, target: str, params: dict, expect: dict | None, level: str | None
) -> tuple[dict, dict]:
    if _perform is None:
        raise VttError(NO_VTT)
    return _perform(op, target, params, expect, level)


def read(op: str, params: dict) -> Any:
    if _read is None:
        raise VttError(NO_VTT)
    return _read(op, params)


def session_started() -> str:
    """Have the connector do what a new live session needs in the VTT: push the campaign's
    current date into its clock (CAL-11). A message for the GM."""
    return _session_started() if _session_started is not None else ""
