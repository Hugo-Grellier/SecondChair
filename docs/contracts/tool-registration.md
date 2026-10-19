# Contract: tool registration and the Core's MCP endpoint

Protocol version: **0.1.0** (`secondchair.core.PROTOCOL_VERSION`). Requirements: ARC-01, ARC-02, ARC-03, ARC-04, DEL-09, DEL-18, DEL-21, DEL-28, ARC-17, ARC-17a, ARC-19, PKG-05, PKG-06, PKG-19.

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
        Tool(
            fn=roll_initiative,
            responsibility="rules_and_combat",
            delegated_action=True,
            reversible=False,
        ),
    ]
```

| `Tool` field | Type | Rule |
|---|---|---|
| `fn` | function | Its name is the MCP tool name, its docstring the description, its typed parameters the input schema. Names are unique across all blocks. |
| `responsibility` | string | One of `prep`, `memory`, `vtt_operations`, `rules_and_combat`, `living_world`, `npcs`, `narrative_direction`, `disclosure` (DEL-01). |
| `delegated_action` | bool | `true` for a delegated action, `false` for a read. |
| `reversible` | bool | Whether the action can be undone (DEL-25). A read declares `true`. |

All three declarations are required. A registration missing one, with an unknown responsibility or a non-boolean flag, a duplicate name, or an entry point that raises, stops `serve` before it listens, with a message naming the block.

## Delegated actions

The Core wraps every delegated action (ARC-04). A delegated action's `fn` does not act: it describes its effect and returns a `Change`, and the Core decides what happens to it.

```python
from secondchair.core.tools import Change


def create_note(title: str) -> Change:
    """Create a note."""
    return Change(path=f"notes/{title}.md", after=f"# {title}\n")
```

| `Change` field | Type | Rule |
|---|---|---|
| `path` | string | The workspace file the action writes, relative to the workspace root. |
| `after` | string or null | The file's new content; null deletes it. |
| `source` | string or null | What the action draws on, recorded in the log (DEL-24). |

The Core adds a required `agent` string argument to every delegated action's MCP input schema: the agent's name, recorded for traceability only (ARC-22). A block's `fn` must not have an `agent` parameter. On each call the Core reads the current moment and the delegation table, then:

| Effective level | What happens | Result |
|---|---|---|
| manual | refused; nothing is written or logged | an MCP error saying why |
| propose | logged as pending; nothing is written until the GM approves | `{"entry": 3, "status": "pending"}` |
| act-then-review, autonomous | written at once and logged | `{"entry": 3, "status": "applied"}` |

An irreversible action is held at propose (DEL-09) and only an authenticated Surface approves it (DEL-29). The Core's own delegated action is `create_entity` (memory, reversible).

## GM interactions relayed by agents

`approve_proposal(entry, gm_words)` is served by the Core itself, outside block registration, with `_meta: {"secondchair/gm_interaction": true}`. An agent calls it only when the GM approved a pending reversible action in conversation, quoting the GM's words; the approval is logged "via agent" with the quote (DEL-28). An irreversible action cannot be approved this way.

On the CLI, in the workspace (or with `-w <workspace>`): `secondchair approve <entry>`, `secondchair reject <entry> --reason <reason>`, `secondchair log undo <entry> --reason <reason>`, the reason one of contradiction, rules, tone, other (DEL-26), and `secondchair moment <prep|live-session|between-sessions>`, which needs an interactive terminal (DEL-03a). The log records whether each GM interaction came from an interactive terminal (`authenticated`).

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

The protocol version is semver and versions this contract and the wire contracts that follow (ARC-17a); before v4.0 a breaking change is free. The Foundry modules' version is checked at the bridge handshake ([foundry-bridge.md](foundry-bridge.md)); how a Python block declares its supported range is still open (#77).
