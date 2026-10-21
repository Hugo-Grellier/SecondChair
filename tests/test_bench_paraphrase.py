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


def test_thin_secret_is_not_scored():
    assert not paraphrase.leaks({"S": "Bran lies"}, {"T": "Bran lies"})
