"""A deterministic paraphrase-leak detector (#198 G2; MET-03: no model, no LLM judge).

`knowledge.guard` refuses canaries and unheld names, not rewordings. This scores how much of a
secret fact's content a text carries: stopwords dropped, words reduced by a crude suffix strip
("lemma-lite"), then the share of the secret's lemmas found in the text. It is REPORTED only and
never a floor or a gate. Ceiling: a paraphrase that swaps every word for a synonym passes
unseen; a shared vocabulary on an unrelated topic can raise a false positive.
"""

import re

THRESHOLD = 0.6  # share of the secret's lemmas the text must carry to be reported
MIN_LEMMAS = 3  # a shorter secret is too thin to score; exact checks cover it

_STOP = frozenset(
    "a an and are as at be been but by for from had has have he her his in is it its of on or "
    "she that the their them they this to was were which who with".split()
)
_SUFFIXES = ("ing", "ed", "es", "s")


def lemmas(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9']+", text.lower()):
        if w in _STOP:
            continue
        for s in _SUFFIXES:
            if w.endswith(s) and len(w) - len(s) >= 3:
                w = w[: -len(s)]
                break
        out.add(w)
    return out


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
