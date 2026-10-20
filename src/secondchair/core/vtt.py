"""The VTT connector slot: how the Core has a `VttAction` taken (ARC-04, ARC-16).

The connector serving this campaign plugs its `perform` in when `serve` starts; the Core never
talks to a VTT itself. One process serves one campaign (ARC-18), so there is one slot.
"""

from collections.abc import Callable


class VttError(Exception):
    """A failed action: the VTT did not take it, with a message for the GM."""


class CeilingRefusal(VttError):
    """The VTT's ceiling refused the action (DEL-19): a failed action and a call (DEL-20)."""


# perform(op, target, params, expect, level) -> (before, after): take the action at the delegation
# `level` (None for the GM's undo), refusing it if the document's fields differ from `expect`
# (when not None); raise VttError when it fails, CeilingRefusal when the ceiling refused it.
type Perform = Callable[[str, str, dict, dict | None, str | None], tuple[dict, dict]]

_perform: Perform | None = None


def connect(perform: Perform | None) -> None:
    global _perform
    _perform = perform


def perform(
    op: str, target: str, params: dict, expect: dict | None, level: str | None
) -> tuple[dict, dict]:
    if _perform is None:
        raise VttError(
            "No GM client is connected: `secondchair serve` this campaign and open its world "
            "as GM in the VTT."
        )
    return _perform(op, target, params, expect, level)
