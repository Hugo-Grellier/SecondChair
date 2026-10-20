import asyncio
import json
import os
import re
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml
from conftest import Serving
from mcp import Client

from secondchair import runner
from secondchair.cli import main
from secondchair.core import index, jobs, workspace
from secondchair.core.server import build_server
from secondchair.core.tools import RESPONSIBILITIES
from secondchair.core.workspace import Workspace

ROOT = Path(__file__).parents[1]
CONTRACTS = ROOT / "docs/contracts"
JOB_SCHEMA = json.loads((CONTRACTS / "job.schema.json").read_text())
LOG_SCHEMA = json.loads((CONTRACTS / "action-log-entry.schema.json").read_text())
BIBLE = ROOT / "sample-campaign/bible.md"
PLAYBOOK = "rebuild-entities-from-a-bible"
OK = [sys.executable, "-c", "pass"]  # exits cleanly without finish_job: a failed attempt (#171)


def finishing(ws: Workspace) -> list[str]:
    """A host that calls finish_job for its job, then exits cleanly."""
    end = "import sys, pathlib; from secondchair.core import jobs, workspace as w; "
    end += "jobs.end(w.load(pathlib.Path(sys.argv[1])), int(sys.argv[2]))"
    return [sys.executable, "-c", end, str(ws.root), "{job}"]


BROKEN = [sys.executable, "-c", "raise SystemExit('host unavailable')"]

# The agent a fake host runs: it creates one entity for the job named in its prompt, over the
# Core's MCP endpoint, finishes the job, and writes what the Core answered to the file given as its argument.
FAKE_AGENT = """
import asyncio, json, os, re, sys
from mcp import Client

prompt, out = sys.argv[1], sys.argv[2]
job = int(re.search(r"job (\\d+)", prompt)[1])

async def main():
    async with Client(os.environ["SECONDCHAIR_TEST_URL"]) as client:
        result = await client.call_tool(
            "create_entity", {"names": ["Ada Fen"], "agent": "fake-runner", "job": job}
        )
        if not result.is_error:
            await client.call_tool("finish_job", {"job": job})
    with open(out, "w") as f:
        json.dump({"error": result.is_error, "text": result.content[0].text}, f)

asyncio.run(main())
"""


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    main(["init", str(tmp_path / "campaign"), "--language", "fr", "--calendar", "absalom"])
    return workspace.load(tmp_path / "campaign")


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The machine configuration file, empty at first."""
    path = tmp_path / "config" / "secondchair" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("port: 0\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return path


def configure(path: Path, hosts: dict[str, list[str]], *entries: tuple[str, str]) -> None:
    """Map tier standard to `(host, model)` entries, in order."""
    runners = {"standard": [{"host": h, "model": m, "effort": "high"} for h, m in entries]}
    path.write_text(yaml.safe_dump({"port": 0, "runners": runners, "hosts": hosts}))


def queue(ws: Workspace) -> int:
    assert main(["jobs", "-w", str(ws.root), "queue", PLAYBOOK, "--input", f"bible={BIBLE}"]) == 0
    return 1


def job(ws: Workspace, job_id: int = 1) -> dict:
    record = jobs.read(ws, job_id)
    jsonschema.validate(record, JOB_SCHEMA)
    return record


def log(ws: Workspace) -> list[dict]:
    entries = [yaml.safe_load(p.read_text()) for p in sorted((ws.root / "action-log").glob("*"))]
    for entry in entries:
        jsonschema.validate(entry, LOG_SCHEMA)
    return entries


def entities(ws: Workspace) -> list[Path]:
    return sorted((ws.root / "canon/entities").glob("*.md"))


def call(ws: Workspace, tool: str, arguments: dict[str, Any]) -> Any:
    async def run() -> Any:
        async with Client(build_server(ws)) as client:
            return await client.call_tool(tool, arguments)

    return asyncio.run(run())


def test_a_queued_job_carries_its_full_contract(ws: Workspace) -> None:
    call(ws, "create_entity", {"names": ["Frère Ezren"], "aliases": ["Ezren"], "agent": "gm"})

    queue(ws)

    record = job(ws)
    assert record["playbook"] == PLAYBOOK
    assert record["inputs"] == {"bible": str(BIBLE)}
    assert record["expected_output"].startswith("One canon entity per named person")
    assert (record["responsibility"], record["moment"], record["tier"]) == (
        "memory",
        "prep",
        "standard",
    )
    assert record["campaign_language"] == "fr"
    assert record["vocabulary"] == ["Ezren", "Frère Ezren"]
    assert (record["status"], record["attempts"]) == ("queued", [])


def test_a_job_may_override_its_playbook_tier_but_not_its_inputs(ws: Workspace) -> None:
    root = str(ws.root)
    assert (
        main(["jobs", "-w", root, "queue", PLAYBOOK, "--input", "bible=x", "--tier", "deep"]) == 0
    )
    assert main(["jobs", "-w", root, "queue", PLAYBOOK, "--input", "notes=x"]) == 1
    assert job(ws)["tier"] == "deep"


@pytest.fixture
def core_url(
    ws: Workspace, config: Path, serving: Serving, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """`serve` running on the workspace; the fake agent reaches it at the yielded URL."""
    with serving(ws.root, dict(os.environ)) as line:
        assert line.startswith("Serving "), line
        url = f"{line.rsplit(' ', 1)[1]}/mcp"
        monkeypatch.setenv("SECONDCHAIR_TEST_URL", url)
        yield url


def fake_agent(tmp_path: Path) -> tuple[list[str], Path]:
    script = tmp_path / "fake_agent.py"
    script.write_text(textwrap.dedent(FAKE_AGENT))
    out = tmp_path / "agent-answer.json"
    return [sys.executable, str(script), "{prompt}", str(out)], out


def test_the_configured_runner_starts_a_queued_job_whose_actions_are_logged(
    ws: Workspace, config: Path, core_url: str, tmp_path: Path
) -> None:
    command, answer = fake_agent(tmp_path)
    configure(config, {"fake": command}, ("fake", "model-a"))
    queue(ws)

    assert main(["jobs", "-w", str(ws.root), "run"]) == 0

    assert json.loads(answer.read_text())["error"] is False
    assert len(entities(ws)) == 1
    [entry] = log(ws)
    assert entry["job"] == 1
    assert entry["runner_configuration"] == {"host": "fake", "model": "model-a", "effort": "high"}
    [attempt] = job(ws)["attempts"]
    assert job(ws)["status"] == "done"
    assert (attempt["manual"], attempt["outcome"]) == (False, "done")


def test_a_manual_cell_refuses_the_actions_of_a_started_job(
    ws: Workspace, config: Path, core_url: str, tmp_path: Path
) -> None:
    table = yaml.safe_load((ws.root / "delegation.yaml").read_text())
    table["prep"]["memory"]["level"] = "manual"
    (ws.root / "delegation.yaml").write_text(yaml.safe_dump(table))
    command, answer = fake_agent(tmp_path)
    configure(config, {"fake": command}, ("fake", "model-a"))
    queue(ws)

    main(["jobs", "-w", str(ws.root), "run"])

    refusal = json.loads(answer.read_text())
    assert refusal["error"] is True and "manual in prep" in refusal["text"]
    assert entities(ws) == []
    assert not (ws.root / "action-log").exists()


def test_every_block_s_playbooks_reach_the_agent_host(
    ws: Workspace, config: Path, tmp_path: Path
) -> None:
    out = tmp_path / "argv.json"
    dump = "import json, sys; json.dump(sys.argv[1:], open(sys.argv[1], 'w'))"
    configure(
        config,
        {"echo": [sys.executable, "-c", dump, str(out), "--plugin-dir={playbooks}"]},
        ("echo", "m"),
    )
    queue(ws)

    # The echo host never calls finish_job, so its attempt fails and the job stays queued.
    assert main(["jobs", "-w", str(ws.root), "run"]) == 1

    dirs = [f"--plugin-dir={d}" for d in runner.playbook_dirs()]
    assert json.loads(out.read_text())[1:] == dirs
    assert len(dirs) == 3  # the Core's, the Foundry connector's (ARC-10) and the PF2e extension's


def test_with_the_first_entry_broken_the_second_is_used_and_both_are_logged(
    ws: Workspace, config: Path
) -> None:
    configure(
        config, {"broken": BROKEN, "ok": finishing(ws)}, ("broken", "model-a"), ("ok", "model-b")
    )
    queue(ws)

    assert main(["jobs", "-w", str(ws.root), "run"]) == 0

    first, second = job(ws)["attempts"]
    assert first["runner_configuration"] == {"host": "broken", "model": "model-a", "effort": "high"}
    assert first["outcome"] == "failed" and "host unavailable" in first["error"]
    assert second["runner_configuration"] == {"host": "ok", "model": "model-b", "effort": "high"}
    assert second["outcome"] == "done"
    assert job(ws)["status"] == "done"


def test_with_every_entry_broken_the_job_stays_queued_and_calls_on_the_gm(
    ws: Workspace, config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(config, {"broken": BROKEN}, ("broken", "model-a"), ("absent-host", "model-b"))
    queue(ws)

    assert main(["jobs", "-w", str(ws.root), "run"]) == 1

    record = job(ws)
    assert record["status"] == "queued"
    assert [a["outcome"] for a in record["attempts"]] == ["failed", "failed"]
    assert "absent-host" in record["attempts"][1]["error"]
    [call_file] = (ws.root / "calls").glob("*.yaml")
    exception = yaml.safe_load(call_file.read_text())
    assert (exception["kind"], exception["deadline"], exception["job"]) == ("exception", "break", 1)
    assert exception["responsibility"] == "memory" and exception["status"] == "open"
    assert "stays queued" in capsys.readouterr().err


def test_a_host_exiting_cleanly_without_finish_job_is_a_failed_attempt(
    ws: Workspace, config: Path
) -> None:
    configure(config, {"ok": OK}, ("ok", "model-a"))
    queue(ws)

    assert main(["jobs", "-w", str(ws.root), "run"]) == 1

    record = job(ws)
    assert record["status"] == "queued"
    [attempt] = record["attempts"]
    assert attempt["outcome"] == "failed" and "finish_job" in attempt["error"]
    assert [yaml.safe_load(p.read_text())["kind"] for p in (ws.root / "calls").glob("*.yaml")] == [
        "exception"
    ]


def test_a_missing_host_binary_is_a_broken_entry(ws: Workspace, config: Path) -> None:
    configure(
        config,
        {"gone": ["/nonexistent/agent-host"], "ok": finishing(ws)},
        ("gone", "m"),
        ("ok", "m"),
    )
    queue(ws)

    assert main(["jobs", "-w", str(ws.root), "run"]) == 0
    assert [a["outcome"] for a in job(ws)["attempts"]] == ["failed", "done"]


def test_without_a_runner_the_gm_starts_the_job_from_their_own_session(
    ws: Workspace, config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    queue(ws)
    assert main(["jobs", "-w", str(ws.root), "run"]) == 0
    assert "waits for you" in capsys.readouterr().out

    assert main(["jobs", "-w", str(ws.root)]) == 0
    listing = capsys.readouterr().out
    assert f"Job 1  queued  {PLAYBOOK}" in listing and "tier standard" in listing

    reported = {"job": 1, "host": "gm-session", "model": "model-x", "effort": "medium"}
    contract = call(ws, "start_job", reported).structured_content
    assert contract["tier"] == "standard" and contract["inputs"] == {"bible": str(BIBLE)}
    call(ws, "create_entity", {"names": ["Ada Fen"], "agent": "gm-session", "job": 1})
    assert call(ws, "finish_job", {"job": 1}).structured_content["status"] == "done"

    [entry] = log(ws)
    assert entry["runner_configuration"] == {
        "host": "gm-session",
        "model": "model-x",
        "effort": "medium",
    }
    [attempt] = job(ws)["attempts"]
    assert (
        attempt["manual"] is True
        and attempt["runner_configuration"] == entry["runner_configuration"]
    )
    main(["jobs", "-w", str(ws.root)])
    assert "No pending job." in capsys.readouterr().out


def test_an_action_for_a_job_not_started_is_refused(ws: Workspace) -> None:
    queue(ws)
    result = call(ws, "create_entity", {"names": ["Ada Fen"], "agent": "a", "job": 1})
    assert result.is_error and "not started" in result.content[0].text
    assert call(ws, "create_entity", {"names": ["X"], "agent": "a", "job": 9}).is_error
    assert entities(ws) == []


def test_a_job_s_actions_follow_the_table_of_the_job_s_moment(ws: Workspace) -> None:
    queue(ws)
    table = yaml.safe_load((ws.root / "delegation.yaml").read_text())
    table["prep"]["memory"]["level"] = "propose"
    (ws.root / "delegation.yaml").write_text(yaml.safe_dump(table))
    call(ws, "start_job", {"job": 1, "host": "h", "model": "m", "effort": "e"})

    result = call(ws, "create_entity", {"names": ["Ada Fen"], "agent": "a", "job": 1})
    assert result.structured_content == {"entry": 1, "status": "pending"}


def world_turn(ws: Workspace) -> int:
    return jobs.queue(
        ws,
        playbook="world-turn",
        inputs={"until": "4720-01-02"},
        expected_output="occurrences",
        responsibility="living_world",
        tier="fast",
    )["id"]


# A legacy client keeps an MCP session; a 2026-07-28 one (auto) has none to bind (ARC-23a).
SESSIONS = pytest.mark.parametrize("mode", ["legacy", "auto"])


@SESSIONS
def test_a_session_that_started_a_job_acts_for_it_whether_or_not_it_passes_job(
    ws: Workspace, mode: Any
) -> None:
    world_turn(ws)
    queue(ws)
    started = {"job": 1, "host": "h", "model": "m", "effort": "e"}

    async def run() -> list[Any]:
        async with Client(build_server(ws), mode=mode) as client:
            return [
                await client.call_tool("start_job", started),
                await client.call_tool("start_job", {**started, "job": 2}),
                await client.call_tool("create_entity", {"names": ["Ada Fen"], "agent": "a"}),
                await client.call_tool("create_entity", {"names": ["X"], "agent": "a", "job": 2}),
                await client.call_tool("finish_job", {"job": 1}),
                await client.call_tool("create_entity", {"names": ["Bo Lin"], "agent": "a"}),
            ]

    _, second, bound, other, _, after = asyncio.run(run())
    if mode == "legacy":
        assert second.is_error and "runs job 1" in second.content[0].text
        assert other.is_error and "runs job 1" in other.content[0].text
        assert not bound.is_error
    else:
        assert not second.is_error and not other.is_error
        assert bound.is_error and "pass `job`" in bound.content[0].text
    assert not after.is_error
    first, last = log(ws)
    assert first["job"] == (1 if mode == "legacy" else 2)
    assert first["runner_configuration"]["host"] == "h"
    assert last["job"] is None


@SESSIONS
def test_a_session_acting_for_a_started_job_stays_bound_to_it(ws: Workspace, mode: Any) -> None:
    """A runner starts the job, not the agent's session: its first action for it binds it."""
    world_turn(ws)
    jobs.start(ws, 1, {"host": "h", "model": "m", "effort": "e"}, manual=False)

    async def run() -> list[Any]:
        async with Client(build_server(ws), mode=mode) as client:
            return [
                await client.call_tool("create_entity", {"names": ["Ada"], "agent": "a", "job": 1}),
                await client.call_tool("create_entity", {"names": ["Bo Lin"], "agent": "a"}),
            ]

    with_job, without = asyncio.run(run())
    assert not with_job.is_error
    if mode == "legacy":
        assert not without.is_error
        assert [e["job"] for e in log(ws)] == [1, 1]
    else:
        assert without.is_error and "pass `job`" in without.content[0].text
        assert [e["job"] for e in log(ws)] == [1]


def test_the_runner_prompt_names_the_job_and_its_contract(ws: Workspace) -> None:
    queue(ws)
    text = runner.prompt(ws, job(ws))
    assert re.search(r"job 1\b", text) and PLAYBOOK in text and "finish_job" in text
    contract = json.loads(text.split("\n", 1)[1])
    assert "attempts" not in contract and contract["campaign_language"] == "fr"


def test_a_retry_prompt_lists_the_actions_earlier_attempts_took(ws: Workspace) -> None:
    """An agent that acted, then exited without finish_job, is retried: the next one is told
    what is already done so it does not redo it (#171)."""
    queue(ws)
    jobs.start(ws, 1, {"host": "h", "model": "m", "effort": "e"}, manual=False)
    call(ws, "create_entity", {"names": ["Ada Fen"], "agent": "a", "job": 1})
    call(ws, "create_entity", {"names": ["Bo Lin"], "agent": "gm"})
    jobs.end(ws, 1, "h exited without calling finish_job")

    text = runner.prompt(ws, job(ws))

    [entry, other] = log(ws)
    assert f"- {entry['id']}: create_entity on {entry['target']}, applied" in text
    assert other["target"] not in text and "do not take them again" in text


def test_a_job_carries_the_vocabulary_of_the_entities_it_is_about(ws: Workspace) -> None:
    for names, aliases in ((["Frère Ezren"], ["Ezren"]), (["Ada Fen"], [])):
        call(ws, "create_entity", {"names": names, "aliases": aliases, "agent": "gm"})
    [ezren] = [e["id"] for e in index.search_entities(ws, "Ezren")]
    root, bible = str(ws.root), f"bible={BIBLE}"

    assert main(["jobs", "-w", root, "queue", PLAYBOOK, "--input", bible, "--entity", ezren]) == 0
    assert main(["jobs", "-w", root, "queue", PLAYBOOK, "--input", bible]) == 0
    assert main(["jobs", "-w", root, "queue", PLAYBOOK, "--input", bible, "--entity", "e-x"]) == 1

    assert job(ws, 1)["vocabulary"] == ["Ezren", "Frère Ezren"]
    assert job(ws, 2)["vocabulary"] == ["Ada Fen", "Ezren", "Frère Ezren"]


# Playbooks (ARC-21, ARC-25, PKG-19)


def test_every_playbook_is_an_agent_skill_with_a_tier_and_a_responsibility() -> None:
    skills = runner.skills()
    assert sorted(s.name for s in skills) == [
        "answer-probes",
        "calibrate-encounters",
        "diagnose-frictions",
        "prepare-a-session",
        "propose-consequences",
        "propose-narrative-direction",
        "quick-help",
        "realise-a-scene",
        PLAYBOOK,
        "settle-an-unless",
        "world-turn",
        "wrap-a-session",
    ]
    for skill in skills:
        front = yaml.safe_load((skill / "SKILL.md").read_text().split("---", 2)[1])
        assert front["name"] == skill.name and len(front["description"]) <= 1024
        meta = runner.playbook(skill.name)
        assert meta["tier"] in jobs.TIERS and meta["responsibility"] in RESPONSIBILITIES
        assert "campaign language" in (skill / "SKILL.md").read_text()
    names = []
    for playbooks in runner.playbook_dirs():
        plugin = json.loads((playbooks / ".claude-plugin/plugin.json").read_text())
        marketplace = json.loads((playbooks / ".claude-plugin/marketplace.json").read_text())
        assert marketplace["name"] == marketplace["plugins"][0]["name"] == plugin["name"]
        names.append(plugin["name"])
    assert names == ["secondchair", "secondchair-foundry", "secondchair-pf2e"]


# Model names live only in the GM's machine configuration (ARC-25): checked in CI.
MODEL_NAME = re.compile(
    r"\b(opus|sonnet|haiku|claude-[0-9a-z]|gpt-?[0-9]|o[1-9](-mini|-pro)?|codex-mini|gemini|"
    r"llama|mistral|mixtral|qwen|deepseek|grok)\b",
    re.IGNORECASE,
)


def test_no_model_name_appears_in_the_core_or_in_a_playbook() -> None:
    files = [
        *(ROOT / "src/secondchair/core").rglob("*.py"),
        *(p for d in runner.playbook_dirs() for p in d.rglob("*") if p.is_file()),
    ]
    found = {
        str(p.relative_to(ROOT)): MODEL_NAME.findall(p.read_text())
        for p in files
        if MODEL_NAME.search(p.read_text())
    }
    assert found == {}


def test_the_model_name_check_catches_model_names() -> None:
    for text in ("model: sonnet", "use gpt-5", "o3-mini", "claude-opus-4"):
        assert MODEL_NAME.search(text), text
    assert not MODEL_NAME.search("tier: standard, host: claude, effort: high")
