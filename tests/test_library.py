import hashlib
import re
import shutil
import subprocess
import zlib

import pytest

from secondchair.cli import main
from secondchair.core import campaign, index, jobs, library, workspace


@pytest.fixture(autouse=True)
def test_embedding_model(monkeypatch):
    """Small deterministic vectors keep ordinary library tests independent of Ollama."""
    families = {
        "detective": {"detective", "sleuth", "investigator", "detectives"},
        "murder": {"murder", "killer", "murderer", "homicide", "killing"},
        "food": {"recipe", "cook", "chickpeas", "saffron", "meal"},
    }
    family = {word: slot for slot, words in enumerate(families.values()) for word in words}

    def embed(texts, model):
        vectors = []
        for text in texts:
            vector = [0.0] * 128
            for word in re.findall(r"\w+", text.casefold()):
                slot = family.get(word)
                if slot is None:
                    slot = (
                        3 + int.from_bytes(hashlib.sha256(word.encode()).digest()[:2], "big") % 125
                    )
                    sign = 1 if hashlib.sha256(word.encode()).digest()[2] % 2 else -1
                else:
                    sign = 1
                vector[slot] += sign
            norm = sum(value * value for value in vector) ** 0.5
            vectors.append([value / norm for value in vector] if norm else [1.0] + [0.0] * 127)
        return vectors

    monkeypatch.setattr(library, "_embed", embed)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return workspace.init(tmp_path / "campaign", "fr", "absalom")


def source(ws, tmp_path, text="Un secret dans le port."):
    path = tmp_path / "reference.txt"
    path.write_text(text)
    [source_id] = library.register(ws, path)
    return source_id, path


def test_registration_permissions_and_revocation_are_independent(ws, tmp_path):
    sid, path = source(ws, tmp_path)
    assert library.listing(ws) == [
        {"id": sid, "filename": path.name, "status": "unindexed", "index": False, "model": False}
    ]
    with pytest.raises(workspace.WorkspaceError, match="indexing permission"):
        library.build_index(ws, sid)
    with pytest.raises(workspace.WorkspaceError, match="interactive"):
        library.permit(ws, sid, True, True, False)
    library.permit(ws, sid, None, True, True)
    with pytest.raises(workspace.WorkspaceError, match="indexing permission"):
        library.build_index(ws, sid)
    library.permit(ws, sid, True, False, True)
    library.build_index(ws, sid)
    assert library.search(ws, "secret")["matches"] == []
    assert library.search(ws, "secret", local=True)["matches"][0]["location"] == "line 1"
    library.permit(ws, sid, None, True, True)
    tools = {t.name: t.fn for t in campaign.tools(ws)}
    result = tools["search_campaign_library"]("secret")
    assert result["matches"][0]["source"] == sid
    assert "path" not in tools["list_campaign_sources"]()[0]
    library.permit(ws, sid, False, None, True)
    assert library.search(ws, "secret")["matches"] == []
    assert library._indexed(ws, sid)
    assert str(path) not in (ws.root / library.REFERENCE_FILE).read_text()
    assert not list(ws.root.rglob("*.txt"))


def test_changed_source_requires_explicit_authenticated_replacement(ws, tmp_path):
    sid, path = source(ws, tmp_path)
    library.permit(ws, sid, True, True, True)
    library.build_index(ws, sid)
    cache = library._indexed(ws, sid)
    path.write_text("Un nouveau secret.")
    assert library.listing(ws)[0]["status"] == "changed"
    assert library.search(ws, "secret")["matches"] == []
    for replace, auth in ((False, True), (True, False), (False, False)):
        with pytest.raises(workspace.WorkspaceError, match="changed"):
            library.build_index(ws, sid, replace, auth)
        assert library._indexed(ws, sid) == cache
    library.build_index(ws, sid, True, True)
    assert library.search(ws, "nouveau")["matches"]
    path.unlink()
    assert library.search(ws, "secret")["sources"][0]["status"] == "unavailable"


def test_folder_snapshot_campaign_notes_and_no_canon_side_effects(ws, tmp_path):
    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "a.md").write_text("Absalom piste port")
    (folder / "b.txt").write_text("Absalom prologue")
    (folder / "ignore.bin").write_bytes(b"unsupported")
    ids = library.register(ws, folder)
    assert len(ids) == 2
    assert library.register(ws, folder) == ids
    note = ws.root / "notes/workshop/port.md"
    note.parent.mkdir(parents=True)
    note.write_text("Piste Absalom : emploi au port. Question ouverte.")
    assert index.search_facts(ws) == []
    hits = library.search(ws, "Absalom")["matches"]
    assert len(hits) == 1 and hits[0]["kind"] == "notes"
    assert hits[0]["filename"] == "notes/workshop/port.md"
    assert index.search_facts(ws) == []
    linked = note.parent / "external.md"
    linked.symlink_to(folder / "a.md")
    assert len(library.search(ws, "Absalom")["matches"]) == 1
    with pytest.raises(workspace.WorkspaceError, match="outside"):
        library.register(ws, note)


def test_cli_local_search_and_permissions_require_gm_terminal(ws, tmp_path, monkeypatch, capsys):
    sid, _ = source(ws, tmp_path)
    assert main(["sources", "permit", sid, "--index", "allow", "-w", str(ws.root)]) == 1
    assert main(["sources", "search", "secret", "--local", "-w", str(ws.root)]) == 1
    monkeypatch.setattr("secondchair.cli.interactive", lambda: True)
    assert main(["sources", "permit", sid, "--index", "allow", "-w", str(ws.root)]) == 0
    assert main(["sources", "index", sid, "-w", str(ws.root)]) == 0
    assert main(["sources", "search", "secret", "--local", "-w", str(ws.root)]) == 0
    assert "secret" in capsys.readouterr().out


def test_raw_registered_source_cannot_be_passed_as_job_input(ws, tmp_path):
    sid, path = source(ws, tmp_path)
    library.permit(ws, sid, True, True, True)
    for value in (str(path), str(path.parent), "../reference.txt"):
        with pytest.raises(workspace.WorkspaceError, match="registered reference"):
            jobs.queue(
                ws,
                playbook="test",
                inputs={"source": value},
                expected_output="test",
                responsibility="memory",
                tier="standard",
            )


def make_pdf(path, texts=("Harbor archaeology", "Absalom ancient treasure"), size=12):
    """Two real text pages with an xref table, without a PDF-generation dependency."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
    ]
    for content in (5, 6):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] "
            f"/Resources << /Font << /F1 7 0 R >> >> /Contents {content} 0 R >>".encode()
        )
    for text in texts:
        stream = f"BT /F1 {size} Tf 50 700 Td ({text}) Tj ET".encode()
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    data = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(data)
    data += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets)
    data += f"trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(data)


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="Poppler not installed")
def test_real_pdf_full_document_retrieval_with_page_citation(ws, tmp_path):
    pdf = tmp_path / "setting.pdf"
    make_pdf(pdf)
    [sid] = library.register(ws, pdf)
    library.permit(ws, sid, True, True, True)
    library.build_index(ws, sid)
    [hit] = library.search(ws, "Absalom treasure")["matches"]
    assert hit["filename"] == "setting.pdf" and hit["location"] == "page 2"
    assert hit["source"] == sid
    [hit] = library.search(ws, "Harbor archaeology")["matches"]
    assert hit["location"] == "page 1"


def test_purchased_content_denial_also_blocks_reference_model_excerpts(ws, tmp_path):
    sid, path = source(ws, tmp_path)
    library.permit(ws, sid, True, True, True)
    library.build_index(ws, sid)
    config = library.machine.config_dir() / "config.yaml"
    config.write_text(f"purchased_content:\n  - path: {path}\n    opt_in: false\n")
    result = library.search(ws, "secret")
    assert result["matches"] == []
    assert result["sources"][0]["model_blocked_by_purchased_content"]
    assert library.search(ws, "secret", local=True)["matches"]


def test_registering_a_source_after_queue_still_blocks_job_start(ws, tmp_path):
    path = tmp_path / "reference.txt"
    path.write_text("secret")
    queued = jobs.queue(
        ws,
        playbook="test",
        inputs={"source": str(path)},
        expected_output="test",
        responsibility="memory",
        tier="standard",
    )
    library.register(ws, path)
    with pytest.raises(workspace.WorkspaceError, match="registered reference"):
        jobs.start(ws, queued["id"], {"host": "test", "model": "test", "effort": "test"}, True)
    assert jobs.read(ws, queued["id"])["status"] == "queued"


def test_failed_refresh_keeps_previous_index(ws, tmp_path, monkeypatch):
    sid, path = source(ws, tmp_path)
    library.permit(ws, sid, True, True, True)
    library.build_index(ws, sid)
    original = library._indexed(ws, sid)
    path.write_text("changed")

    def extraction_failed(path):
        raise workspace.WorkspaceError("No extractable text")

    monkeypatch.setattr(library, "_passages", extraction_failed)
    with pytest.raises(workspace.WorkspaceError, match="No extractable text"):
        library.build_index(ws, sid, True, True)
    assert library._indexed(ws, sid) == original


def test_search_ignores_empty_working_notes(ws):
    note = ws.root / "notes/workshop/empty.md"
    note.parent.mkdir(parents=True)
    note.touch()
    assert library.search(ws, "secret")["matches"] == []


def test_mcp_search_returns_only_permitted_excerpts(ws, tmp_path):
    import asyncio

    from mcp import Client

    from secondchair.core.server import build_server

    sid, _ = source(ws, tmp_path)
    library.permit(ws, sid, True, False, True)
    library.build_index(ws, sid)

    async def exercise():
        async with Client(build_server(ws)) as client:
            result = await client.call_tool("search_campaign_library", {"query": "secret"})
            assert not result.is_error, result.content
            assert result.structured_content["matches"] == []
            library.permit(ws, sid, None, True, True)
            result = await client.call_tool("search_campaign_library", {"query": "secret"})
            assert not result.is_error, result.content
            assert result.structured_content["matches"][0]["source"] == sid

    asyncio.run(exercise())


def test_semantic_query_finds_paraphrased_passage_and_ranks_it(ws, tmp_path):
    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "mystery.txt").write_text("A detective questions witnesses after a homicide.")
    (folder / "cookbook.txt").write_text("A recipe explains how to cook chickpeas with saffron.")
    ids = library.register(ws, folder)
    for sid in ids:
        library.permit(ws, sid, True, True, True)
        library.build_index(ws, sid)
    result = library.search(ws, "A sleuth investigates a killer.")
    assert result["method"] == "hybrid"
    assert [hit["filename"] for hit in result["matches"]] == ["mystery.txt"]
    assert result["matches"][0]["score"] > 0


def make_scanned_pdf(path, tmp_path):
    """Rasterize a text PDF with Poppler and wrap the grey bitmap as an image-only PDF."""
    text = tmp_path / "text.pdf"
    make_pdf(text, ("DRAGON HARBOR", "unused"), size=48)
    subprocess.run(
        [
            "pdftoppm",
            "-f",
            "1",
            "-l",
            "1",
            "-r",
            "100",
            "-gray",
            "-singlefile",
            text,
            tmp_path / "page",
        ],
        check=True,
    )
    raw = (tmp_path / "page.pgm").read_bytes()
    _, width, height, _, pixels = raw.split(maxsplit=4)
    compressed = zlib.compress(pixels)
    image = (
        f"<< /Type /XObject /Subtype /Image /Width {int(width)} /Height {int(height)} "
        f"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode "
        f"/Length {len(compressed)} >>\nstream\n".encode()
        + compressed
        + b"\nendstream"
    )
    content = b"q 600 0 0 800 0 0 cm /Im0 Do Q"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources "
        b"<< /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        image,
    ]
    data, offsets = b"%PDF-1.4\n", []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 6\n0000000000 65535 f \n"
    data += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets)
    data += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(data)


@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("pdftotext", "pdftoppm", "tesseract")),
    reason="Poppler and Tesseract are needed for the scanned-PDF integration test",
)
def test_scanned_pdf_is_ocr_indexed_with_a_page_citation(ws, tmp_path):
    pdf = tmp_path / "scanned.pdf"
    make_scanned_pdf(pdf, tmp_path)
    [sid] = library.register(ws, pdf)
    library.permit(ws, sid, True, True, True)
    library.build_index(ws, sid)
    result = library.search(ws, "dragon harbor")
    assert result["matches"][0]["filename"] == "scanned.pdf"
    assert result["matches"][0]["location"] == "page 1"
    assert "DRAGON" in result["matches"][0]["text"]


def test_exact_names_match_lexically_and_index_is_shared_across_campaigns(
    ws, tmp_path, monkeypatch
):
    sid, path = source(ws, tmp_path, "Le culte de Dahak hante les ruines azlantes.")
    calls = []

    def unrelated(texts, model):
        """Semantic similarity finds nothing; only the BM25 leg can match."""
        calls.append(len(texts))
        return [[1.0, 0.0] if text != "Dahak" else [0.0, 1.0] for text in texts]

    monkeypatch.setattr(library, "_embed", unrelated)
    library.permit(ws, sid, True, True, True)
    library.build_index(ws, sid)
    [hit] = library.search(ws, "Dahak")["matches"]
    assert hit["source"] == sid and "Dahak" in hit["text"]
    other = workspace.init(tmp_path / "other", "fr", "absalom")
    [other_sid] = library.register(other, path)
    library.permit(other, other_sid, True, True, True)
    indexed = len(calls)
    library.build_index(other, other_sid)
    assert len(calls) == indexed  # same content, same model: nothing re-embedded
    assert library.search(other, "dahak")["matches"][0]["source"] == other_sid
