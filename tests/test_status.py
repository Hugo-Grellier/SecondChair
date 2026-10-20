"""`secondchair status`: where the campaign stands and the GM's next step, and the warning when
a session starts before the last one was wrapped."""

import pytest
from test_delegation import call, gm, set_level, ws  # noqa: F401  (ws is a fixture)

from secondchair.cli import status
from secondchair.core.workspace import Workspace


def test_a_fresh_campaign_says_to_prepare_session_one(ws: Workspace) -> None:  # noqa: F811
    text = status(ws)

    assert "Moment: prep" in text and "Sessions played: 0" in text
    assert "prepare session 1" in text
    assert "secondchair date <date>" in text


def test_status_names_the_pending_approvals_and_the_command(ws: Workspace) -> None:  # noqa: F811
    set_level(ws, "prep", "prep", "propose")
    for n in (1, 2):
        call(ws, "write_prep", {"path": f"n{n}.md", "text": "x", "agent": "claude-prep"})

    assert "secondchair approve 1 2" in status(ws)


def test_an_unwrapped_session_shows_its_wrap_job_and_warns_at_the_next_start(
    ws: Workspace,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert gm("session", "start", root=ws.root) == 0
    assert gm("session", "end", root=ws.root) == 0

    text = status(ws)
    assert "Session 1 is not wrapped" in text
    assert 'start SecondChair job 1"' in text
    assert "prepare session 2" not in text  # the wrap comes first

    capsys.readouterr()
    assert gm("session", "start", root=ws.root) == 0
    assert "session 1 is not wrapped yet" in capsys.readouterr().out
