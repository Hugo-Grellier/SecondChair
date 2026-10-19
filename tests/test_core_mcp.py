import asyncio
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import InstallBlock, Serving
from mcp import Client

from secondchair.cli import main

BLOCK = """
from secondchair.core.tools import Tool

def roll_initiative(creature: str) -> str:
    "Roll initiative for a creature."
    return creature

def tools(ws):
    return [Tool(fn=roll_initiative, responsibility="rules_and_combat",
                 delegated_action=True, reversible=False)]
"""


@pytest.fixture
def core(
    tmp_path: Path, machine_config: dict[str, str], serving: Serving, install_block: InstallBlock
) -> Iterator[str]:
    """A running Core with one extra block installed; yields its MCP URL."""
    site = install_block("fakeblock", BLOCK)
    ws = tmp_path / "campaign"
    main(["init", str(ws), "--language", "fr", "--calendar", "absalom"])
    with serving(ws, {**machine_config, "PYTHONPATH": str(site)}) as line:
        assert line.startswith("Serving "), line
        yield f"{line.rsplit(' ', 1)[1]}/mcp"


def test_campaign_info_answers_several_agents_at_once(core: str) -> None:
    async def call() -> object:
        async with Client(core) as client:
            return (await client.call_tool("campaign_info", {})).structured_content

    async def both() -> tuple[object, object]:
        return await asyncio.gather(call(), call())

    for info in asyncio.run(both()):
        assert info == {
            "campaign_language": "fr",
            "workspace_schema_version": 1,
            "protocol_version": "0.1.0",
        }


def test_a_block_tool_is_listed_with_its_declarations(core: str) -> None:
    async def list_tools():
        async with Client(core) as client:
            return (await client.list_tools()).tools

    tools = {tool.name: tool for tool in asyncio.run(list_tools())}
    assert tools["roll_initiative"].meta == {
        "secondchair/responsibility": "rules_and_combat",
        "secondchair/delegated_action": True,
        "secondchair/reversible": False,
    }
    assert tools["campaign_info"].meta == {
        "secondchair/responsibility": "memory",
        "secondchair/delegated_action": False,
        "secondchair/reversible": True,
    }


@pytest.mark.parametrize(
    ("declaration", "message"),
    [
        ("delegated_action=False, reversible=True", "responsibility"),
        ('responsibility="prep", delegated_action=True', "reversible"),
        ('responsibility="cooking", delegated_action=True, reversible=True', "cooking"),
        ('responsibility="prep", delegated_action=True, reversible="yes"', "reversible"),
    ],
)
def test_serve_refuses_an_incomplete_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    install_block: InstallBlock,
    declaration: str,
    message: str,
) -> None:
    site = install_block(
        "badblock",
        f"""
        from secondchair.core.tools import Tool

        def act() -> None:
            "Act."

        def tools(ws):
            return [Tool(fn=act, {declaration})]
        """,
    )
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.delitem(sys.modules, "badblock", raising=False)  # each case's own module
    ws = tmp_path / "campaign"
    main(["init", str(ws), "--language", "fr", "--calendar", "absalom"])

    assert main(["serve", str(ws)]) == 1
    err = capsys.readouterr().err
    assert "badblock" in err
    assert message in err
