"""Reference library: local text indexes, explicit permissions, model-safe cited retrieval.

Source paths and permissions are machine configuration; excerpts stay in machine data.
The workspace carries portable metadata only. Embeddings run through the GM's
local Ollama server.
"""

import base64
import hashlib
import json
import math
import re
import struct
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from secondchair.core import machine
from secondchair.core.delegation import locked
from secondchair.core.tools import Tool
from secondchair.core.workspace import Workspace, WorkspaceError

REFERENCE_FILE = "library.yaml"
EXTENSIONS = {".pdf", ".md", ".txt"}
DEFAULT_EMBEDDING_MODEL = "qwen3-embedding:0.6b"
OLLAMA_EMBED_URL = "http://127.0.0.1:11434/api/embed"


def _key(ws: Workspace) -> str:
    return hashlib.sha256(str(ws.root.resolve()).encode()).hexdigest()[:24]


def _settings(ws: Workspace) -> Path:
    return machine.config_dir() / "library" / f"{_key(ws)}.json"


def _cache(ws: Workspace, source_id: str) -> Path:
    return machine.data_dir() / "library" / _key(ws) / f"{source_id}.json"


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("expected an object")
        return data
    except ValueError as e:
        raise WorkspaceError(f"Invalid library data {path}: {e}") from e


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def _references(ws: Workspace) -> dict:
    path = ws.root / REFERENCE_FILE
    if not path.exists():
        return {}
    try:
        refs = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise WorkspaceError(f"Invalid library references {path}: {e}") from e
    if not isinstance(refs, dict) or not all(
        isinstance(k, str) and re.fullmatch(r"r-[a-f0-9]{24}", k) and isinstance(v, str)
        for k, v in refs.items()
    ):
        raise WorkspaceError(f"{path} must map source ids to filenames.")
    return refs


def register(ws: Workspace, path: Path) -> list[str]:
    """Register a file or snapshot of a directory's supported files; grant no permissions."""
    path = path.expanduser().resolve()
    root = ws.root.resolve()
    if path.is_relative_to(root) or root.is_relative_to(path):
        raise WorkspaceError("Reference sources must stay outside the campaign workspace.")
    if not path.exists():
        raise WorkspaceError(f"Source does not exist: {path}.")
    files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
    files = [p for p in files if p.suffix.lower() in EXTENSIONS]
    if not files:
        raise WorkspaceError("No supported sources (.pdf, .md, .txt).")
    with locked(ws):
        settings, refs = _read(_settings(ws)), _references(ws)
        ids = []
        for file in files:
            resolved = file.resolve()
            if resolved.is_relative_to(root):
                raise WorkspaceError(f"Source points into the workspace: {file}.")
            source_id = "r-" + hashlib.sha256(str(resolved).encode()).hexdigest()[:24]
            name = str(file.relative_to(path)) if path.is_dir() else file.name
            refs.setdefault(source_id, name)
            settings.setdefault(source_id, {"path": str(resolved), "index": False, "model": False})
            ids.append(source_id)
        _write(_settings(ws), settings)
        (ws.root / REFERENCE_FILE).write_text(yaml.safe_dump(refs, allow_unicode=True))
    return list(dict.fromkeys(ids))


def _source(ws: Workspace, source_id: str) -> tuple[str, dict]:
    refs, settings = _references(ws), _read(_settings(ws))
    if source_id not in refs or source_id not in settings:
        raise WorkspaceError(f"Source {source_id!r} is not registered on this machine.")
    return refs[source_id], settings[source_id]


def permit(
    ws: Workspace,
    source_id: str,
    indexing: bool | None,
    model: bool | None,
    authenticated: bool,
) -> None:
    if not authenticated:
        raise WorkspaceError("Changing source permissions needs an interactive GM terminal.")
    with locked(ws):
        _source(ws, source_id)
        settings = _read(_settings(ws))
        for name, value in (("index", indexing), ("model", model)):
            if value is not None:
                settings[source_id][name] = value
        _write(_settings(ws), settings)


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _embedding_model() -> str:
    path, config = machine.config()
    model = config.get("semantic_model", DEFAULT_EMBEDDING_MODEL)
    if not isinstance(model, str) or not model.strip():
        raise WorkspaceError(f"{path}: semantic_model must be a non-empty Ollama model name.")
    return model.strip()


def _embed(texts: list[str], model: str) -> list[list[float]]:
    """Create embeddings on the GM's loopback Ollama server; source text never leaves it."""
    embeddings = []
    for start in range(0, len(texts), 32):
        request = urllib.request.Request(
            OLLAMA_EMBED_URL,
            data=json.dumps({"model": model, "input": texts[start : start + 32]}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                found = json.loads(response.read())["embeddings"]
        except urllib.error.HTTPError as e:
            raise WorkspaceError(
                f"Ollama could not embed text with {model!r}; check the model is installed. "
                f"Install it with `ollama pull {model}`."
            ) from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise WorkspaceError(
                "Semantic search needs local Ollama running at 127.0.0.1:11434."
            ) from e
        except (KeyError, ValueError, TypeError) as e:
            raise WorkspaceError("Ollama returned an invalid embedding response.") from e
        if not isinstance(found, list) or len(found) != min(32, len(texts) - start):
            raise WorkspaceError("Ollama returned an incomplete set of embeddings.")
        for vector in found:
            if (
                not isinstance(vector, list)
                or not vector
                or not all(
                    isinstance(value, (int, float)) and math.isfinite(value) for value in vector
                )
            ):
                raise WorkspaceError("Ollama returned an invalid embedding vector.")
            norm = math.sqrt(sum(value * value for value in vector))
            if not norm:
                raise WorkspaceError("Ollama returned an empty embedding vector.")
            embeddings.append([value / norm for value in vector])
    return embeddings


def _pack_vectors(vectors: list[list[float]]) -> tuple[str, int]:
    dimensions = len(vectors[0])
    if any(len(vector) != dimensions for vector in vectors):
        raise WorkspaceError("Ollama returned embeddings with inconsistent dimensions.")
    packed = struct.pack(
        f"<{len(vectors) * dimensions}f", *(v for vector in vectors for v in vector)
    )
    return base64.b64encode(packed).decode("ascii"), dimensions


def _unpack_vectors(encoded: str, count: int, dimensions: int) -> list[tuple[float, ...]]:
    try:
        packed = base64.b64decode(encoded, validate=True)
        values = struct.unpack(f"<{count * dimensions}f", packed)
        return [tuple(values[i * dimensions : (i + 1) * dimensions]) for i in range(count)]
    except (ValueError, struct.error) as e:
        raise WorkspaceError("The semantic index is corrupt; reindex the source.") from e


def listing(ws: Workspace) -> list[dict[str, Any]]:
    """Metadata only, including permission and index freshness. Never return source paths."""
    settings = _read(_settings(ws))
    model = _embedding_model()
    result = []
    for source_id, name in _references(ws).items():
        entry = settings.get(source_id)
        status = "unavailable"
        if entry and Path(entry["path"]).is_file():
            cache = _read(_cache(ws, source_id))
            status = (
                "unindexed"
                if not cache
                else "ready"
                if cache["sha256"] == _digest(Path(entry["path"])) and cache.get("model") == model
                else "model-changed"
                if cache["sha256"] == _digest(Path(entry["path"]))
                else "changed"
            )
        result.append(
            {
                "id": source_id,
                "filename": name,
                "status": status,
                "index": bool(entry and entry["index"]),
                "model": bool(entry and entry["model"]),
            }
        )
    return result


def _passages(path: Path) -> list[dict]:
    if path.suffix.lower() == ".pdf":
        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
        except FileNotFoundError as e:
            raise WorkspaceError("PDF indexing needs Poppler's pdftotext installed locally.") from e
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            raise WorkspaceError(f"Could not extract PDF text: {path.name}.") from e
        pages = proc.stdout.split("\f")
        while pages and not pages[-1].strip():
            pages.pop()
        if not pages:
            try:
                info = subprocess.run(
                    ["pdfinfo", str(path)], capture_output=True, text=True, timeout=30, check=True
                )
            except FileNotFoundError as e:
                raise WorkspaceError(
                    "Scanned PDF indexing needs Poppler's pdfinfo installed locally."
                ) from e
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                raise WorkspaceError(f"Could not count pages in PDF: {path.name}.") from e
            page_count = re.search(r"^Pages:\s+(\d+)\s*$", info.stdout, re.MULTILINE)
            if not page_count:
                raise WorkspaceError(f"Could not count pages in PDF: {path.name}.")
            pages = [""] * int(page_count.group(1))
        languages = machine.config()[1].get("ocr_languages", "eng+fra")
        if not isinstance(languages, str) or not re.fullmatch(r"[A-Za-z0-9_+]+", languages):
            raise WorkspaceError("Machine config ocr_languages must be a Tesseract language list.")
        for page, text in enumerate(pages, 1):
            if not text.strip():
                pages[page - 1] = _ocr_page(path, page, languages)
    else:
        try:
            pages = [path.read_text(encoding="utf-8")]
        except UnicodeError as e:
            raise WorkspaceError(f"Source is not UTF-8 text: {path.name}.") from e
    passages = []
    for page, text in enumerate(pages, 1):
        lines = text.splitlines()
        for start in range(0, len(lines), 12):
            excerpt = "\n".join(lines[start : start + 12]).strip()
            if excerpt:
                location = f"page {page}" if path.suffix.lower() == ".pdf" else f"line {start + 1}"
                # Bound model excerpts even when extracted text has very long lines.
                for offset in range(0, len(excerpt), 1800):
                    passages.append({"location": location, "text": excerpt[offset : offset + 1800]})
    return passages


def _ocr_page(path: Path, page: int, languages: str) -> str:
    """Rasterize and OCR one text-empty PDF page, keeping it inside a temporary directory."""
    try:
        with tempfile.TemporaryDirectory(prefix="secondchair-ocr-") as directory:
            prefix = Path(directory) / "page"
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-r",
                    "200",
                    "-singlefile",
                    "-png",
                    str(path),
                    str(prefix),
                ],
                capture_output=True,
                timeout=120,
                check=True,
            )
            result = subprocess.run(
                ["tesseract", f"{prefix}.png", "stdout", "-l", languages],
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            return result.stdout
    except FileNotFoundError as e:
        tool = "Poppler's pdftoppm" if e.filename == "pdftoppm" else "Tesseract"
        raise WorkspaceError(f"Scanned PDF pages need {tool} installed locally.") from e
    except subprocess.CalledProcessError as e:
        raise WorkspaceError(
            f"OCR failed on {path.name} page {page}; check the installed language data "
            f"for {languages!r}."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise WorkspaceError(f"OCR timed out on {path.name} page {page}.") from e


def build_index(
    ws: Workspace, source_id: str, replace_changed: bool = False, authenticated: bool = False
) -> None:
    with locked(ws):
        _, entry = _source(ws, source_id)
        if not entry["index"]:
            raise WorkspaceError("Local indexing permission has not been granted.")
        path = Path(entry["path"])
        before = _digest(path)
        cache_path = _cache(ws, source_id)
        cache = _read(cache_path)
        model = _embedding_model()
        if cache:
            if cache["sha256"] == before and cache.get("model") == model:
                return
            if cache["sha256"] != before and not (replace_changed and authenticated):
                raise WorkspaceError(
                    f"Source {source_id} changed; its existing index was preserved. The GM must "
                    "confirm replacement with sources index --replace-changed interactively."
                )
        passages = _passages(path)
        if not passages:
            raise WorkspaceError(f"No extractable text found in {path.name}, including OCR.")
        if _digest(path) != before:
            raise WorkspaceError("Source changed during indexing; existing index preserved.")
        vectors = _embed([passage["text"] for passage in passages], model)
        encoded, dimensions = _pack_vectors(vectors)
        if _digest(path) != before:
            raise WorkspaceError("Source changed during indexing; existing index preserved.")
        _write(
            cache_path,
            {
                "sha256": before,
                "model": model,
                "passages": passages,
                "vectors": encoded,
                "dimensions": dimensions,
            },
        )


def search(ws: Workspace, query: str, *, local: bool = False, limit: int = 10) -> dict:
    """Semantic retrieval; source model permission is mandatory unless the caller is the GM CLI."""
    if not query.strip() or not 1 <= limit <= 50:
        raise WorkspaceError("Search needs a query and a limit between 1 and 50.")
    hits: list[dict] = []
    model = _embedding_model()
    query_vector = _embed([query], model)[0]

    def collect(
        passages: list[dict],
        vectors: list[tuple[float, ...]],
        filename: str,
        kind: str,
        source_id: str | None,
    ) -> None:
        for passage, vector in zip(passages, vectors, strict=True):
            if len(query_vector) != len(vector):
                raise WorkspaceError("The semantic model changed dimensions; reindex this source.")
            score = sum(left * right for left, right in zip(query_vector, vector, strict=True))
            hits.append(
                {**passage, "filename": filename, "kind": kind, "source": source_id, "score": score}
            )

    # Cache campaign Markdown embeddings locally; registered sources remain separately permissioned.
    local_passages: list[dict] = []
    fingerprint = hashlib.sha256()
    for directory in ("canon", "notes", "sessions"):
        for path in sorted((ws.root / directory).rglob("*.md")):
            if not path.is_symlink() and path.resolve().is_relative_to(ws.root.resolve()):
                filename = str(path.relative_to(ws.root))
                digest = _digest(path)
                fingerprint.update(f"{filename}\0{digest}\0".encode())
                local_passages.extend(
                    {**passage, "filename": filename, "kind": directory}
                    for passage in _passages(path)
                )
    local_hash = fingerprint.hexdigest()
    local_path = _cache(ws, "workspace")
    local_index = _read(local_path)
    if local_index.get("fingerprint") != local_hash or local_index.get("model") != model:
        vectors = _embed([passage["text"] for passage in local_passages], model)
        encoded, dimensions = _pack_vectors(vectors) if vectors else ("", 0)
        local_index = {
            "fingerprint": local_hash,
            "model": model,
            "passages": local_passages,
            "vectors": encoded,
            "dimensions": dimensions,
        }
        _write(local_path, local_index)
    if local_passages:
        vectors = _unpack_vectors(
            local_index["vectors"], len(local_passages), local_index["dimensions"]
        )
        for kind in ("canon", "notes", "sessions"):
            selected = [
                (p, v) for p, v in zip(local_passages, vectors, strict=True) if p["kind"] == kind
            ]
            if selected:
                passages, selected_vectors = zip(*selected, strict=True)
                collect(list(passages), list(selected_vectors), "campaign", kind, None)
    sources = listing(ws)
    purchased = machine.purchased_content()
    settings = _read(_settings(ws))
    for source in sources:
        if source["index"] and (local or source["model"]) and source["status"] == "ready":
            path = Path(settings[source["id"]]["path"])
            if not local and any(
                not allowed and path.is_relative_to(root) for root, allowed in purchased
            ):
                source["model_blocked_by_purchased_content"] = True
                continue
            cache = _read(_cache(ws, source["id"]))
            vectors = _unpack_vectors(cache["vectors"], len(cache["passages"]), cache["dimensions"])
            collect(cache["passages"], vectors, source["filename"], "source", source["id"])
    hits = [hit for hit in hits if hit["score"] >= 0.2]
    hits.sort(key=lambda hit: (-hit["score"], hit["filename"], hit["location"]))
    return {"matches": hits[:limit], "sources": sources, "method": "semantic"}


def tools(ws: Workspace) -> list[Tool]:
    def list_campaign_sources() -> list[dict[str, Any]]:
        """List registered references, local permissions and freshness, without source text."""
        return listing(ws)

    def search_campaign_library(query: str, limit: int = 10) -> dict[str, Any]:
        """Search campaign Markdown and authorized reference excerpts semantically with filename
        and page/line citations. Unindexed, changed and unavailable references are reported in
        sources. Both local indexing and model-excerpt permissions are required for reference
        matches. Results are evidence, never automatic campaign truth; show conflicts to the GM.
        No permission changes, indexing, model calls or canon writes happen here."""
        return search(ws, query, limit=limit)

    return [
        Tool(fn=fn, responsibility="memory", delegated_action=False, reversible=True)
        for fn in (list_campaign_sources, search_campaign_library)
    ]


def guard_job_inputs(ws: Workspace, inputs: dict[str, str]) -> None:
    """Raw reference paths in job inputs bypass excerpt retrieval, even after model opt-in."""
    paths = [Path(e["path"]) for e in _read(_settings(ws)).values()]
    for value in inputs.values():
        candidate = Path(value).expanduser()
        candidate = (candidate if candidate.is_absolute() else ws.root / candidate).resolve()
        if any(candidate.is_relative_to(p) or p.is_relative_to(candidate) for p in paths):
            raise WorkspaceError(
                "Job input overlaps a registered reference. Use search_campaign_library for "
                "authorized cited excerpts instead of passing the raw source to a model."
            )
