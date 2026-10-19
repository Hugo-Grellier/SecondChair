# Contract: tool registration and the Core's MCP endpoint

Protocol version: **0.1.0** (`secondchair.core.PROTOCOL_VERSION`). Requirements: ARC-01, ARC-02, ARC-03, ARC-04, CAN-12, DEL-09, DEL-18, DEL-21, DEL-28, ARC-17, ARC-17a, ARC-19, ARC-21, ARC-23, ARC-29, PKG-05, PKG-06, PKG-19.

## The MCP endpoint

`secondchair serve <workspace>` carries the Core's MCP server over **Streamable HTTP** at `http://127.0.0.1:<port>/mcp`, the port coming from the machine configuration (default 7240). There is no stdio mode: every agent host (the GM's session, the runners) shares this one Core. The endpoint is unauthenticated and bound to loopback only; requests whose `Host` or `Origin` is not a loopback name are refused (DNS rebinding). `GET /` answers `{"service": "secondchair", "campaign_language": …, "protocol_version": …}`.

`secondchair host setup <claude|codex>` prints the configuration an agent host needs to reach that endpoint, and how to install the playbooks: for Claude Code a plugin (`claude plugin marketplace add <playbooks>` then `claude plugin install secondchair@secondchair`), for Codex a skill bundle linked into `~/.codex/skills/`. It writes no file: the GM pastes or runs what it prints.

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

An action that acts in the VTT returns a `VttAction` instead, which the Core logs and has the VTT connector take ([foundry-bridge.md](foundry-bridge.md#actions-arc-04-arc-07-arc-09)). The Core reads none of its fields; the connector gives them their meaning.

```python
from secondchair.core.tools import VttAction


def move_token(token: str, x: int, y: int) -> VttAction:
    """Move a token on its scene."""
    return VttAction(op="move_token", target=token, params={"x": x, "y": y})
```

| `VttAction` field | Type | Rule |
|---|---|---|
| `op` | string | The connector's operation, generic or mechanical. |
| `target` | string | The document acted on, as the connector names it (a Foundry UUID). |
| `params` | object | The fields to set. |
| `source` | string or null | As for `Change`. |

The log entry of a VTT action carries `op`, and the fields the VTT reported `before` and `after` it. A VTT action the VTT did not take is a **failed action**: logged with status `failed` and its `error`, and returned to the agent as an MCP error. The Foundry connector registers `move_token` and `set_door` (VTT operations, reversible).

The Core adds a required `agent` string argument to every delegated action's MCP input schema: the agent's name, recorded for traceability only (ARC-22). It also adds an optional `job` integer: the job the agent is running (see below). A block's `fn` must not have an `agent` or a `job` parameter. On each call the Core reads the current moment and the delegation table, then:

| Effective level | What happens | Result |
|---|---|---|
| manual | refused; nothing is written or logged | an MCP error saying why |
| propose | logged as pending; nothing is written until the GM approves | `{"entry": 3, "status": "pending"}` |
| act-then-review, autonomous | written at once and logged | `{"entry": 3, "status": "applied"}` |

An irreversible action is held at propose (DEL-09) and only an authenticated Surface approves it (DEL-29).

A delegated action's `fn` that finds its change would contradict canon raises `secondchair.core.tools.Contradiction(path, message)`. The Core writes nothing, logs the action with `status: refused` and the message as `refusal` (a continuity error, MET-01), and returns an MCP error.

The Core's own delegated actions are all under memory and reversible: `create_entity`, `record_fact`, `correct_fact`, `record_event` and `record_knowledge` ([workspace layout](workspace-layout.md#canonfacts)).
The mystery graph adds `record_mystery`, under prep and reversible ([workspace layout](workspace-layout.md#canonmysteries)).

## GM interactions relayed by agents

`approve_proposal(entry, gm_words)` is served by the Core itself, outside block registration, with `_meta: {"secondchair/gm_interaction": true}`. An agent calls it only when the GM approved a pending reversible action in conversation, quoting the GM's words; the approval is logged "via agent" with the quote (DEL-28). An irreversible action cannot be approved this way.

On the CLI, in the workspace (or with `-w <workspace>`): `secondchair approve <entry>`, `secondchair reject <entry> --reason <reason>`, `secondchair log undo <entry> --reason <reason>`, the reason one of contradiction, rules, tone, other (DEL-26), and `secondchair moment <prep|live-session|between-sessions>`, which needs an interactive terminal (DEL-03a). The log records whether each GM interaction came from an interactive terminal (`authenticated`).

Approving or undoing a VTT action needs the GM client, which only the `serve` process holds. The CLI therefore relays those two gestures to `POST /gm` on the Core serving the campaign, found through `.secondchair/serve.json`: `{"gesture": "approve" | "undo", "entry", "reason", "authenticated", "workspace"}` with `Authorization: Bearer <token>`, the token `secondchair token` prints. The Core refuses a wrong token (401), a malformed gesture (400) and another workspace's gesture (409), and answers a refused gesture with 409 and its message. With no Core serving the campaign, the CLI says to run `secondchair serve`.

## Jobs

An agent running a job ([`job.schema.json`](job.schema.json)) passes `job` to every delegated action. The job must be started; the action is then bound by the delegation table of the job's moment (a manual cell refuses it), and its log entry records the job and the runner configuration it was started with. Two tools, served by the Core outside block registration with `_meta: {"secondchair/job": true}`, let a session take and close a job:

| Tool | Does |
|---|---|
| `start_job(job, host, model, effort)` | Starts a queued job from the GM's own session (ARC-29): the host, model and effort the session reports are logged as the effective configuration. Returns the job record; its tier is only a hint. |
| `finish_job(job)` | Marks a started job done. |

A runner started by `secondchair jobs run` logs its attempt itself and gives the agent the contract in its prompt; the job is done when the agent calls `finish_job` or exits cleanly.

## Playbooks

A playbook is an [Agent Skills](https://agentskills.io/specification) skill (`skills/<name>/SKILL.md`), in English, telling the agent to write in the campaign language (ARC-21). Its front matter's `metadata` declares what the Core needs to queue a job for it, never a model name (ARC-25):

```yaml
metadata:
  secondchair-responsibility: memory
  secondchair-tier: standard              # fast, standard or deep; a job may override it
  secondchair-inputs: bible               # comma-separated input names
  secondchair-expected-output: One canon entity per named person, place, …
```

The Core's playbooks live in `src/secondchair/playbooks/`, which is both a Claude Code plugin (`.claude-plugin/`) and, through its `skills/` directory, a Codex skill bundle (PKG-19). The first is `rebuild-entities-from-a-bible` (memory, standard).

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

The Core's own reads, all under memory: `campaign_info` returns the campaign language, the workspace schema version and the protocol version; `search_entities(text)`, `search_facts(text, entity, relation, at, include_retconned)` and `search_events(text, fact)` search the derived index, structured and full text (every word of `text` must match); `what_knows(knower, at)` returns what a knower holds, inheritance included, and `check_audience_content(audience, text, cites, at)` checks content for an audience ([workspace layout](workspace-layout.md#canonknowledge)). A read's refusal reaches the agent as an MCP error with its message. The mystery graph adds `check_mystery(mystery, lose)`, under prep: the graph with each element's state, its problems and warnings, `lose` simulating the loss of clues without writing.

## Versioning

The protocol version is semver and versions this contract and the wire contracts that follow (ARC-17a); before v4.0 a breaking change is free. The Foundry modules' version is checked at the bridge handshake ([foundry-bridge.md](foundry-bridge.md)); how a Python block declares its supported range is still open (#77).
