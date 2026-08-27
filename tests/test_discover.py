"""Adding a water: dedupe, quota, slugs, and what the pipeline queues.

None of the network is touched. Nominatim's parsing is tested against captured
response shapes, and everything downstream takes a `Candidate` - so the whole
add path is exercised without a single request, which is also the only way it
could be tested from this sandbox at all (docs/10 §6).
"""

from __future__ import annotations

import pathlib
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base, Job, Lake
from app.core.time import iso, utcnow
from app.discover import nominatim, service
from app.discover.nominatim import Candidate, _area_ha_from_bbox, _to_candidate
from app.geo.service import cell_size_for_area
from app.jobs.handlers import NEW_WATER_PIPELINE


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def water(
    name: str = "Jezioro Zegrzyńskie",
    lat: float = 52.45,
    lon: float = 21.05,
    osm_id: int = 111,
    is_water: bool = True,
) -> Candidate:
    return Candidate(
        name=name,
        display_name=f"{name}, Poland",
        lat=lat,
        lon=lon,
        osm_type="way",
        osm_id=osm_id,
        kind="natural=water",
        area_ha=3000.0,
        is_water=is_water,
    )


# ---------------------------------------------------------------------------
# Parsing what the geocoder sends
# ---------------------------------------------------------------------------


def test_a_lake_result_is_recognised_as_water() -> None:
    """The row is shaped as **jsonv2** sends it, which is what we ask for.

    This test used to say `"class"`, because that is what the parser read - a
    fixture written to match the code instead of the API. jsonv2 renames that
    field to `category`, so in production every result parsed with an empty
    category, matched no water type, and was refused as "not a water". Zalew
    Zegrzynski - 3 300 ha, mapped, unmistakable - could not be added.

    The lesson, and the reason this docstring is long: a fake that is built
    from the same assumption as the code under test asserts the assumption, not
    the behaviour. When a fixture stands in for a service nobody here can
    reach, its field names have to come from that service's documentation.
    """
    candidate = _to_candidate(
        {
            "lat": "52.4500",
            "lon": "21.0500",
            # jsonv2. NOT "class" - see the docstring.
            "category": "natural",
            "type": "water",
            "place_rank": 22,
            "osm_type": "way",
            "osm_id": 123,
            "display_name": "Jezioro Zegrzyńskie, powiat legionowski, Poland",
            "boundingbox": ["52.40", "52.48", "21.00", "21.12"],
        }
    )
    assert candidate is not None
    assert candidate.is_water
    assert candidate.name == "Jezioro Zegrzyńskie"
    assert candidate.area_ha and candidate.area_ha > 1000


def test_a_village_with_a_lake_name_is_not_water() -> None:
    """Half the lakes in Poland share their name with the village beside them."""
    candidate = _to_candidate(
        {
            "lat": "52.1",
            "lon": "21.1",
            "category": "place",
            "type": "village",
            "osm_type": "node",
            "osm_id": 9,
            "display_name": "Białe, Poland",
        }
    )
    assert candidate is not None
    assert not candidate.is_water


def test_search_offers_waters_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """The picker is for waters. Villages and streets never reach it.

    Non-water results used to be kept and merely marked. Searching a Polish
    lake's name returns the village, the gmina and the street of that name
    first, so the angler had to read OSM tag labels to find the lake. The
    server-side refusal for a hand-crafted POST stays either way - see
    `test_a_village_cannot_be_added_as_a_water`.
    """
    rows = [
        {
            "lat": "52.1", "lon": "21.1", "category": "place", "type": "village",
            "osm_type": "node", "osm_id": 9, "display_name": "Zegrze, Poland",
        },
        {
            "lat": "52.45", "lon": "21.05", "category": "natural", "type": "water",
            "osm_type": "relation", "osm_id": 2,
            "display_name": "Zalew Zegrzynski, Poland",
            "boundingbox": ["52.40", "52.48", "21.00", "21.12"],
        },
        {
            "lat": "52.2", "lon": "21.2", "category": "highway", "type": "residential",
            "osm_type": "way", "osm_id": 7, "display_name": "ulica Zegrzynska, Poland",
        },
    ]
    monkeypatch.setattr(nominatim, "_cache", {})
    monkeypatch.setattr(nominatim, "_throttle", lambda: None)

    class _Response:
        status_code = 200

        @staticmethod
        def json() -> list[dict[str, object]]:
            return rows

    class _Client:
        def __init__(self, *a: object, **kw: object) -> None: ...
        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *a: object) -> None: ...
        def get(self, *a: object, **kw: object) -> _Response:
            return _Response()

    monkeypatch.setattr(nominatim.httpx, "Client", _Client)

    results = nominatim.search("Zegrzynski")

    assert [c.name for c in results] == ["Zalew Zegrzynski"]
    assert all(c.is_water for c in results)


def test_a_canal_is_a_water() -> None:
    """The bug the owner found: Kanal Zeranski could not be searched for.

    `waterway=canal` was missing from an exhaustive allowlist of tag pairs.
    That was survivable while non-water results were still shown and marked;
    once the picker became waters-only it meant an empty page for a real PZW
    water in the Zegrzynski district.
    """
    candidate = _to_candidate(
        {
            "lat": "52.3200",
            "lon": "20.9900",
            "category": "waterway",
            "type": "canal",
            "osm_type": "way",
            "osm_id": 42,
            "display_name": "Kanał Żerański, Białołęka, Warszawa, Poland",
        }
    )
    assert candidate is not None
    assert candidate.is_water


@pytest.mark.parametrize(
    ("category", "type_name", "expected"),
    [
        ("waterway", "canal", True),
        ("waterway", "river", True),
        ("waterway", "riverbank", True),
        ("waterway", "ditch", True),
        ("water", "lake", True),
        ("water", "pond", True),
        ("water", "oxbow", True),
        ("natural", "water", True),
        ("landuse", "reservoir", True),
        ("landuse", "basin", True),
        ("leisure", "fishing", True),
        # ...and the things that are emphatically not water
        ("place", "village", False),
        ("place", "town", False),
        ("highway", "residential", False),
        ("boundary", "administrative", False),
        ("natural", "wood", False),
        ("landuse", "forest", False),
        ("leisure", "pitch", False),
        ("leisure", "park", False),
        ("waterway", "weir", False),
        ("waterway", "dam", False),
    ],
)
def test_the_water_rule_fails_open_but_not_daft(
    category: str, type_name: str, expected: bool
) -> None:
    """Wrong-and-wide shows one odd row. Wrong-and-narrow hides a water."""
    assert nominatim.is_water_tag(category, type_name) is expected


def test_a_result_with_no_coordinates_is_dropped() -> None:
    assert _to_candidate({"category": "natural", "type": "water"}) is None


def test_the_older_class_field_is_still_understood() -> None:
    """`format=json` and older mirrors send `class`. Both are read.

    Not for compatibility's sake: for the next time somebody changes the format
    parameter. A parser that silently marks every water as not-a-water is the
    worst possible failure here, because it looks like a data problem at the
    other end.
    """
    candidate = _to_candidate(
        {"lat": "52.4", "lon": "21.0", "class": "natural", "type": "water"}
    )
    assert candidate is not None and candidate.is_water


def test_the_kind_string_names_the_tag_that_was_refused() -> None:
    """What the picker shows when it refuses, so the reason is legible."""
    candidate = _to_candidate(
        {"lat": "52.1", "lon": "21.1", "category": "place", "type": "village"}
    )
    assert candidate is not None
    assert candidate.kind == "place=village"


def test_a_missing_bounding_box_is_not_an_area_of_zero() -> None:
    assert _area_ha_from_bbox(None) is None
    assert _area_ha_from_bbox(["52.0", "52.0", "21.0", "21.0"]) is None


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------


def test_a_listed_water_is_typed_and_named_from_the_permit(db: Session) -> None:
    """One tap: the okreg's list already answers both questions."""
    result = service.add_water(db, water(name="Zalew Zegrzyński"), user_id=1)

    assert result.lake.water_type == "pzw"
    assert result.lake.water_type_source == service.SOURCE_REGISTRY
    # The fixture's coordinates fall inside the okreg map's Zegrzynskie
    # boundary, so this resolves by position rather than by name - which is
    # the stronger answer and the point of carrying boundaries at all.
    assert result.lake.name == "Jezioro Zegrzyńskie", "PZW's spelling is the one shown"
    assert result.lake.name_osm == "Zalew Zegrzyński", "and OSM's is kept, not discarded"


def test_an_unlisted_water_takes_the_anglers_answer(db: Session) -> None:
    result = service.add_water(
        db,
        water(name="Łowisko Poniaty - Pod Lasem", lat=52.6229547, lon=20.8875144),
        user_id=1,
        water_type="commercial",
    )

    assert result.lake.water_type == "commercial"
    assert result.lake.water_type_source == service.SOURCE_ANGLER
    assert result.lake.name == "Łowisko Poniaty - Pod Lasem"
    assert result.lake.name_osm is None, "nothing was renamed, so there is no alias to keep"


def test_the_angler_overrules_the_registry(db: Session) -> None:
    """A name match with no coordinates behind it loses to someone standing there."""
    result = service.add_water(
        db, water(name="Zalew Zegrzyński"), user_id=1, water_type="commercial"
    )

    assert result.lake.water_type == "commercial"
    assert result.lake.water_type_source == service.SOURCE_ANGLER


def test_an_unlisted_water_added_without_an_answer_has_no_type(db: Session) -> None:
    """Blank, not guessed.

    `assert_comparable` refuses to pool CPUE across waters whose type nobody
    recorded, which is the correct outcome. Defaulting to either value here
    would produce a number that looks fine and is wrong (law 3).
    """
    result = service.add_water(
        db, water(name="Łowisko Poniaty - Pod Lasem", lat=52.6229547, lon=20.8875144), user_id=1
    )

    assert result.lake.water_type is None
    assert result.lake.water_type_source is None


def test_the_same_water_is_still_deduped_after_being_renamed(db: Session) -> None:
    """The regression the rename introduced.

    Once a water is stored under its PZW name, a second angler searching OSM
    finds the OSM name - which no longer equals the stored `name`. Without
    checking `name_osm` too, the app fails to recognise a water it added
    itself and creates a duplicate, splitting every statistic about that lake.
    """
    service.add_water(db, water(name="Zalew Zegrzyński", osm_id=111), user_id=1)
    again = service.add_water(
        db, water(name="Zalew Zegrzyński", osm_id=222, lat=52.4503, lon=21.0504), user_id=1
    )

    assert not again.created


def test_polish_letters_survive_slugging(db: Session) -> None:
    """NFKD alone eats the ł entirely and leaves `zegrzy-skie`."""
    assert service.slugify("Jezioro Zegrzyńskie") == "jezioro-zegrzynskie"
    assert service.slugify("Łowisko Wędkarskie") == "lowisko-wedkarskie"
    assert service.slugify("!!!") == "water"


def test_a_second_lake_of_the_same_name_gets_its_own_slug(db: Session) -> None:
    """There are dozens of Jezioro Białe, and they are different lakes."""
    db.add(
        Lake(slug="jezioro-biale", name="Jezioro Białe", centroid_lat=52.0,
             centroid_lon=21.0, timezone="Europe/Warsaw", created_at=iso(utcnow()))
    )
    db.flush()
    assert service.unique_slug(db, "jezioro-biale") == "jezioro-biale-2"


# ---------------------------------------------------------------------------
# Adding
# ---------------------------------------------------------------------------


def test_adding_a_water_queues_the_whole_pipeline(db: Session) -> None:
    result = service.add_water(db, water(), user_id=1)

    assert result.created
    assert result.lake.origin == "discovered"
    assert result.lake.added_by_user_id == 1
    queued = {job.kind for job in db.query(Job).all()}
    assert queued == set(NEW_WATER_PIPELINE)


def test_the_same_water_is_never_added_twice(db: Session) -> None:
    """Two anglers searching the same lake must land on one page, not two."""
    first = service.add_water(db, water(), user_id=1)
    second = service.add_water(db, water(), user_id=2)

    assert not second.created
    assert second.lake.id == first.lake.id
    assert db.query(Lake).count() == 1


def test_the_same_water_is_matched_through_a_different_osm_object(db: Session) -> None:
    """Same name, a few metres apart: one lake reached two ways."""
    service.add_water(db, water(osm_id=111), user_id=1)
    again = service.add_water(db, water(osm_id=222, lat=52.4503, lon=21.0504), user_id=1)

    assert not again.created
    assert db.query(Lake).count() == 1


def test_two_different_lakes_of_the_same_name_are_both_kept(db: Session) -> None:
    service.add_water(db, water(name="Jezioro Białe", lat=52.0, lon=21.0, osm_id=1), user_id=1)
    service.add_water(db, water(name="Jezioro Białe", lat=53.5, lon=22.5, osm_id=2), user_id=1)

    assert db.query(Lake).count() == 2


def test_a_village_cannot_be_added_as_a_water(db: Session) -> None:
    with pytest.raises(service.NotAWaterError):
        service.add_water(db, water(is_water=False), user_id=1)


def test_the_daily_quota_is_enforced_per_account(db: Session) -> None:
    for i in range(service.DAILY_ADD_QUOTA):
        service.add_water(db, water(name=f"Lake {i}", lat=52.0 + i, osm_id=100 + i), user_id=1)

    assert service.quota_left(db, user_id=1) == 0
    with pytest.raises(service.QuotaExceededError):
        service.add_water(db, water(name="One Too Many", lat=60.0, osm_id=999), user_id=1)

    # Another angler is unaffected, and so is the same one tomorrow.
    assert service.quota_left(db, user_id=2) == service.DAILY_ADD_QUOTA
    tomorrow = utcnow() + timedelta(days=1, minutes=1)
    assert service.quota_left(db, user_id=1, now=tomorrow) == service.DAILY_ADD_QUOTA


def test_opening_a_water_that_already_exists_does_not_cost_quota(db: Session) -> None:
    """Otherwise searching for your home lake five times locks you out."""
    service.add_water(db, water(), user_id=1)
    for _ in range(10):
        service.add_water(db, water(), user_id=1)

    assert service.quota_left(db, user_id=1) == service.DAILY_ADD_QUOTA - 1


def test_the_quota_reset_is_reported_only_when_it_matters(db: Session) -> None:
    assert service.next_quota_reset(db, user_id=1) is None
    for i in range(service.DAILY_ADD_QUOTA):
        service.add_water(db, water(name=f"Lake {i}", lat=52.0 + i, osm_id=200 + i), user_id=1)
    assert service.next_quota_reset(db, user_id=1) is not None


# ---------------------------------------------------------------------------
# Grid resolution
# ---------------------------------------------------------------------------


def test_small_waters_keep_the_finest_grid() -> None:
    """Pomocnia must not change resolution because this feature exists."""
    assert cell_size_for_area(9.0) == 5.0
    assert cell_size_for_area(0.4) == 5.0
    assert cell_size_for_area(None) == 5.0


def test_big_waters_get_bigger_cells_and_stay_sendable() -> None:
    """The limit is the JSON handed to a phone, not the CPU."""
    for area_ha in (50, 100, 500, 2000, 10000):
        cell_m = cell_size_for_area(float(area_ha))
        cells = (area_ha * 10_000) / (cell_m**2)
        assert cell_m <= 150.0
        # The number that matters is cells, not metres: this is what gets
        # serialised and sent on every day tap.
        assert cells <= 8_000, f"{area_ha} ha would send {cells:.0f} cells"


def test_cell_size_never_goes_below_the_floor() -> None:
    assert cell_size_for_area(0.001) == 5.0


def test_a_refusal_leaves_the_other_results_on_screen(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Being told "not a water" must not also take away the right answer.

    The correct result is usually one row below the one that was tapped.
    Emptying the list turns one wrong tap into "this app cannot add my lake" -
    which is how the jsonv2 bug was reported, and the reason it took a fortnight
    to look at.

    Driven through the real app: the query has to survive the POST as a hidden
    field for this to work at all, and only the running form proves it does.
    """
    from fastapi.testclient import TestClient

    from app.auth import passwords
    from app.discover import nominatim as nominatim_module

    village = Candidate(
        name="Zegrze",
        display_name="Zegrze, powiat legionowski, Poland",
        lat=52.45,
        lon=21.05,
        osm_type="node",
        osm_id=1,
        kind="place=village",
        area_ha=None,
        is_water=False,
    )
    lake = Candidate(
        name="Zalew Zegrzynski",
        display_name="Zalew Zegrzynski, Poland",
        lat=52.44,
        lon=21.06,
        osm_type="relation",
        osm_id=2,
        kind="natural=water",
        area_ha=3300.0,
        is_water=True,
    )
    monkeypatch.setattr(
        nominatim_module, "search", lambda name, **kw: [village, lake]
    )

    monkeypatch.setenv("FISHLOG_DB_PATH", str(tmp_path / "refusal.db"))
    monkeypatch.setenv("FISHLOG_MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(passwords, "DEFAULT_N", 1 << 12)

    import app.core.db as db_module

    monkeypatch.setattr(db_module, "_engine", None)
    monkeypatch.setattr(db_module, "_SessionLocal", None)

    from app.web import app as app_module

    client = TestClient(app_module.create_app())
    db_module.init_db()
    client.post(
        "/auth/register",
        data={
            "email": "angler@example.com",
            "display_name": "Ann",
            "password": "bream-on-the-margin",
            "password_confirm": "bream-on-the-margin",
        },
        follow_redirects=False,
    )

    response = client.post(
        "/places/new",
        data={
            "q": "Zalew Zegrzynski",
            "name": "Zegrze",
            "display_name": "Zegrze, powiat legionowski, Poland",
            "lat": "52.45",
            "lon": "21.05",
            "osm_type": "node",
            "osm_id": "1",
            "area_ha": "",
            "is_water": "0",
        },
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert "Zalew Zegrzynski" in response.text, (
        "the refusal emptied the list, so the lake one row down was unreachable"
    )
    # And the tag is printed, so a correct refusal is legible as one.
    assert "place=village" in response.text
