"""Asking Gemini what is publicly known about one water, and believing little of it.

Shaped deliberately like `app/auth/google.py`: the key lives in the environment,
"not configured" is a state rather than an error, and nothing here ever falls
back to something that looks like it worked.

    load_config()  ->  None means no key, which is not a failure
    collect(...)   ->  a list of Facts and a list of reasons things were dropped

**Strict JSON, not prose.** The request pins `responseMimeType` to
`application/json` and hands the API a `responseSchema`, so the answer arrives
as a shape rather than as a paragraph to be regex-mined. Temperature is 0: this
is a lookup, and there is nothing here that creativity improves.

**The source URL is the whole design, and its weakness is known.** The prompt
demands one per claim and `app/intel/facts.py` drops any claim without one. But
a model answering without a search tool can write a URL that has never existed,
and it will look exactly like one that has. So:

- each unique URL is HEAD-checked once after the answer comes back, and the
  outcome is stored per fact (`source_ok`: 1 reachable, 0 refused, NULL never
  checked);
- a check that could not run - no network, DNS down, our own sandbox - leaves
  NULL and drops nothing. Discarding somebody's local knowledge because *our*
  machine is offline would be the wrong failure;
- nothing collected here reaches the score under any circumstances, checked or
  not. It is shown to the angler, marked as unverified, and stays that way
  until a human says otherwise (`docs/13 §10`).

Never reached from the build sandbox (`docs/10 §6`). Tested against a fake
transport; the first real call happens on the owner's machine.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, replace
from typing import Any

import httpx

from app.intel.facts import CONFIDENCE, MAX_KEY_CHARS, MAX_VALUE_CHARS, TOPICS, Fact, parse_facts

logger = logging.getLogger("fishlog.intel.gemini")

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.5-flash"
TIMEOUT_S = 60.0
SOURCE_CHECK_TIMEOUT_S = 8.0
# Was 24. A page of one fact per stocked species read as a data dump rather
# than a briefing - the owner's word was "essentials". Rule 8 below folds
# stocking into one fact, so this cap now bounds the five substantive topics.
MAX_FACTS = 14

# The languages the rest of the site already switches between (`app/core/i18n.py`).
# Facts are collected once in English, then this module's own translation call
# - not a second research pass - produces the other two, so every language
# shows the same claims from the same sources.
TRANSLATABLE_LANGUAGES: tuple[tuple[str, str], ...] = (("pl", "Polish"), ("ru", "Russian"))


class GeminiNotConfiguredError(RuntimeError):
    """No API key in the environment. The pass is skipped, not failed."""


class GeminiError(RuntimeError):
    """Gemini answered, and the answer was not usable."""


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str
    model: str


@dataclass(frozen=True)
class Collection:
    """What one pass produced, including what it threw away."""

    facts: list[Fact]
    rejected: list[str]
    model: str
    source_ok: dict[str, bool]


def load_config() -> GeminiConfig | None:
    """Read the environment. None means "not set up", which is not a failure.

    The model id is configurable because it is the part that goes stale: a
    default that no longer exists should be a one-line environment change on
    the owner's machine, not a code change and a redeploy.
    """
    api_key = os.environ.get("FISHLOG_GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.environ.get("FISHLOG_GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    return GeminiConfig(api_key=api_key, model=model)


def is_configured() -> bool:
    return load_config() is not None


# The shape the answer must arrive in. A flat list rather than a nested profile
# so that one unsourced claim is dropped on its own instead of taking a whole
# section with it.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "facts": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "topic": {"type": "STRING", "enum": list(TOPICS)},
                    "key": {"type": "STRING"},
                    "value": {"type": "STRING"},
                    "source_url": {"type": "STRING"},
                    "source_title": {"type": "STRING"},
                    "confidence": {"type": "STRING", "enum": list(CONFIDENCE)},
                },
                "required": ["topic", "key", "value", "source_url", "confidence"],
            },
        }
    },
    "required": ["facts"],
}


def build_prompt(name: str, lat: float, lon: float, country: str = "Poland") -> str:
    """The instruction, written to make "I found nothing" an acceptable answer.

    Most waters this app will be pointed at are small enough that the honest
    answer is an empty list, and a prompt that does not say so out loud gets a
    confident invention instead - which is the single failure mode that would
    make this whole feature worse than not having it.
    """
    return (
        f"Collect only what is publicly documented about the fishing water "
        f'"{name}" at latitude {lat:.5f}, longitude {lon:.5f}, in {country}.\n\n'
        "Rules, all of them binding:\n"
        "1. Every fact must come from a specific web page you can cite by URL. "
        "If you cannot cite a page, do not state the fact.\n"
        "2. Do not generalise from other waters, from the region, or from the "
        "name. A fact about a different lake with a similar name is not a fact "
        "about this one.\n"
        "3. If you find nothing about this specific water, return an empty "
        "facts list. That is a correct and useful answer - it is much better "
        "than a plausible one.\n"
        "4. State no recommendations, no tactics, no scores, no weights and no "
        "best times. Facts about the water only: which species are present, "
        "depths, bottom composition, bank access, permits and local rules, "
        "stocking.\n"
        "5. `confidence` is high only for an official or authoritative page "
        "(the angling club, the operator, a public register), medium for a "
        "reputable secondary source, low for a forum post or a listing site.\n"
        "6. Answer in English. Keep each value under 300 characters.\n"
        f"7. At most {MAX_FACTS} facts.\n"
        "8. This is a short briefing, not a data dump: pick what would "
        "actually change an angler's plan for a session, drop the rest. For "
        "`stocking`, one fact summarising the plan (what is stocked, roughly "
        "how much, how often) beats a row per species - never state more than "
        "one `stocking` fact."
    )


def _request_body(prompt: str, schema: dict[str, Any] = RESPONSE_SCHEMA) -> dict[str, Any]:
    return {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            # A lookup, not a composition. Nothing here is improved by variety.
            "temperature": 0.0,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }


def _text_of(payload: dict[str, Any]) -> str:
    """Dig the JSON string out of the response envelope, or say what is wrong.

    The envelope is nested enough that a missing key here would otherwise
    surface as a `KeyError` in a job log with no indication of which layer
    refused - a blocked answer and a quota refusal look identical then.
    """
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        reason = payload.get("promptFeedback", {})
        raise GeminiError(f"no candidates in the answer ({json.dumps(reason)[:200]})")
    parts = candidates[0].get("content", {}).get("parts")
    if not isinstance(parts, list) or not parts:
        finish = candidates[0].get("finishReason", "unknown")
        raise GeminiError(f"candidate carried no content (finishReason={finish})")
    text = str(parts[0].get("text") or "").strip()
    if not text:
        raise GeminiError("candidate carried an empty text part")
    return text


def check_sources(urls: list[str], client: httpx.Client | None = None) -> dict[str, bool]:
    """HEAD each URL once. Absent from the result means "could not check".

    Fails open on purpose. A source that our machine cannot reach is not
    thereby a fabrication - it may be behind Cloudflare, refuse HEAD, or simply
    be unreachable from wherever this container is. Only a definite 404 or 410
    is recorded as a refusal.
    """
    outcome: dict[str, bool] = {}
    owned = client is None
    session = client or httpx.Client(
        timeout=SOURCE_CHECK_TIMEOUT_S, follow_redirects=True
    )
    try:
        for url in urls:
            try:
                response = session.head(url)
            except Exception as exc:  # noqa: BLE001 - any transport failure is "unknown"
                logger.info("source check could not run for %s: %s", url, exc)
                continue
            if response.status_code in (404, 410):
                outcome[url] = False
            elif response.status_code < 400 or response.status_code in (403, 405, 429):
                # 403/405/429 mean the page exists and did not want a HEAD from
                # us, which is not evidence against the citation.
                outcome[url] = True
    finally:
        if owned:
            session.close()
    return outcome


def collect(
    config: GeminiConfig,
    *,
    name: str,
    lat: float,
    lon: float,
    client: httpx.Client | None = None,
) -> Collection:
    """One pass. Raises `GeminiError` for anything that is not a usable answer."""
    owned = client is None
    session = client or httpx.Client(timeout=TIMEOUT_S)
    try:
        response = session.post(
            f"{API_ROOT}/{config.model}:generateContent",
            headers={"x-goog-api-key": config.api_key},
            json=_request_body(build_prompt(name, lat, lon)),
        )
        if response.status_code != 200:
            raise GeminiError(
                f"generateContent returned {response.status_code}: "
                f"{response.text[:300]}"
            )
        envelope: dict[str, Any] = response.json()
    finally:
        if owned:
            session.close()

    text = _text_of(envelope)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GeminiError(f"answer was not JSON despite the schema: {exc}") from exc

    facts, rejected = parse_facts(payload)
    if len(facts) > MAX_FACTS:
        rejected.append(f"{len(facts) - MAX_FACTS} facts past the cap of {MAX_FACTS}")
        facts = facts[:MAX_FACTS]

    source_ok = check_sources(sorted({f.source_url for f in facts}), client=client)
    return Collection(
        facts=facts, rejected=rejected, model=config.model, source_ok=source_ok
    )


# Translation, not a second research pass. `id` round-trips each item so a
# reordered or partially-dropped answer still lines back up with the right
# fact instead of silently pairing the wrong key with the wrong value.
TRANSLATE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "INTEGER"},
                    "key": {"type": "STRING"},
                    "value": {"type": "STRING"},
                },
                "required": ["id", "key", "value"],
            },
        }
    },
    "required": ["items"],
}


def build_translate_prompt(facts: list[Fact], language_name: str) -> str:
    items = [{"id": i, "key": f.key, "value": f.value} for i, f in enumerate(facts)]
    return (
        f"Translate the `key` and `value` of each item below into natural, "
        f"fluent {language_name}, for an angler reading a fishing app. Keep "
        f"the meaning exact - translate the wording only, do not add, remove "
        f"or guess at anything. Species names, numbers and units must stay "
        f"accurate. Return every `id` exactly once.\n\n"
        f"{json.dumps(items, ensure_ascii=False)}"
    )


def translate_facts(
    config: GeminiConfig,
    facts: list[Fact],
    lang: str,
    language_name: str,
    *,
    client: httpx.Client | None = None,
) -> list[Fact]:
    """`facts` (lang="en") -> the same claims, same sources, in `lang`.

    Topic, source_url, source_title and confidence are copied through
    unchanged - only wording is asked for, so only wording can come back
    different. An item the model drops or answers with an empty key/value is
    left out rather than falling back to English silently mislabelled as
    `lang`; a caller that wants every language populated should treat a short
    result as partial, not fail the whole pass over it.
    """
    if not facts:
        return []

    owned = client is None
    session = client or httpx.Client(timeout=TIMEOUT_S)
    try:
        response = session.post(
            f"{API_ROOT}/{config.model}:generateContent",
            headers={"x-goog-api-key": config.api_key},
            json=_request_body(
                build_translate_prompt(facts, language_name), TRANSLATE_SCHEMA
            ),
        )
        if response.status_code != 200:
            raise GeminiError(
                f"translate returned {response.status_code}: {response.text[:300]}"
            )
        envelope: dict[str, Any] = response.json()
    finally:
        if owned:
            session.close()

    text = _text_of(envelope)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GeminiError(f"translation was not JSON despite the schema: {exc}") from exc

    items = payload.get("items")
    if not isinstance(items, list):
        raise GeminiError("translation carried no 'items' list")

    by_id: dict[int, tuple[str, str]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        try:
            idx = int(raw["id"])
        except (KeyError, TypeError, ValueError):
            continue
        key = str(raw.get("key") or "").strip()[:MAX_KEY_CHARS]
        value = str(raw.get("value") or "").strip()[:MAX_VALUE_CHARS]
        if key and value:
            by_id[idx] = (key, value)

    translated: list[Fact] = []
    for i, fact in enumerate(facts):
        pair = by_id.get(i)
        if pair is None:
            continue
        key, value = pair
        translated.append(replace(fact, key=key, value=value, lang=lang))
    return translated
