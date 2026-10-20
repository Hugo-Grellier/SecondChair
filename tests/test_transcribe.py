import hashlib
import json
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml

from secondchair.cli import main
from secondchair.core import workspace
from secondchair.core.workspace import Workspace

SCHEMA = json.loads(
    (Path(__file__).parents[1] / "docs/contracts/transcript.schema.json").read_text()
)
SPEAKERS = {
    "gm_hugo": {"player": "Hugo", "gm": True},
    "alice_42": {"player": "Alice", "pc": "Valeros"},
}

# A fake WhisperX: the "audio" file holds the segments it should hear, as JSON. It writes them
# where WhisperX would (`<out_dir>/<audio stem>.json`) and logs its argv and whether it saw the
# Hugging Face token in its environment.
FAKE_ENGINE = """
import json, os, sys
from pathlib import Path
audio, out_dir, hotwords, log = sys.argv[1:5]
with open(log, "a") as f:
    f.write(json.dumps({"argv": sys.argv, "hf_token": os.environ.get("HF_TOKEN")}) + "\\n")
segments = json.loads(Path(audio).read_text())
(Path(out_dir) / (Path(audio).stem + ".json")).write_text(
    json.dumps({"segments": segments, "language": "fr"})
)
"""


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    main(["init", str(tmp_path / "campaign"), "--language", "fr", "--calendar", "absalom"])
    root = tmp_path / "campaign"
    (root / "speakers.yaml").write_text(yaml.safe_dump(SPEAKERS))
    (root / "moment.yaml").write_text("moment: between-sessions\nseq: 3\nsession: 1\n")
    (root / "canon/entities").mkdir(parents=True)
    (root / "canon/entities/e-00000001.md").write_text(
        "---\nid: e-00000001\nnames: [Frère Ezren]\naliases: [Ezren]\n"
        "official_reference: null\n---\nUn prêtre.\n"
    )
    engine = tmp_path / "engine.py"
    engine.write_text(FAKE_ENGINE)
    config = tmp_path / "config/secondchair"
    config.mkdir(parents=True)
    log = tmp_path / "engine.log"
    template = [sys.executable, str(engine), "{audio}", "{out_dir}", "{hotwords}", str(log)]
    (config / "config.yaml").write_text(yaml.safe_dump({"transcription": template}))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HF_TOKEN", "hf_secret")
    return workspace.load(root)


def audio(path: Path, *segments: tuple[float, float, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{"start": s, "end": e, "text": t} for s, e, t in segments]))
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def tracks(tmp_path: Path) -> list[Path]:
    rec = tmp_path / "recordings"
    return [
        audio(rec / "1-gm_hugo.flac", (0.0, 2.5, " Vous entrez."), (6.0, 7.0, "Ezren sourit.")),
        audio(rec / "2-alice_42.flac", (3.0, 5.5, " Je salue Ezren. "), (8.0, 8.5, " ")),
    ]


def transcribe(ws: Workspace, *args: str) -> int:
    return main(["transcribe", "-w", str(ws.root), "--session", "1", *args])


def test_a_multi_track_session_yields_a_transcript_timestamped_per_speaker(
    ws: Workspace, tracks: list[Path], tmp_path: Path
) -> None:
    out = tmp_path / "recordings/session-1.jsonl"
    assert transcribe(ws, f"gm_hugo={tracks[0]}", f"alice_42={tracks[1]}") == 0

    segments = [json.loads(line) for line in out.read_text().splitlines()]
    for segment in segments:
        jsonschema.validate(segment, SCHEMA)
    assert segments == [
        {"speaker": "gm_hugo", "start": 0.0, "end": 2.5, "text": "Vous entrez."},
        {"speaker": "alice_42", "start": 3.0, "end": 5.5, "text": "Je salue Ezren."},
        {"speaker": "gm_hugo", "start": 6.0, "end": 7.0, "text": "Ezren sourit."},
    ]
    runs = [json.loads(line) for line in (tmp_path / "engine.log").read_text().splitlines()]
    assert [r["argv"][3] for r in runs] == ["Ezren, Frère Ezren"] * 2  # the vocabulary


def test_transcripts_and_audio_stay_outside_the_workspace_referenced_by_id_and_hash(
    ws: Workspace, tracks: list[Path], tmp_path: Path
) -> None:
    out = tmp_path / "elsewhere/s1.jsonl"
    transcribe(ws, f"gm_hugo={tracks[0]}", f"alice_42={tracks[1]}", "--out", str(out))

    refs = {p.stem: yaml.safe_load(p.read_text()) for p in (ws.root / "sources").glob("*.yaml")}
    by_hash = {r["sha256"]: r for r in refs.values()}
    assert set(by_hash) == {sha(tracks[0]), sha(tracks[1]), sha(out)}
    transcript = by_hash[sha(out)]
    assert transcript["kind"] == "transcript"
    assert transcript["session"] == 1
    assert sorted(transcript["from"]) == sorted(by_hash[sha(t)]["id"] for t in tracks)
    assert by_hash[sha(tracks[1])] | {"id": None} == {
        "id": None,
        "kind": "audio",
        "sha256": sha(tracks[1]),
        "session": 1,
        "speaker": "alice_42",
    }
    assert all(r["id"] == stem for stem, r in refs.items())
    # Their locations are machine configuration, never the workspace's.
    locations = yaml.safe_load((tmp_path / "config/secondchair/sources.yaml").read_text())
    assert locations[transcript["id"]] == str(out.resolve())
    text = "".join(
        p.read_text(errors="ignore")
        for p in ws.root.rglob("*")
        if p.is_file() and ".git" not in p.parts
    )
    assert "Je salue" not in text and str(tmp_path / "recordings") not in text


@pytest.mark.parametrize("inside", ["out", "audio"])
def test_a_transcript_or_audio_inside_the_workspace_is_refused(
    ws: Workspace, tracks: list[Path], inside: str, capsys: pytest.CaptureFixture[str]
) -> None:
    args = [f"gm_hugo={tracks[0]}", f"alice_42={tracks[1]}"]
    if inside == "out":
        args += ["--out", str(ws.root / "t.jsonl")]
    else:
        args[1] = f"alice_42={audio(ws.root / 'alice.flac', (0, 1, 'x'))}"
    assert transcribe(ws, *args) == 1
    assert "outside the campaign workspace" in capsys.readouterr().err
    assert not (ws.root / "sources").exists()


def test_a_single_track_input_is_refused(
    ws: Workspace, tracks: list[Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert transcribe(ws, f"gm_hugo={tracks[0]}") == 1
    assert "per-speaker tracks" in capsys.readouterr().err


def test_a_track_must_name_a_speaker_of_the_speaker_table(
    ws: Workspace, tracks: list[Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert transcribe(ws, f"gm_hugo={tracks[0]}", f"bob={tracks[1]}") == 1
    assert "bob" in capsys.readouterr().err


def test_the_hugging_face_token_comes_from_the_environment_only(
    ws: Workspace, tracks: list[Path], tmp_path: Path
) -> None:
    transcribe(ws, f"gm_hugo={tracks[0]}", f"alice_42={tracks[1]}")
    runs = [json.loads(line) for line in (tmp_path / "engine.log").read_text().splitlines()]
    assert all(r["hf_token"] == "hf_secret" for r in runs)
    assert not any("hf_secret" in a for r in runs for a in r["argv"])
    written = [p for p in tmp_path.rglob("*") if p.is_file() and p.name != "engine.log"]
    assert not any("hf_secret" in p.read_text(errors="ignore") for p in written)


def test_a_failing_engine_is_reported(
    ws: Workspace, tracks: list[Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config/secondchair/config.yaml"
    config.write_text(yaml.safe_dump({"transcription": [sys.executable, "-c", "exit(3)"]}))
    assert transcribe(ws, f"gm_hugo={tracks[0]}", f"alice_42={tracks[1]}") == 1
    assert "transcription engine" in capsys.readouterr().err
    assert not (ws.root / "sources").exists()


def write_lines(path: Path, *segments: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(s) + "\n" for s in segments))
    return path


def test_any_engines_attributed_transcript_is_accepted(ws: Workspace, tmp_path: Path) -> None:
    other = write_lines(
        tmp_path / "other/s1.jsonl",
        {"speaker": "gm_hugo", "start": 0, "end": 1.5, "text": "Bonsoir."},
        {"speaker": "alice_42", "start": 2, "end": 3, "text": "Salut."},
    )
    other.write_text(other.read_text() + "\n")  # a trailing blank line is fine
    assert transcribe(ws, "--from", str(other)) == 0
    [ref] = [yaml.safe_load(p.read_text()) for p in (ws.root / "sources").glob("*.yaml")]
    assert ref == {
        "id": ref["id"],
        "kind": "transcript",
        "sha256": sha(other),
        "session": 1,
        "from": [],
    }


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (['{"speaker": "gm_hugo", "start": 0, "end": 1}'], "line 1"),
        (['{"speaker": "bob", "start": 0, "end": 1, "text": "x"}'], "bob"),
        (["not json"], "line 1"),
        (
            ['{"speaker": "gm_hugo", "start": 0, "end": 1, "text": "x"}'] * 2,
            "per-speaker tracks",
        ),
    ],
)
def test_a_transcript_out_of_format_or_single_speaker_is_refused(
    ws: Workspace,
    tmp_path: Path,
    lines: list[str],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text("\n".join(lines) + "\n")
    assert transcribe(ws, "--from", str(path)) == 1
    assert message in capsys.readouterr().err


def test_a_session_not_yet_played_is_refused(
    ws: Workspace, tracks: list[Path], capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["transcribe", "-w", str(ws.root), "--session", "2"]
    assert main([*args, f"gm_hugo={tracks[0]}", f"alice_42={tracks[1]}"]) == 1
    assert "session 2" in capsys.readouterr().err


@pytest.mark.parametrize(
    "table",
    [
        {"a": {"player": "A"}, "b": {"player": "B"}},  # no GM track
        {"a": {"player": "A", "gm": True}, "b": {"player": "B", "gm": True}},
        {"a": {"player": "A", "gm": True}, "b": {"pc": "X"}},  # no player
        ["a", "b"],
        {123456789012345678: {"player": "A", "gm": True}, "b": {"player": "B"}},  # unquoted
    ],
)
def test_check_reports_an_invalid_speaker_table(
    ws: Workspace, table: object, capsys: pytest.CaptureFixture[str]
) -> None:
    (ws.root / "speakers.yaml").write_text(yaml.safe_dump(table))
    assert main(["check", "-w", str(ws.root)]) == 1
    assert "speakers.yaml" in capsys.readouterr().err


@pytest.mark.parametrize(
    "engine",
    [
        "print('no output')",
        "import sys, json, pathlib; pathlib.Path(sys.argv[2], 'a.json').write_text("
        "json.dumps({{'segments': [{{'start': None, 'end': 1, 'text': 'x'}}]}}))",
        "import sys, json, pathlib; pathlib.Path(sys.argv[2], 'a.json').write_text("
        "json.dumps({{'segments': [{{'start': 2, 'end': 1, 'text': 'x'}}]}}))",
    ],
)  # braces doubled: the command template is a format string
def test_malformed_engine_output_is_reported(
    ws: Workspace,
    tracks: list[Path],
    tmp_path: Path,
    engine: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "config/secondchair/config.yaml"
    config.write_text(
        yaml.safe_dump({"transcription": [sys.executable, "-c", engine, "{audio}", "{out_dir}"]})
    )
    assert transcribe(ws, f"gm_hugo={tracks[0]}", f"alice_42={tracks[1]}") == 1
    assert "transcription engine" in capsys.readouterr().err
    assert not (ws.root / "sources").exists()


def test_an_existing_transcript_or_a_shared_track_is_refused(
    ws: Workspace, tracks: list[Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert transcribe(ws, f"gm_hugo={tracks[0]}", f"alice_42={tracks[0]}") == 1
    assert "their own track" in capsys.readouterr().err
    assert (
        transcribe(ws, f"gm_hugo={tracks[0]}", f"alice_42={tracks[1]}", "--out", str(tracks[0]))
        == 1
    )
    assert "already exists" in capsys.readouterr().err


def test_check_reports_an_invalid_source_reference(
    ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    (ws.root / "sources").mkdir()
    (ws.root / "sources/s-1234abcd.yaml").write_text("id: s-1234abcd\nkind: video\n")
    assert main(["check", "-w", str(ws.root)]) == 1
    assert "s-1234abcd.yaml" in capsys.readouterr().err
