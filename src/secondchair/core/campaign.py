"""The Core's own tools, registered through the same entry point as any block's."""

from typing import TypedDict

from secondchair.core import (
    PROTOCOL_VERSION,
    canon,
    knowledge,
    library,
    mystery,
    prep,
    signals,
    world,
)
from secondchair.core.tools import Block, Tool
from secondchair.core.workspace import Workspace


class CampaignInfo(TypedDict):
    campaign_language: str
    workspace_schema_version: int
    protocol_version: str


def tools(ws: Workspace) -> list[Tool]:
    def campaign_info() -> CampaignInfo:
        """The served campaign: its language, workspace schema and the Core's protocol version."""
        return {
            "campaign_language": ws.campaign_language,
            "workspace_schema_version": ws.schema_version,
            "protocol_version": PROTOCOL_VERSION,
        }

    # ponytail: a read sits under memory (canon and continuity) until reads get their own rule.
    return [
        Tool(fn=campaign_info, responsibility="memory", delegated_action=False, reversible=True),
        *canon.tools(ws),
        *library.tools(ws),
        *mystery.tools(ws),
        *knowledge.tools(ws),
        *world.tools(ws),
        *prep.tools(ws),
        *signals.tools(ws),
    ]


# The protocol range this block supports (ARC-17): `serve` refuses it outside the range.
BLOCK = Block(protocol=("0.1.0", "0.2.0"), tools=tools)
