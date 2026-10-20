"""Transcription (CAP-01, CAP-02, CAP-15, PKG-12): a CLI step outside the Core's MCP server.

Each speaker's track goes through the transcription engine (WhisperX by default) with the
campaign vocabulary as hotwords; the segments are merged into one transcript in the transcript
format (docs/contracts/transcript.schema.json). Audio and transcripts are Sources: they stay
outside the workspace, which only records their id and hash in `sources/`; their locations are
machine configuration. The Hugging Face token WhisperX may need is left in the engine's
environment (`HF_TOKEN`), never read, passed or stored here (PKG-14).
"""

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import TypeIs

import yaml

from secondchair.core import canon, machine
from secondchair.core.delegation import MOMENT_FILE, _read_yaml, _write, locked
from secondchair.core.workspace import Workspace, WorkspaceError

SPEAKERS_FILE = "speakers.yaml"
SOURCES_DIR = "sources"
LOCATIONS_FILE = "sources.yaml"  # in the machine configuration
# `{audio}`, `{out_dir}`, `{language}` and `{hotwords}` are filled in; the engine writes
# `<out_dir>/<audio stem>.json` with WhisperX's `segments`. The machine configuration's
# `transcription` overrides it (e.g. to add `--model large-v3`).
WHISPERX = [
    "whisperx",
    "{audio}",
    "--output_dir",
    "{out_dir}",
    "--output_format",
    "json",
    "--language",
    "{language}",
    "--hotwords",
    "{hotwords}",
]
SEGMENT_KEYS = {"speaker", "start", "end", "text"}


class TranscriptionError(Exception):
    """Input the transcription step refuses, with a message for the GM."""


def speakers(ws: Workspace) -> dict[str, dict]:
    """The speaker table (CAP-02): Discord user -> {player, pc, gm}, exactly one GM track."""
    path = ws.root / SPEAKERS_FILE
    table = _read_yaml(path)
    if not all(
        isinstance(row, dict)
        and isinstance(row.get("player"), str)
        and isinstance(row.get("pc", ""), str | None)
        and isinstance(row.get("gm", False), bool)
        and set(row) <= {"player", "pc", "gm"}
        for row in table.values()
    ):
        raise WorkspaceError(f"{path}: each Discord user maps to {{player, pc, gm}}.")
    if sum(row.get("gm", False) for row in table.values()) != 1:
        raise WorkspaceError(f"{path}: exactly one speaker must be the GM's track (gm: true).")
    return table


def check(ws: Workspace) -> list[str]:
    """One message per invalid speaker table or Source reference."""
    errors = []
    if (ws.root / SPEAKERS_FILE).exists():
        try:
            speakers(ws)
        except WorkspaceError as e:
            errors.append(str(e))
    for path in sorted((ws.root / SOURCES_DIR).glob("*.yaml")):
        try:
            _read_yaml(path)
        except WorkspaceError as e:
            errors.append(str(e))
    return errors


def transcribe(
    ws: Workspace,
    session: int,
    tracks: dict[str, Path],
    out: Path | None,
    language: str | None,
    template: list[str] | None,
) -> Path:
    """Transcribe one session's per-speaker tracks into `out` (default: next to the first track)
    and reference them all in the workspace."""
    _session(ws, session)
    _attributed(ws, set(tracks))
    tracks = {speaker: _outside(ws, path) for speaker, path in tracks.items()}
    out = _outside(ws, out or next(iter(tracks.values())).parent / f"session-{session}.jsonl")
    hotwords = ", ".join(canon.vocabulary(ws))
    language = language or ws.campaign_language.split("-")[0]
    segments = []
    for speaker, audio in tracks.items():
        segments += [
            {"speaker": speaker, **s} for s in _engine(template, audio, hotwords, language)
        ]
    segments.sort(key=lambda s: (s["start"], s["speaker"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    _write(out, "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in segments))
    audio_ids = [
        _reference(ws, path, {"kind": "audio", "session": session, "speaker": speaker})
        for speaker, path in tracks.items()
    ]
    _reference(ws, out, {"kind": "transcript", "session": session, "from": audio_ids})
    return out


def register(ws: Workspace, session: int, path: Path) -> str:
    """Reference a transcript any engine produced in the transcript format, already attributed
    to the speaker table's speakers; its id."""
    _session(ws, session)
    path = _outside(ws, path)
    found = set()
    for n, line in enumerate(path.read_text().splitlines(), 1):
        try:
            segment = json.loads(line)
        except ValueError:
            segment = None
        if not _segment(segment):
            raise TranscriptionError(f"{path} line {n}: not a transcript segment.")
        found.add(segment["speaker"])
    _attributed(ws, found)
    return _reference(ws, path, {"kind": "transcript", "session": session, "from": []})


def _segment(s: object) -> TypeIs[dict]:
    """A transcript segment (docs/contracts/transcript.schema.json)."""
    return (
        isinstance(s, dict)
        and set(s) == SEGMENT_KEYS
        and all(isinstance(s[k], str) and s[k] for k in ("speaker", "text"))
        and all(type(s[k]) in (int, float) and s[k] >= 0 for k in ("start", "end"))
        and s["start"] <= s["end"]
    )


def _session(ws: Workspace, session: int) -> None:
    played = _read_yaml(ws.root / MOMENT_FILE).get("session", 0)
    if not 1 <= session <= played:
        raise TranscriptionError(f"No session {session}: sessions 1 to {played} were played.")


def _attributed(ws: Workspace, found: set[str]) -> None:
    """Per-speaker input only (CAP-02): two speakers at least, all in the speaker table."""
    if unknown := sorted(found - set(speakers(ws))):
        raise TranscriptionError(f"{', '.join(unknown)}: not in {ws.root / SPEAKERS_FILE}.")
    if len(found) < 2:
        raise TranscriptionError(
            "Single-track input is out of v4: give per-speaker tracks or a transcript "
            "already attributed to each speaker."
        )


def _outside(ws: Workspace, path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_relative_to(ws.root.resolve()):
        raise TranscriptionError(
            f"{path}: audio and transcripts are Sources and stay outside the campaign workspace."
        )
    return path


def _engine(template: list[str] | None, audio: Path, hotwords: str, language: str) -> list[dict]:
    """The engine's segments for one track: {start, end, text}, empty ones dropped."""
    if not audio.is_file():
        raise TranscriptionError(f"{audio} is not a file.")
    with tempfile.TemporaryDirectory() as out_dir:
        fields = {"audio": str(audio), "out_dir": out_dir, "hotwords": hotwords}
        command = [a.format(**fields, language=language) for a in template or WHISPERX]
        try:  # the environment, Hugging Face token included, is inherited as is
            subprocess.run(command, check=True, capture_output=True, text=True)
            [result] = Path(out_dir).glob("*.json")
            raw = json.loads(result.read_text())["segments"]
        except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as e:
            detail = getattr(e, "stderr", None) or e
            raise TranscriptionError(f"The transcription engine failed on {audio}: {detail}") from e
    return [
        {"start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()}
        for s in raw
        if s["text"].strip()
    ]


def _reference(ws: Workspace, path: Path, record: dict) -> str:
    """Reference a Source by id and hash in the workspace (PKG-12), and remember where it is in
    the machine configuration."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    source_id = f"s-{digest[:8]}"
    with locked(ws):
        (ws.root / SOURCES_DIR).mkdir(exist_ok=True)
        text = yaml.safe_dump(
            {"id": source_id, "kind": record.pop("kind"), "sha256": digest, **record},
            sort_keys=False,
            allow_unicode=True,
        )
        _write(ws.root / SOURCES_DIR / f"{source_id}.yaml", text)
    locations_path = machine.config_dir() / LOCATIONS_FILE
    locations_path.parent.mkdir(parents=True, exist_ok=True)
    locations = yaml.safe_load(locations_path.read_text()) if locations_path.exists() else None
    _write(locations_path, yaml.safe_dump({**(locations or {}), source_id: str(path)}))
    return source_id
