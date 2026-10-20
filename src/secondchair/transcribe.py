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
    if not all(isinstance(user, str) for user in table):
        raise WorkspaceError(f"{path}: quote each Discord user so it is a string.")
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
            ref = _read_yaml(path)
        except WorkspaceError as e:
            errors.append(str(e))
            continue
        digest = str(ref.get("sha256", ""))
        if not (
            ref.get("kind") in ("audio", "transcript")
            and len(digest) == 64
            and set(digest) <= set("0123456789abcdef")
            and ref.get("id") == path.stem == f"s-{digest[:8]}"
        ):
            errors.append(f"{path}: not a Source reference {{id, kind, sha256, session}}.")
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
    if len(set(tracks.values())) != len(tracks):
        raise TranscriptionError("Each speaker needs their own track.")
    out = _outside(ws, out or next(iter(tracks.values())).parent / f"session-{session}.jsonl")
    if out.exists():
        raise TranscriptionError(f"{out} already exists: choose another --out.")
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
        if not line.strip():
            continue
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
    fields = {"audio": str(audio), "hotwords": hotwords, "language": language}
    with tempfile.TemporaryDirectory() as out_dir:
        try:
            command = [a.format(**fields, out_dir=out_dir) for a in template or WHISPERX]
        except (KeyError, ValueError, IndexError) as e:
            raise TranscriptionError(
                f"The transcription command has an unknown placeholder {e}; use "
                "{audio}, {out_dir}, {language}, {hotwords}, and double other braces."
            ) from e
        try:  # the environment, Hugging Face token included, is inherited as is
            subprocess.run(command, check=True, capture_output=True, text=True)
            [result] = Path(out_dir).glob("*.json")
            segments = [
                {"start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()}
                for s in json.loads(result.read_text())["segments"]
                if s["text"].strip()
            ]
        except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError) as e:
            detail = getattr(e, "stderr", None) or e
            raise TranscriptionError(f"The transcription engine failed on {audio}: {detail}") from e
    if bad := [s for s in segments if not _segment({"speaker": "-", **s})]:
        raise TranscriptionError(f"The transcription engine gave an invalid segment: {bad[0]}")
    return segments


def _reference(ws: Workspace, path: Path, record: dict) -> str:
    """Reference a Source by id and hash in the workspace (PKG-12), and remember where it is in
    the machine configuration."""
    with path.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
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
    # ponytail: unlocked read-modify-write; two concurrent transcribe runs on one machine can
    # drop a location (the workspace reference stays). Lock it if that ever happens.
    try:
        locations = yaml.safe_load(locations_path.read_text()) if locations_path.exists() else None
    except yaml.YAMLError as e:
        raise TranscriptionError(f"{locations_path} is not valid YAML: {e}") from e
    if not isinstance(locations, dict | None):
        raise TranscriptionError(f"{locations_path} must map Source ids to paths.")
    _write(locations_path, yaml.safe_dump({**(locations or {}), source_id: str(path)}))
    return source_id
