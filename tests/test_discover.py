"""Adding a water: dedupe, quota, slugs, and what the pipeline queues.

None of the network is touched. Nominatim's parsing is tested against captured
response shapes, and everything downstream takes a `Candidate` - so the whole
add path is exercised without a single request, which is also the only way it
could be tested from this sandbox at all (docs/10 §6).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base, Job, Lake
from app.core.time import iso, utcnow
from app.discover import service
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
    candidate = _to_candidate(
        {
            "lat": "52.4500",
            "lon": "21.0500",
            "class": "natural",
            "type": "water",
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
            "class": "place",
            "type": "village",
            "osm_type": "node",
            "osm_id": 9,
            "display_name": "Białe, Poland",
        }
    )
    assert candidate is not None
    assert not candidate.is_water


def test_a_result_with_no_coordinates_is_dropped() -> None:
    assert _to_candidate({"class": "natural", "type": "water"}) is None


def test_a_missing_bounding_box_is_not_an_area_of_zero() -> None:
    assert _area_ha_from_bbox(None) is None
    assert _area_ha_from_bbox(["52.0", "52.0", "21.0", "21.0"]) is None


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------


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
