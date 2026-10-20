"""The Core's own tools, registered through the same entry point as any block's."""

from typing import TypedDict

from secondchair.core import PROTOCOL_VERSION, canon, knowledge, mystery, world
from secondchair.core.tools import Tool
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
        *mystery.tools(ws),
        *knowledge.tools(ws),
        *world.tools(ws),
    ]
