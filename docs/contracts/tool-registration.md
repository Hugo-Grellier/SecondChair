# Contract: tool registration and the Core's MCP endpoint

Protocol version: **0.1.0** (`secondchair.core.PROTOCOL_VERSION`). Requirements: ARC-01, ARC-02, ARC-03, ARC-17, ARC-17a, ARC-19, PKG-05, PKG-06, PKG-19.

## The MCP endpoint

`secondchair serve <workspace>` carries the Core's MCP server over **Streamable HTTP** at `http://127.0.0.1:<port>/mcp`, the port coming from the machine configuration (default 7240). There is no stdio mode: every agent host (the GM's session, the runners) shares this one Core. The endpoint is unauthenticated and bound to loopback only; requests whose `Host` or `Origin` is not a loopback name are refused (DNS rebinding). `GET /` answers `{"service": "secondchair", "campaign_language": …, "protocol_version": …}`.

`secondchair host setup <claude|codex>` prints the configuration an agent host needs to reach that endpoint. It writes no file: the GM pastes or runs what it prints.

## Registering tools

The Core is the only MCP server agents see (ARC-03). A block (System extension, VTT connector, or the Core itself) registers tools through a Python **entry point** in the group `secondchair.tools`:

```toml
# the block's pyproject.toml
[project.entry-points."secondchair.tools"]
pf2e = "secondchair_pf2e.tools:tools"
```

The entry point is a function called once when `serve` starts, with the served `Workspace`, returning the block's tools:

```python
from secondchair.core.tools import Tool
from secondchair.core.workspace import Workspace


def tools(ws: Workspace) -> list[Tool]:
    def roll_initiative(creature: str) -> str:
        """Roll initiative for a creature."""
        ...

    return [
        Tool(fn=roll_initiative, responsibility="rules_and_combat",
             delegated_action=True, reversible=False),
    ]
```

| `Tool` field | Type | Rule |
|---|---|---|
| `fn` | function | Its name is the MCP tool name, its docstring the description, its typed parameters the input schema. Names are unique across all blocks. |
| `responsibility` | string | One of `prep`, `memory`, `vtt_operations`, `rules_and_combat`, `living_world`, `npcs`, `narrative_direction`, `disclosure` (DEL-01). |
| `delegated_action` | bool | `true` for a delegated action, `false` for a read. |
| `reversible` | bool | Whether the action can be undone (DEL-25). A read declares `true`. |

All three declarations are required. A registration missing one, with an unknown responsibility or a non-boolean flag, a duplicate name, or an entry point that raises, stops `serve` before it listens, with a message naming the block.

## What agents see

Each tool in `tools/list` carries its declarations in `_meta`, and the matching MCP annotations:

```json
{
  "name": "roll_initiative",
  "_meta": {
    "secondchair/responsibility": "rules_and_combat",
    "secondchair/delegated_action": true,
    "secondchair/reversible": false
  },
  "annotations": {"readOnlyHint": false, "destructiveHint": true}
}
```

The Core's own read, `campaign_info` (memory, read), returns the campaign language, the workspace schema version and the protocol version.

## Versioning

The protocol version is semver and versions this contract and the wire contracts that follow (ARC-17a); before v4.0 a breaking change is free. The Foundry modules' range is checked at the bridge handshake (#47); how a Python block declares its supported range is still open (#77).
