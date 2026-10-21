"""The index's stat cache (#172): an unchanged read hashes no canon or action-log file, and every
change the full hash saw still rebuilds the index."""

import json
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from secondchair.core import canon, delegation, index, workspace
from secondchair.core.workspace import STATE_DIR, Workspace


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    ws = workspace.init(tmp_path / "camp", "en", "absalom")
    for name in ("Mira Pell", "Tovan Reed"):
        create(ws, name)
    return ws


def create(ws: Workspace, name: str) -> None:
    tool = next(t for t in canon.tools(ws) if t.name == "create_entity")
    delegation.act(ws, tool, "test-agent", lambda: tool.fn(names=[name]))


def mira(ws: Workspace) -> Path:
    return next(p for p in (ws.root / index.ENTITIES_DIR).glob("*.md") if "Mira" in p.read_text())


def inputs(ws: Workspace) -> list[Path]:
    return [p for top in index.FINGERPRINTED for p in (ws.root / top).rglob("*") if p.is_file()]


def settle(ws: Workspace) -> None:
    """Age every input past the mtime granularity, as between sessions; a rebuild then writes
    the cache, as after a write that does not age."""
    old = time.time_ns() - 2 * index.MTIME_GRANULARITY_NS
    for p in inputs(ws):
        os.utime(p, ns=(old, old))
    index.rebuild(ws)


def reads(ws: Workspace) -> set[Path]:
    """The inputs whose content one connect reads."""
    seen: set[Path] = set()
    read_bytes = Path.read_bytes

    def counted(path: Path) -> bytes:
        seen.add(Path(path))
        return read_bytes(path)

    with patch.object(Path, "read_bytes", counted):
        index.connect(ws).close()
    return seen & set(inputs(ws))


def full_hash(ws: Workspace) -> str:
    (ws.root / STATE_DIR / index.STAT_CACHE).unlink(missing_ok=True)
    return index._fingerprint(ws)[0]


def stored(ws: Workspace) -> str:
    with index.connect(ws) as conn:
        return conn.execute("select value from meta where key = 'fingerprint'").fetchone()[0]


def names(ws: Workspace) -> list[str]:
    return sorted(n for e in index.search_entities(ws) for n in e["names"])


def test_an_unchanged_read_hashes_nothing_and_gives_the_full_hash(ws: Workspace) -> None:
    settle(ws)
    cache = (ws.root / STATE_DIR / index.STAT_CACHE).read_bytes()
    assert reads(ws) == set()
    assert reads(ws) == set()
    assert (ws.root / STATE_DIR / index.STAT_CACHE).read_bytes() == cache  # a read writes none
    assert stored(ws) == full_hash(ws)


def test_a_file_written_just_before_the_cache_is_re_read_until_the_next_rebuild(
    ws: Workspace,
) -> None:
    index.connect(ws).close()
    assert reads(ws) == set(inputs(ws))  # all written within the granularity of the cache
    settle(ws)
    assert reads(ws) == set()


def test_a_core_write_and_a_hand_edit_rebuild(ws: Workspace) -> None:
    settle(ws)
    create(ws, "Sella Voss")
    assert "Sella Voss" in names(ws)

    settle(ws)
    doc = mira(ws)
    text = doc.read_text()
    doc.write_text(text.replace("Mira Pell", "Mira Bell"))
    assert len(doc.read_text()) == len(text)  # same size: the mtime alone gives it away
    index.connect(ws).close()
    assert delegation.read_log(ws)[0][-1]["kind"] == "hand_edit"


def test_an_edit_in_the_same_tick_as_the_cache_is_still_seen(ws: Workspace) -> None:
    index.connect(ws).close()  # the cache is written just after the files: they are racy
    doc = mira(ws)
    before = doc.stat()
    doc.write_text(doc.read_text().replace("Mira Pell", "Mira Bell"))
    os.utime(doc, ns=(before.st_atime_ns, before.st_mtime_ns))  # same size, same mtime
    index.connect(ws).close()
    assert delegation.read_log(ws)[0][-1]["kind"] == "hand_edit"


def test_the_documented_blind_spot_a_settled_file_rewritten_with_its_size_and_mtime(
    ws: Workspace,
) -> None:
    settle(ws)
    doc = mira(ws)
    before = doc.stat()
    doc.write_text(doc.read_text().replace("Mira Pell", "Mira Bell"))
    os.utime(doc, ns=(before.st_atime_ns, before.st_mtime_ns))
    index.connect(ws).close()
    assert delegation.read_log(ws)[0][-1]["kind"] != "hand_edit"
    index.rebuild(ws)  # check, or any rebuild, compares content and sees it
    assert delegation.read_log(ws)[0][-1]["kind"] == "hand_edit"


def test_a_schema_upgrade_rebuilds(ws: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    settle(ws)
    old = stored(ws)
    monkeypatch.setattr(index, "_SCHEMA", index._SCHEMA + "\n-- a new column\n")
    assert stored(ws) != old


def test_a_restored_workspace_rebuilds(ws: Workspace, tmp_path: Path) -> None:
    settle(ws)
    backup = tmp_path / "backup"
    tops = [top for top in index.FINGERPRINTED if (ws.root / top).is_dir()]  # no journal at rest
    for top in tops:
        shutil.copytree(ws.root / top, backup / top)  # copy2: the mtimes travel too
    create(ws, "Sella Voss")
    assert "Sella Voss" in names(ws)

    for top in tops:
        shutil.rmtree(ws.root / top)
        shutil.copytree(backup / top, ws.root / top)
    assert "Sella Voss" not in names(ws)
    assert stored(ws) == full_hash(ws)


@pytest.mark.parametrize(
    "cache",
    [None, "not json", '{"version": 1}', '{"version": 0, "written_ns": 0, "files": {}}', "[]"],
)
def test_a_missing_corrupt_or_older_cache_falls_back_to_full_hashing(
    ws: Workspace, cache: str | None
) -> None:
    settle(ws)
    path = ws.root / STATE_DIR / index.STAT_CACHE
    if cache is None:
        path.unlink()
    else:
        path.write_text(cache)
    assert reads(ws) == set(inputs(ws))
    assert json.loads(path.read_text())["version"] == index.STAT_CACHE_VERSION  # healed
    assert reads(ws) == set()


def test_a_future_mtime_or_a_cache_from_the_future_falls_back(ws: Workspace) -> None:
    settle(ws)
    future = time.time_ns() + 3600 * 10**9
    doc = inputs(ws)[0]
    os.utime(doc, ns=(future, future))
    assert reads(ws) == set(inputs(ws))

    settle(ws)
    path = ws.root / STATE_DIR / index.STAT_CACHE
    cache = json.loads(path.read_text())
    path.write_text(json.dumps(cache | {"written_ns": future}))
    assert reads(ws) == set(inputs(ws))


def test_concurrent_connects_and_writes_leave_a_whole_cache(ws: Workspace) -> None:
    def work(n: int) -> None:
        if n % 4 == 0:
            create(ws, f"Fictional person {n}")
        index.connect(ws).close()

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(work, range(40)))
    cache = json.loads((ws.root / STATE_DIR / index.STAT_CACHE).read_text())
    assert cache["version"] == index.STAT_CACHE_VERSION
    assert len(names(ws)) == 12
    assert stored(ws) == full_hash(ws)
    assert not list((ws.root / STATE_DIR).glob("*.tmp"))
