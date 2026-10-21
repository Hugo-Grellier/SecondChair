"""Admission (ADR 0015): a rank above agent_proposal is admitted only on evidence the Core
resolves itself. The caller names evidence in its origin; `admit` looks it up, and refuses a
forged one with a `CanonError` naming what is missing. `index.rank_of` stays a pure mapping.

Who is calling is set by the code path, never by data: `delegation.act` runs a tool function
`under` the context of the job it acts for (that job's Sources), and the Core's own writers (a
disclosure, the world-turn) pass `CORE`. Neither is a tool parameter.
"""

import re
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from secondchair.core import index, observations
from secondchair.core.index import PARTY, CanonError
from secondchair.core.workspace import Workspace


@dataclass(frozen=True)
class Context:
    """What admission may resolve evidence against: the inputs of the job the action runs
    under (its Sources), and whether the Core itself composes the record."""

    sources: dict[str, str] = field(default_factory=dict)
    core: bool = False


CORE = Context(core=True)
MIN_WORDS = 3  # a quote is evidence only with this many words, matched as whole words
CITED = (  # one refusal, whatever is missing: it tells nothing of the library (no page oracle)
    "the reference library has no such page and excerpt that a model may read (registered, "
    "indexing and model permission, a ready index: secondchair sources)"
)
_current: ContextVar[Context | None] = ContextVar("secondchair.admission", default=None)


@contextmanager
def under(context: Context) -> Generator[None]:
    """Run a tool function with `context` as its admission context."""
    token = _current.set(context)
    try:
        yield
    finally:
        _current.reset(token)


def admit(
    ws: Workspace, origin: Any, context: Context | None = None, knower: str | None = None
) -> None:
    """Refuse `origin` unless the Core finds the evidence its rank needs (ADR 0015 table). An
    observation quotes a VTT observation by id (for the party, one the table saw) or a line of
    the job's Sources; a source cites an indexed page of the reference library; a rule or an
    action log locator is the Core's own. A gm or job origin needs nothing: it ranks
    agent_proposal."""
    context = context or _current.get() or Context()  # outside any job: no Sources
    index.rank_of(origin, authenticated=context.core)  # its shape; only the Core writes a rule
    if context.core:
        return
    if origin["kind"] == "observation":
        missing = _observed(ws, origin["quote"], origin["locator"], context, knower)
    elif origin["kind"] == "source":
        missing = _cited(ws, origin["source"], origin["page"], origin.get("excerpt"))
    else:
        return
    if missing:
        raise CanonError(
            f"{origin['kind'].capitalize()} origin refused: {missing}. Without evidence the Core "
            "can find, record it with a job origin carrying it."
        )


def substantive(quote: str) -> bool:
    """Whether `quote` has enough words to be evidence (MIN_WORDS)."""
    return len(re.findall(r"\w+", quote)) >= MIN_WORDS


def _starts(quote: str, text: str) -> list[int]:
    """Where `quote` occurs in `text` as whole words: never inside a longer word."""
    q = quote.strip()
    before = r"(?<!\w)" if re.match(r"\w", q) else ""
    after = r"(?!\w)" if re.search(r"\w$", q) else ""
    return [m.start() for m in re.finditer(before + re.escape(q) + after, text)]


def quoted(sources: dict[str, str], locator: str, quote: str) -> bool:
    """Whether `quote`, substantive, is at a `<file>:<line>` locator in one of `sources` (a job's
    inputs), as whole words: in that segment's text for its transcript, starting on that line
    for any other file."""
    if not substantive(quote):
        return False
    from secondchair.core import capture  # it builds on canon, which builds on this module

    name, _, line = locator.rpartition(":")
    parts = Path(name).parts
    for key, value in sources.items():
        path = Path(value)
        if not parts or path.parts[-len(parts) :] != parts or not path.is_file():
            continue
        if key == "transcript":
            segment = capture._segment(value, locator)
            if segment is not None and _starts(quote, segment["text"]):
                return True
            continue
        text = path.read_text()
        lines, n = text.splitlines(keepends=True), int(line) if line.isdigit() else 0
        if 0 < n <= len(lines):  # it starts on line n, and may run on past it
            start = sum(map(len, lines[: n - 1]))
            if any(start <= i < start + len(lines[n - 1]) for i in _starts(quote, text)):
                return True
    return False


def _observed(
    ws: Workspace, quote: str, locator: str, context: Context, knower: str | None
) -> str | None:
    if not substantive(quote):
        return f"a quote needs at least {MIN_WORDS} words of what was said or done"
    if locator.startswith(f"{index.LOG_DIR}/"):
        return f"{locator} is an action log entry, which only the Core quotes (a disclosure)"
    if not locator.startswith(f"{observations.DIR}/"):
        if not quoted(context.sources, locator, quote):
            return f"the quote is not at {locator} in the Sources of the job it runs under"
        return None
    seen = observations.find(ws, locator)
    if seen is None:
        return f"no observation at {locator}"
    if not any(_starts(quote, s) for s in _strings(seen["payload"])):
        return f"the quote is not in the observation at {locator}"
    if knower == PARTY and seen["visibility"] != "players":
        return (
            f"the observation {locator} is {seen['visibility']}: the table did not see it, so it "
            "never marks a fact as known by the party. Hold it as a call for the wrap"
        )
    return None


def _cited(ws: Workspace, source: str, page: str, excerpt: Any) -> str | None:
    from secondchair.core import library  # it reads the machine's reference library

    text = library.page_text(ws, source, page)
    if text is None or (
        excerpt is not None
        and (
            not isinstance(excerpt, str)
            or not substantive(excerpt)
            or not _starts(" ".join(excerpt.split()), " ".join(text.split()))
        )
    ):
        return CITED
    return None


def _strings(value: Any) -> Generator[str]:
    """Every string in an observation's payload."""
    if isinstance(value, str):
        yield value
    for v in (
        value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    ):
        yield from _strings(v)


def unresolved(ws: Workspace) -> list[str]:
    """`secondchair doctor` (ADR 0015 c): each canon record ranked played or cited_source whose
    evidence no longer resolves (an observation or a Source edited or lost since). Its rank
    stands; nothing is changed. A file locator resolves against any job's Sources."""
    from secondchair.core import delegation  # it builds on this module's callers

    jobs = [
        Context(sources=dict(delegation._read_yaml(p)["inputs"]))
        for p in sorted((ws.root / delegation.JOBS_DIR).glob("*.yaml"))
    ] or [Context()]
    knowers = [PARTY, *(e["id"] for e in index.search_entities(ws))]
    records = [
        *index.search_facts(ws, include_retconned=True),
        *index.search_events(ws),
        *index.search_knowledge(ws, knowers),
    ]
    found = []
    for record in records:  # ranked by the index: a hand edit is agent_proposal (CAN-11)
        origin = record["origin"]
        if record["rank"] not in ("played", "cited_source") or str(
            origin.get("locator", "")
        ).startswith(f"{index.LOG_DIR}/"):
            continue  # a disclosure quotes the Core's own entry
        errors = []
        for context in jobs:
            try:
                admit(ws, origin, context, knower=record.get("knower"))
                break
            except CanonError as e:
                errors.append(str(e))
        else:
            found.append(f"{record['id']}: {errors[0]}")
    return found
