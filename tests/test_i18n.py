from app.core.i18n import DEFAULT_LANGUAGE, LANGUAGES, language_names, normalise, translate


def test_every_language_loads_and_names_itself():
    names = dict(language_names())
    assert set(names) == set(LANGUAGES)
    assert names["en"] == "English"
    assert names["pl"] == "Polski"
    assert names["ru"] == "Русский"


def test_translation_differs_per_language():
    values = {translate(lang, "nav.places") for lang in LANGUAGES}
    assert len(values) == len(LANGUAGES), f"languages share a string: {values}"


def test_unknown_language_falls_back_to_default():
    assert normalise("de") == DEFAULT_LANGUAGE
    assert normalise(None) == DEFAULT_LANGUAGE
    assert translate("de", "nav.places") == translate(DEFAULT_LANGUAGE, "nav.places")


def test_unknown_key_returns_the_key_rather_than_blank():
    """A visible key in the UI is a better bug report than an empty label."""
    assert translate("pl", "no.such.key") == "no.such.key"


def _flatten(node: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys |= _flatten(value, path)
        else:
            keys.add(path)
    return keys


def test_translations_cover_every_english_key():
    """A missing key silently falls back to English, which reads as a bug to
    the angler. Catch the gap here instead."""
    from app.core.i18n import _catalogue

    english = _flatten(_catalogue("en"))
    for lang in LANGUAGES:
        missing = english - _flatten(_catalogue(lang))
        assert not missing, f"{lang} is missing: {sorted(missing)}"
