"""The Gemini pass, driven against a fake transport.

No Gemini endpoint has ever been reached from this sandbox (`docs/10 §6`), so
everything here stops at the boundary: a fake `httpx` transport answers with
envelopes shaped like the real API's, and what is asserted is our behaviour
given those answers - never Gemini's behaviour.

The tests are ordered by what would hurt most if it broke:

1. an unsourced claim is dropped rather than stored with an empty column;
2. an empty answer is a success, not a failure, because for most small waters
   it is the true answer;
3. no API key skips the job instead of failing it;
4. a refresh supersedes rather than overwrites;
5. nothing collected here can carry a weight, a score or a coefficient.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base, Job, Lake, WaterFact
from app.intel import gemini
from app.intel import service as intel_service
from app.intel.facts import TOPICS, is_usable_source, parse_facts
from app.jobs import handlers

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: pathlib.Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'intel.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def lake(db: Session) -> Lake:
    row = Lake(
        slug="jezioro-testowe",
        name="Jezioro Testowe",
        centroid_lat=52.6,
        centroid_lon=20.5,
        area_ha=9.0,
        timezone="Europe/Warsaw",
        created_at="2026-08-19T00:00:00+00:00",
    )
    db.add(row)
    db.flush()
    return row


def envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """A Gemini generateContent response carrying `payload` as its JSON text."""
    return {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps(payload)}]}, "finishReason": "STOP"}
        ]
    }


def fake_client(
    answer: dict[str, Any], *, status: int = 200, head_status: int = 200
) -> httpx.Client:
    """An httpx client that answers generateContent, and HEADs the sources."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(head_status)
        return httpx.Response(status, json=answer)

    return httpx.Client(transport=httpx.MockTransport(handler))


CONFIG = gemini.GeminiConfig(api_key="test-key", model="gemini-test")

SOURCED = {
    "topic": "species",
    "key": "roach",
    "value": "Roach are the dominant cyprinid here.",
    "source_url": "https://pzw.example.org/jezioro-testowe",
    "source_title": "PZW okreg",
    "confidence": "high",
}


# --------------------------------------------------------------------------
# What is a fact
# --------------------------------------------------------------------------


def test_a_claim_with_no_source_is_dropped() -> None:
    """The single rule the whole module exists for."""
    kept, rejected = parse_facts(
        {
            "facts": [
                SOURCED,
                {**SOURCED, "key": "bream", "source_url": ""},
                {**SOURCED, "key": "tench", "source_url": "not a url"},
                {**SOURCED, "key": "carp", "source_url": "ftp://old.example.org/x"},
            ]
        }
    )
    assert [f.key for f in kept] == ["roach"]
    assert len(rejected) == 3


@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://pzw.example.org/a", True),
        ("http://pzw.example.org/a", True),
        ("https://localhost/a", False),  # no dot: not a public page
        ("javascript:alert(1)", False),
        ("", False),
    ],
)
def test_source_shape(url: str, ok: bool) -> None:
    assert is_usable_source(url) is ok


def test_an_unknown_topic_cannot_get_in() -> None:
    """The closed topic list is what keeps a coefficient out (ADR 0005 §2)."""
    kept, rejected = parse_facts(
        {
            "facts": [
                {**SOURCED, "topic": "weights", "key": "pressure_weight", "value": "0.4"},
                {**SOURCED, "topic": "score", "key": "zone_multiplier", "value": "1.2"},
                {**SOURCED, "topic": "best_times", "key": "dawn", "value": "05:00"},
            ]
        }
    )
    assert kept == []
    assert len(rejected) == 3
    assert "weights" not in TOPICS and "score" not in TOPICS


def test_an_unstated_confidence_is_the_lowest_one() -> None:
    kept, _ = parse_facts({"facts": [{**SOURCED, "confidence": ""}]})
    assert kept[0].confidence == "low"


def test_duplicates_are_collapsed() -> None:
    kept, rejected = parse_facts({"facts": [SOURCED, {**SOURCED, "key": "Roach"}]})
    assert len(kept) == 1
    assert any("duplicate" in r for r in rejected)


def test_a_non_answer_is_reported_not_crashed() -> None:
    assert parse_facts("nope") == ([], ["answer was not a JSON object"])
    assert parse_facts({})[1] == ["answer carried no 'facts' list"]


# --------------------------------------------------------------------------
# The client
# --------------------------------------------------------------------------


def test_no_api_key_is_a_state_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FISHLOG_GEMINI_API_KEY", raising=False)
    assert gemini.load_config() is None
    assert gemini.is_configured() is False


def test_the_model_id_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """It is the part that goes stale, so it must not need a code change."""
    monkeypatch.setenv("FISHLOG_GEMINI_API_KEY", "k")
    monkeypatch.delenv("FISHLOG_GEMINI_MODEL", raising=False)
    assert gemini.load_config() is not None
    assert gemini.load_config().model == gemini.DEFAULT_MODEL  # type: ignore[union-attr]
    monkeypatch.setenv("FISHLOG_GEMINI_MODEL", "gemini-next")
    assert gemini.load_config().model == "gemini-next"  # type: ignore[union-attr]


def test_the_request_pins_json_and_zero_temperature() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "HEAD":
            return httpx.Response(200)
        return httpx.Response(200, json=envelope({"facts": [SOURCED]}))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        gemini.collect(CONFIG, name="Jezioro Testowe", lat=52.6, lon=20.5, client=client)

    post = next(r for r in seen if r.method == "POST")
    body = json.loads(post.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["temperature"] == 0.0
    assert body["generationConfig"]["responseSchema"]["required"] == ["facts"]
    assert post.headers["x-goog-api-key"] == "test-key"
    assert "gemini-test:generateContent" in str(post.url)


def test_the_prompt_makes_an_empty_answer_acceptable() -> None:
    """Without this line the model invents rather than returning nothing."""
    prompt = gemini.build_prompt("Jezioro Testowe", 52.6, 20.5)
    assert "empty" in prompt.lower()
    assert "url" in prompt.lower()


def test_a_refused_call_raises_with_the_status_in_it() -> None:
    with fake_client({"error": "quota"}, status=429) as client:
        with pytest.raises(gemini.GeminiError, match="429"):
            gemini.collect(CONFIG, name="X", lat=1.0, lon=1.0, client=client)


def test_a_blocked_answer_says_which_layer_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(gemini.GeminiError, match="no candidates"):
            gemini.collect(CONFIG, name="X", lat=1.0, lon=1.0, client=client)


def test_a_dead_source_is_marked_but_the_fact_is_kept() -> None:
    with fake_client(envelope({"facts": [SOURCED]}), head_status=404) as client:
        collection = gemini.collect(
            CONFIG, name="X", lat=1.0, lon=1.0, client=client
        )
    assert len(collection.facts) == 1
    assert collection.source_ok[SOURCED["source_url"]] is False


def test_a_source_check_that_cannot_run_drops_nothing() -> None:
    """Our own machine being offline is not evidence against a citation."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            raise httpx.ConnectError("no network here")
        return httpx.Response(200, json=envelope({"facts": [SOURCED]}))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collection = gemini.collect(CONFIG, name="X", lat=1.0, lon=1.0, client=client)
    assert len(collection.facts) == 1
    assert collection.source_ok == {}


def test_a_403_on_head_is_not_taken_as_a_dead_link() -> None:
    with fake_client(envelope({"facts": [SOURCED]}), head_status=403) as client:
        collection = gemini.collect(CONFIG, name="X", lat=1.0, lon=1.0, client=client)
    assert collection.source_ok[SOURCED["source_url"]] is True


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------


def test_a_refresh_supersedes_rather_than_overwrites(db: Session, lake: Lake) -> None:
    kept, _ = parse_facts({"facts": [SOURCED]})
    intel_service.store(db, lake.id, kept, model="gemini-test")
    later, _ = parse_facts(
        {"facts": [{**SOURCED, "value": "Roach and bream, roach dominant."}]}
    )
    intel_service.store(db, lake.id, later, model="gemini-test")

    all_rows = list(db.execute(select(WaterFact)).scalars().all())
    standing = intel_service.current_facts(db, lake.id)
    assert len(all_rows) == 2, "the old claim was overwritten instead of superseded"
    assert len(standing) == 1
    assert standing[0].value.endswith("roach dominant.")


def test_an_empty_pass_still_supersedes(db: Session, lake: Lake) -> None:
    """Otherwise last month's claims silently present as this month's."""
    kept, _ = parse_facts({"facts": [SOURCED]})
    intel_service.store(db, lake.id, kept, model="gemini-test")
    intel_service.store(db, lake.id, [], model="gemini-test")
    assert intel_service.current_facts(db, lake.id) == []


def test_stored_facts_are_unverified_and_stay_out_of_the_score(
    db: Session, lake: Lake
) -> None:
    kept, _ = parse_facts({"facts": [SOURCED]})
    intel_service.store(db, lake.id, kept, model="gemini-test")
    row = intel_service.current_facts(db, lake.id)[0]
    assert row.verified_by_owner == 0
    assert row.model == "gemini-test"
    # It lives in its own table, not in the weather or derived tables (law 4).
    assert row.__tablename__ == "water_fact"


def test_facts_are_grouped_in_topic_order(db: Session, lake: Lake) -> None:
    kept, _ = parse_facts(
        {
            "facts": [
                {**SOURCED, "topic": "rules", "key": "permit"},
                {**SOURCED, "topic": "species", "key": "roach"},
                {**SOURCED, "topic": "depth", "key": "max"},
            ]
        }
    )
    intel_service.store(db, lake.id, kept, model="gemini-test")
    assert list(intel_service.facts_by_topic(db, lake.id)) == ["species", "depth", "rules"]


# --------------------------------------------------------------------------
# The job
# --------------------------------------------------------------------------


def _job(db: Session, lake: Lake) -> Job:
    job = Job(
        lake_id=lake.id,
        kind=handlers.INTEL,
        state="running",
        attempts=1,
        run_after="2026-08-19T00:00:00+00:00",
        created_at="2026-08-19T00:00:00+00:00",
    )
    db.add(job)
    db.flush()
    return job


def test_the_job_skips_rather_than_fails_without_a_key(
    db: Session, lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deployment that has not switched this on is not a broken water."""
    monkeypatch.delenv("FISHLOG_GEMINI_API_KEY", raising=False)
    outcome = handlers.handle_intel(db, _job(db, lake))
    assert "skipped" in outcome
    assert intel_service.current_facts(db, lake.id) == []


def test_the_job_stores_what_it_collected(
    db: Session, lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FISHLOG_GEMINI_API_KEY", "k")
    monkeypatch.setenv("FISHLOG_GEMINI_MODEL", "gemini-test")

    def fake_collect(config: gemini.GeminiConfig, **kwargs: Any) -> gemini.Collection:
        facts, rejected = parse_facts(
            {"facts": [SOURCED, {**SOURCED, "key": "bream", "source_url": ""}]}
        )
        return gemini.Collection(
            facts=facts,
            rejected=rejected,
            model=config.model,
            source_ok={SOURCED["source_url"]: True},
        )

    monkeypatch.setattr(gemini, "collect", fake_collect)
    outcome = handlers.handle_intel(db, _job(db, lake))
    assert "1 facts stored" in outcome
    assert "1 dropped" in outcome
    stored = intel_service.current_facts(db, lake.id)
    assert [f.key for f in stored] == ["roach"]
    assert stored[0].source_ok == 1


def test_the_job_is_last_in_the_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing waits on it, and it is the only step that costs money."""
    assert handlers.NEW_WATER_PIPELINE[-1] == handlers.INTEL
    assert handlers.INTEL in handlers.HANDLERS
