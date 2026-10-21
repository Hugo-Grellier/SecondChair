"""The paraphrase-leak detector (#198 G2), on invented text."""

from secondchair.bench import paraphrase

SECRET = {"S1": "The harbourmaster secretly sells the lantern keys to the smugglers"}


def found(text: str) -> list[str]:
    return paraphrase.leaks(SECRET, {"T": text})


def test_verbatim_leak():
    assert found("The harbourmaster secretly sells the lantern keys to the smugglers.")


def test_light_paraphrase():
    assert found("Smugglers buy lantern keys, secretly sold by the harbourmaster.")


def test_unrelated_text():
    assert not found("The baker sells warm bread near the market every morning.")


def test_thin_secret_is_not_scored_but_is_listed():
    assert not paraphrase.leaks({"S": "Bran lies"}, {"T": "Bran lies"})
    assert paraphrase.unscored({"S": "Bran lies", "T": SECRET["S1"]}) == ["S"]


def test_inflections_meet_their_base():
    pairs = (("house", "houses"), ("hate", "hated"), ("cave", "caves"), ("spy", "spies"))
    for base, inflected in pairs:
        assert paraphrase.lemmas(base) == paraphrase.lemmas(inflected), (base, inflected)
    assert paraphrase.lemmas("boss") != paraphrase.lemmas("bos")  # a double s is not a plural


def test_accents_and_possessives_fold():
    secret = {"S": "Éloïse Marchand hides the admiral's ledger"}
    assert paraphrase.leaks(secret, {"T": "eloise marchand hid ledgers of the admiral"})
    assert paraphrase.lemmas("l'amiral Éloïse") == {"amiral"} | paraphrase.lemmas("eloise")
    assert paraphrase.lemmas("Mira's key") == {"mira", "key"}
