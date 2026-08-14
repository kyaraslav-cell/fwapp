from __future__ import annotations

from typing import Any

from app.core.config import CONFIG_DIR, load_yaml

LANGUAGES = ("en", "pl", "ru")
DEFAULT_LANGUAGE = "en"
COOKIE_NAME = "fishlog_lang"

_catalogues: dict[str, dict[str, Any]] = {}


def _catalogue(lang: str) -> dict[str, Any]:
    if lang not in _catalogues:
        _catalogues[lang] = load_yaml(CONFIG_DIR / "i18n" / f"{lang}.yaml")
    return _catalogues[lang]


def normalise(lang: str | None) -> str:
    return lang if lang in LANGUAGES else DEFAULT_LANGUAGE


def language_names() -> list[tuple[str, str]]:
    return [(code, str(_catalogue(code)["language_name"])) for code in LANGUAGES]


def translate(lang: str, key: str) -> str:
    """Look up a dotted key, e.g. 'session.log_catch'.

    Falls back to English for a key a translation has not caught up with, and
    to the key itself if it exists nowhere - a visible key in the UI is a
    better bug report than a silent blank.
    """
    for candidate in (normalise(lang), DEFAULT_LANGUAGE):
        node: Any = _catalogue(candidate)
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
        if isinstance(node, str):
            return node.strip()
    return key
