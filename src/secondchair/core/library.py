"""Reference library: local text indexes, explicit permissions, model-safe cited retrieval.

Source paths and permissions are machine configuration; excerpts stay in a machine-wide
index shared by every campaign. The workspace carries portable metadata only. Embeddings
run through the GM's own Ollama server (ADR 0001 amendment).
"""

import hashlib
import json
import math
import re
import sqlite3
import subprocess
import tempfile
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from secondchair.core import machine, notes
from secondchair.core.delegation import locked
from secondchair.core.tools import Tool
from secondchair.core.workspace import Workspace, WorkspaceError

REFERENCE_FILE = "library.yaml"
EXTENSIONS = {".pdf", ".md", ".txt"}
DEFAULT_EMBEDDING_MODEL = "qwen3-embedding:0.6b"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
# Qwen3-Embedding is trained for truncated (Matryoshka) vectors: 256 dimensions keep a
# whole PF2e library (~800k passages) near 2 s per linear query instead of 9 s at 1024.
EMBEDDING_DIMENSIONS = 256


def _key(ws: Workspace) -> str:
    return hashlib.sha256(str(ws.root.resolve()).encode()).hexdigest()[:24]


def _settings(ws: Workspace) -> Path:
    return machine.config_dir() / "library" / f"{_key(ws)}.json"


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


def _stat(path: Path) -> list[int]:
    found = path.stat()
    return [found.st_size, found.st_mtime_ns]


def _embedding_model() -> str:
    path, config = machine.config()
    model = config.get("semantic_model", DEFAULT_EMBEDDING_MODEL)
    if not isinstance(model, str) or not model.strip():
        raise WorkspaceError(f"{path}: semantic_model must be a non-empty Ollama model name.")
    return model.strip()


def _ollama_url() -> str:
    path, config = machine.config()
    url = config.get("ollama_url", DEFAULT_OLLAMA_URL)
    if not isinstance(url, str) or not re.fullmatch(r"https?://[^\s/@]+/?", url):
        raise WorkspaceError(f"{path}: ollama_url must look like http://host:11434.")
    return url.rstrip("/")


def _embed(texts: list[str], model: str) -> list[list[float]]:
    """Create embeddings on the GM's own Ollama server (ADR 0001 amendment)."""
    url = _ollama_url()
    embeddings = []
    for start in range(0, len(texts), 32):
        request = urllib.request.Request(
            url + "/api/embed",
            data=json.dumps(
                {
                    "model": model,
                    "input": texts[start : start + 32],
                    "dimensions": EMBEDDING_DIMENSIONS,
                }
            ).encode(),
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
            raise WorkspaceError(f"Semantic search needs Ollama running at {url}.") from e
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


def _db() -> sqlite3.Connection:
    """Machine-wide index shared by every campaign: passages are keyed by content digest and
    model, so a rulebook registered in several workspaces is extracted and embedded once."""
    path = machine.data_dir() / "library" / "index.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=60, isolation_level=None)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS passages (
            id INTEGER PRIMARY KEY, digest TEXT, model TEXT, location TEXT, text TEXT,
            vector BLOB);
        CREATE INDEX IF NOT EXISTS passages_key ON passages (digest, model);
        CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5 (
            text, content='passages', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
        CREATE TABLE IF NOT EXISTS indexed (
            workspace TEXT, source TEXT, digest TEXT, model TEXT, stat TEXT,
            PRIMARY KEY (workspace, source));
        """
    )
    return db


def _indexed(ws: Workspace, source_id: str) -> dict | None:
    """The version of a source this workspace last indexed, or None."""
    with closing(_db()) as db:
        row = db.execute(
            "SELECT digest, model, stat FROM indexed WHERE workspace = ? AND source = ?",
            (_key(ws), source_id),
        ).fetchone()
    return row and {"sha256": row[0], "model": row[1], "stat": json.loads(row[2])}


def _store(digest: str, model: str, extract) -> None:
    """Extract and embed one content version unless any workspace already stored it."""
    with closing(_db()) as db:
        if db.execute(
            "SELECT 1 FROM passages WHERE digest = ? AND model = ? LIMIT 1", (digest, model)
        ).fetchone():
            return
    passages = extract()
    if not passages:
        return
    vectors = _embed([passage["text"] for passage in passages], model)
    if len({len(vector) for vector in vectors}) != 1:
        raise WorkspaceError("Ollama returned embeddings with inconsistent dimensions.")
    with closing(_db()) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            if not db.execute(
                "SELECT 1 FROM passages WHERE digest = ? AND model = ? LIMIT 1", (digest, model)
            ).fetchone():
                for passage, vector in zip(passages, vectors, strict=True):
                    rowid = db.execute(
                        "INSERT INTO passages (digest, model, location, text, vector) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            digest,
                            model,
                            passage["location"],
                            passage["text"],
                            np.asarray(vector, dtype="<f4").tobytes(),
                        ),
                    ).lastrowid
                    db.execute(
                        "INSERT INTO passages_fts (rowid, text) VALUES (?, ?)",
                        (rowid, passage["text"]),
                    )
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise


def listing(ws: Workspace) -> list[dict[str, Any]]:
    """Metadata only, including permission and index freshness. Never return source paths."""
    settings = _read(_settings(ws))
    model = _embedding_model()
    result = []
    for source_id, name in _references(ws).items():
        entry = settings.get(source_id)
        status = "unavailable"
        if entry and Path(entry["path"]).is_file():
            path = Path(entry["path"])
            done = _indexed(ws, source_id)
            # Hashing every rulebook on each search is too slow; trust an unchanged size+mtime.
            same = done and (done["stat"] == _stat(path) or done["sha256"] == _digest(path))
            status = (
                "unindexed"
                if not done
                else "changed"
                if not same
                else "ready"
                if done["model"] == model
                else "model-changed"
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
                ["pdftotext", "-enc", "UTF-8", str(path), "-"],
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
        # Pack whole lines into ~1,500-character passages: fixed line counts leave page
        # numbers and headers as tiny passages that outrank real text on short queries.
        chunks: list[tuple[int, list[str]]] = []
        for number, line in enumerate(text.splitlines(), 1):
            if not chunks or sum(len(kept) + 1 for kept in chunks[-1][1]) + len(line) > 1500:
                chunks.append((number, []))
            chunks[-1][1].append(line)
        if len(chunks) > 1 and len("".join(chunks[-1][1]).strip()) < 200:
            chunks[-2][1].extend(chunks.pop()[1])
        for start, lines in chunks:
            excerpt = "\n".join(lines).strip()
            location = f"page {page}" if path.suffix.lower() == ".pdf" else f"line {start}"
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
        stat, before = _stat(path), _digest(path)
        done = _indexed(ws, source_id)
        model = _embedding_model()
        if done:
            if done["sha256"] == before and done["model"] == model:
                return
            if done["sha256"] != before and not (replace_changed and authenticated):
                raise WorkspaceError(
                    f"Source {source_id} changed; its existing index was preserved. The GM must "
                    "confirm replacement with sources index --replace-changed interactively."
                )

        def extract() -> list[dict]:
            passages = _passages(path)
            if not passages:
                raise WorkspaceError(f"No extractable text found in {path.name}, including OCR.")
            if _digest(path) != before:
                raise WorkspaceError("Source changed during indexing; existing index preserved.")
            return passages

        # ponytail: superseded content versions stay in the shared index; add a GC if disk matters.
        _store(before, model, extract)
        if _digest(path) != before:
            raise WorkspaceError("Source changed during indexing; existing index preserved.")
        with closing(_db()) as db:
            db.execute(
                "INSERT OR REPLACE INTO indexed VALUES (?, ?, ?, ?, ?)",
                (_key(ws), source_id, before, model, json.dumps(stat)),
            )


RRF_K = 60  # reciprocal rank fusion constant
# Qwen3-Embedding expects an instruction on queries, not on indexed passages.
QUERY_INSTRUCTION = (
    "Instruct: Given a question about a tabletop RPG book, retrieve passages that answer it\n"
    "Query: "
)
CANDIDATES = 30  # per retrieval method, before fusion


def _note_status(path: Path) -> str | None:
    try:
        return (notes.front_matter(path.read_text()) or {}).get("status")
    except yaml.YAMLError, ValueError, UnicodeDecodeError:
        return None  # `notes check` reports it


def search(
    ws: Workspace,
    query: str,
    *,
    local: bool = False,
    limit: int = 10,
    include_closed: bool = False,
) -> dict:
    """Hybrid retrieval: exact-term BM25 (names of spells, gods, places) fused with semantic
    similarity. Source model permission is mandatory unless the caller is the GM CLI."""
    if not query.strip() or not 1 <= limit <= 50:
        raise WorkspaceError("Search needs a query and a limit between 1 and 50.")
    model = _embedding_model()
    # Content digest -> where it is cited from. Campaign Markdown is stored like any source.
    origins: dict[str, list[dict]] = {}
    for directory in ("canon", "notes", "sessions"):
        for path in sorted((ws.root / directory).rglob("*.md")):
            if not path.is_symlink() and path.resolve().is_relative_to(ws.root.resolve()):
                status = _note_status(path) if directory == "notes" else None
                if status in notes.CLOSED and not include_closed:
                    continue  # rejected / superseded design notes (ADR 0017)
                digest = _digest(path)
                _store(digest, model, lambda path=path: _passages(path))
                origins.setdefault(digest, []).append(
                    {"filename": str(path.relative_to(ws.root)), "kind": directory, "source": None}
                    | ({"status": status} if status else {})
                )
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
            done = _indexed(ws, source["id"])
            if done:  # "ready" was just read from it; a concurrent reset drops the source
                origins.setdefault(done["sha256"], []).append(
                    {"filename": source["filename"], "kind": "source", "source": source["id"]}
                )
    if not origins:
        return {"matches": [], "sources": sources, "method": "hybrid"}
    digests = list(origins)
    marks = ",".join("?" * len(digests))
    fused: dict[int, float] = {}
    with closing(_db()) as db:
        # ponytail: loads every authorized vector per query (~1 s at 300k passages); keep a
        # per-process matrix cache if serve latency matters.
        rows = db.execute(
            f"SELECT id, vector FROM passages WHERE model = ? AND digest IN ({marks})",
            (model, *digests),
        ).fetchall()
        if rows:
            ids = np.array([row[0] for row in rows])
            matrix = np.frombuffer(b"".join(row[1] for row in rows), dtype="<f4")
            query_vector = np.asarray(_embed([QUERY_INSTRUCTION + query], model)[0], dtype="<f4")
            if matrix.size != len(rows) * query_vector.size:
                raise WorkspaceError("The semantic model changed dimensions; reindex sources.")
            scores = matrix.reshape(len(rows), -1) @ query_vector
            best = [i for i in np.argsort(-scores)[:CANDIDATES] if scores[i] >= 0.2]
            for rank, i in enumerate(best):
                fused[int(ids[i])] = 1 / (RRF_K + rank)
        # Every query term must appear: the lexical leg is for precision, the semantic for recall.
        terms = " ".join(f'"{word}"' for word in re.findall(r"\w+", query))
        if terms:
            lexical = db.execute(
                f"SELECT p.id FROM passages_fts JOIN passages p ON p.id = passages_fts.rowid "
                f"WHERE passages_fts MATCH ? AND p.model = ? AND p.digest IN ({marks}) "
                f"ORDER BY bm25(passages_fts) LIMIT ?",
                (terms, model, *digests, CANDIDATES),
            ).fetchall()
            for rank, (rowid,) in enumerate(lexical):
                fused[rowid] = fused.get(rowid, 0) + 1 / (RRF_K + rank)
        exact = {rowid for (rowid,) in lexical} if terms else set()
        # On equal fused rank an exact-term match beats a semantic neighbour.
        ranked = sorted(fused, key=lambda i: (fused[i], i in exact), reverse=True)[:limit]
        found = {
            row[0]: row[1:]
            for row in db.execute(
                f"SELECT id, digest, location, text FROM passages "
                f"WHERE id IN ({','.join('?' * len(ranked))})",
                ranked,
            )
        }
    hits = [
        {"location": location, "text": text, **origin, "score": fused[rowid]}
        for rowid in ranked
        for digest, location, text in [found[rowid]]
        for origin in origins[digest]
    ]
    return {"matches": hits[:limit], "sources": sources, "method": "hybrid"}


def tools(ws: Workspace) -> list[Tool]:
    def list_campaign_sources() -> list[dict[str, Any]]:
        """List registered references, local permissions and freshness, without source text."""
        return listing(ws)

    def search_campaign_library(
        query: str, limit: int = 10, include_closed: bool = False
    ) -> dict[str, Any]:
        """Search campaign Markdown and authorized reference excerpts semantically with filename
        and page/line citations. Unindexed, changed and unavailable references are reported in
        sources. Both local indexing and model-excerpt permissions are required for reference
        matches. Rejected and superseded design notes are left out unless include_closed.
        Results are evidence, never automatic campaign truth; show conflicts to the GM.
        No permission changes, indexing, model calls or canon writes happen here."""
        return search(ws, query, limit=limit, include_closed=include_closed)

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
