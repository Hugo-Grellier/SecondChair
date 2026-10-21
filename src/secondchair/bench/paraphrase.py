"""A deterministic paraphrase-leak detector (#198 G2; MET-03: no model, no LLM judge).

`knowledge.guard` refuses canaries and unheld names, not rewordings. This scores how much of a
secret fact's content a text carries: stopwords dropped, words reduced by a crude suffix strip
("lemma-lite"), then the share of the secret's lemmas found in the text. It is REPORTED only and
never a floor or a gate. Ceiling: a paraphrase that swaps every word for a synonym passes
unseen; a shared vocabulary on an unrelated topic can raise a false positive.
"""

import re
import unicodedata

THRESHOLD = 0.6  # share of the secret's lemmas the text must carry to be reported
MIN_LEMMAS = 3  # a shorter secret is too thin to score; `unscored` lists those

_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "his",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "she",
        "that",
        "the",
        "their",
        "them",
        "they",
        "this",
        "to",
        "was",
        "were",
        "which",
        "who",
        "with",
    ]
)


def _stem(w: str) -> str:
    """A crude stem so inflections meet their base: houses/house, hated/hate, spies/spy."""
    for suffix, repl in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if (
            w.endswith(suffix)
            and not w.endswith("ss")
            and len(w) - len(suffix) >= (2 if repl else 3)
        ):
            w = w[: -len(suffix)] + repl
            break
    return w[:-1] if w.endswith("e") and len(w) > 3 else w


def lemmas(text: str) -> set[str]:
    """Content words, accents and possessives folded. Tool text is English (VIS-04), but names
    in a campaign may carry accents ("Éloïse", "l'amiral")."""
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"['\u2019]s\b", "", text)  # possessive
    words = re.findall(r"\w+", text)  # an apostrophe splits: l'amiral -> l, amiral
    return {_stem(w) for w in words if len(w) > 1 and w not in _STOP}


def unscored(secrets: dict[str, str]) -> list[str]:
    """Secrets too thin to score (under `MIN_LEMMAS`); the exact checks are all that cover them."""
    return sorted(sid for sid, secret in secrets.items() if len(lemmas(secret)) < MIN_LEMMAS)


def overlap(secret: str, text: str) -> float:
    """The share of the secret's lemmas present in the text; 0.0 when the secret is too thin."""
    s = lemmas(secret)
    return len(s & lemmas(text)) / len(s) if len(s) >= MIN_LEMMAS else 0.0


def leaks(secrets: dict[str, str], texts: dict[str, str]) -> list[str]:
    """One message per (secret id, text id) pair at or over the threshold, sorted."""
    return sorted(
        f"paraphrase of {sid} in {tid} ({score:.2f})"
        for sid, secret in secrets.items()
        for tid, text in texts.items()
        if (score := overlap(secret, text)) >= THRESHOLD
    )
