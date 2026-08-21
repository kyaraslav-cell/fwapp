"""Large waters: multipolygon relations, split ways, and the search radius.

Written after Zalew Zegrzyński — 3 300 ha, mapped in OpenStreetMap for years —
came back as "no water polygon near this point". Three separate faults, each of
which alone was enough to lose the lake:

1. **Relations were silently skipped.** A way carries a top-level `geometry`;
   a relation does not — its shape is in `members`. The parser read only
   `geometry`, so every multipolygon water produced nothing. That is every
   water with an island, and every water big enough that more than one person
   mapped it.
2. **The outer boundary arrives in pieces.** Even once members are read, none
   of them is a closed ring on its own; they have to be stitched end to end.
3. **The search radius was a fixed 500 m.** Overpass measures `around` to a
   way's geometry, so on a reservoir whose centroid sits a kilometre from any
   bank, nothing is within 500 m of it and the answer is an honest, useless
   empty set.

The element shapes below are as Overpass's `out geom` documents them, not as
our parser happened to want them — which is the mistake that let the jsonv2
field-name bug live (`docs/13 §11`).
"""

from __future__ import annotations

from typing import Any

from app.geo.outline import (
    DEFAULT_RADIUS_M,
    MAX_RADIUS_M,
    _query_by_id,
    _radius_for_area,
    _rings_of,
    _stitch,
)


def pts(*coords: tuple[float, float]) -> list[dict[str, float]]:
    """Overpass geometry: a list of {lat, lon} objects, in that spelling."""
    return [{"lat": lat, "lon": lon} for lon, lat in coords]


# --------------------------------------------------------------------------
# Ways — the shape that already worked, pinned so the rewrite kept it
# --------------------------------------------------------------------------


def test_a_way_still_yields_its_ring() -> None:
    element: dict[str, Any] = {
        "type": "way",
        "id": 1,
        "geometry": pts((21.0, 52.4), (21.1, 52.4), (21.1, 52.5), (21.0, 52.5)),
    }
    rings = _rings_of(element)
    assert len(rings) == 1
    assert rings[0][0] == rings[0][-1], "the ring was not closed"
    assert len(rings[0]) == 5


def test_an_already_closed_way_is_not_closed_twice() -> None:
    element: dict[str, Any] = {
        "type": "way",
        "geometry": pts(
            (21.0, 52.4), (21.1, 52.4), (21.1, 52.5), (21.0, 52.5), (21.0, 52.4)
        ),
    }
    assert len(_rings_of(element)[0]) == 5


def test_a_fragment_too_short_to_be_a_polygon_is_dropped() -> None:
    assert _rings_of({"type": "way", "geometry": pts((21.0, 52.4), (21.1, 52.4))}) == []


# --------------------------------------------------------------------------
# Relations — the shape that produced nothing at all
# --------------------------------------------------------------------------


def test_a_relation_in_one_piece_yields_its_ring() -> None:
    element: dict[str, Any] = {
        "type": "relation",
        "id": 99,
        "tags": {"natural": "water", "water": "reservoir"},
        "members": [
            {
                "type": "way",
                "ref": 1,
                "role": "outer",
                "geometry": pts(
                    (21.0, 52.4), (21.3, 52.4), (21.3, 52.5), (21.0, 52.5), (21.0, 52.4)
                ),
            }
        ],
    }
    rings = _rings_of(element)
    assert len(rings) == 1, "a multipolygon water produced no ring at all"
    assert rings[0][0] == rings[0][-1]


def test_an_outer_boundary_split_across_four_ways_is_stitched() -> None:
    """The real case. No member is closed; the ring only exists once joined."""
    element: dict[str, Any] = {
        "type": "relation",
        "members": [
            {"role": "outer", "geometry": pts((21.0, 52.4), (21.3, 52.4))},
            {"role": "outer", "geometry": pts((21.3, 52.4), (21.3, 52.5))},
            {"role": "outer", "geometry": pts((21.3, 52.5), (21.0, 52.5))},
            {"role": "outer", "geometry": pts((21.0, 52.5), (21.0, 52.4))},
        ],
    }
    rings = _rings_of(element)
    assert len(rings) == 1
    assert rings[0][0] == rings[0][-1]
    assert len(rings[0]) == 5, "the four fragments did not join into one ring"


def test_a_member_digitised_backwards_is_reversed_rather_than_dropped() -> None:
    """Mappers draw ways in whichever direction suits them; OSM does not care.

    A stitcher that only joins head-to-tail loses roughly half of any real
    boundary, and loses it silently.
    """
    element: dict[str, Any] = {
        "type": "relation",
        "members": [
            {"role": "outer", "geometry": pts((21.0, 52.4), (21.3, 52.4))},
            # This one runs the other way round.
            {"role": "outer", "geometry": pts((21.3, 52.5), (21.3, 52.4))},
            {"role": "outer", "geometry": pts((21.0, 52.5), (21.3, 52.5))},
            {"role": "outer", "geometry": pts((21.0, 52.5), (21.0, 52.4))},
        ],
    }
    rings = _rings_of(element)
    assert len(rings) == 1
    assert len(rings[0]) == 5


def test_islands_are_ignored_rather_than_treated_as_shoreline() -> None:
    """An inner ring is a hole. Fed to the grid as an outline it would be a
    second, wrong lake sitting inside the real one."""
    element: dict[str, Any] = {
        "type": "relation",
        "members": [
            {
                "role": "outer",
                "geometry": pts(
                    (21.0, 52.4), (21.3, 52.4), (21.3, 52.5), (21.0, 52.5), (21.0, 52.4)
                ),
            },
            {
                "role": "inner",
                "geometry": pts(
                    (21.1, 52.44),
                    (21.12, 52.44),
                    (21.12, 52.46),
                    (21.1, 52.46),
                    (21.1, 52.44),
                ),
            },
        ],
    }
    rings = _rings_of(element)
    assert len(rings) == 1
    assert all(p[0] <= 21.0 or p[0] >= 21.3 or p[1] in (52.4, 52.5) for p in rings[0])


def test_an_unjoinable_fragment_is_dropped_not_forced_shut() -> None:
    """Half a shoreline closed by a straight line across the water is fiction.

    ADR 0005 §4 refuses a circle for exactly this reason; a half-traced lake
    closed with a chord is the same lie in a different shape.
    """
    element: dict[str, Any] = {
        "type": "relation",
        "members": [
            {"role": "outer", "geometry": pts((21.0, 52.4), (21.3, 52.4))},
            {"role": "outer", "geometry": pts((21.3, 52.4), (21.3, 52.5))},
            # The rest of the boundary never came back.
        ],
    }
    assert _rings_of(element) == []


def test_a_relation_with_no_members_is_not_a_crash() -> None:
    assert _rings_of({"type": "relation", "id": 5}) == []
    assert _rings_of({"type": "relation", "members": "unexpected"}) == []


def test_two_separate_basins_both_come_back() -> None:
    """One relation can hold more than one outer ring; the caller picks."""
    element: dict[str, Any] = {
        "type": "relation",
        "members": [
            {
                "role": "outer",
                "geometry": pts(
                    (21.0, 52.4), (21.1, 52.4), (21.1, 52.5), (21.0, 52.5), (21.0, 52.4)
                ),
            },
            {
                "role": "outer",
                "geometry": pts(
                    (22.0, 52.4), (22.1, 52.4), (22.1, 52.5), (22.0, 52.5), (22.0, 52.4)
                ),
            },
        ],
    }
    assert len(_rings_of(element)) == 2


def test_stitching_is_not_confused_by_an_empty_list() -> None:
    assert _stitch([]) == []


# --------------------------------------------------------------------------
# The radius, and the query that makes it unnecessary
# --------------------------------------------------------------------------


def test_a_small_pond_keeps_the_default_radius() -> None:
    """Pomocnia is 9 ha. Tightening the search there gains nothing and would
    lose a lake whose geocoded point is slightly off."""
    assert _radius_for_area(9.0) == DEFAULT_RADIUS_M
    assert _radius_for_area(None) == DEFAULT_RADIUS_M
    assert _radius_for_area(0.0) == DEFAULT_RADIUS_M


def test_a_reservoir_gets_a_radius_that_can_reach_its_bank() -> None:
    """3 300 ha is ~3.2 km equivalent radius. 500 m would find nothing."""
    radius = _radius_for_area(3300.0)
    assert radius > 4000, f"{radius} m still cannot reach the bank"
    assert radius <= MAX_RADIUS_M


def test_the_radius_is_capped_so_a_typo_cannot_hammer_overpass() -> None:
    assert _radius_for_area(50_000_000.0) == MAX_RADIUS_M


def test_a_known_osm_id_is_asked_for_directly() -> None:
    """The reliable path: the geocoder already said which object this is.

    Asking "what water is near this point" instead throws that away and
    re-derives it worse - and reintroduces the radius problem this whole file
    exists because of.
    """
    assert "relation(1234)" in _query_by_id("relation", 1234)
    assert "way(99)" in _query_by_id("way", 99)
    assert "out geom" in _query_by_id("way", 99)


def test_an_unexpected_osm_type_is_treated_as_a_way_not_injected() -> None:
    """Nominatim says "way"/"relation"/"node"; anything else must not become
    query text. The id is cast to int for the same reason."""
    assert "way(7)" in _query_by_id("node", 7)
    assert "way(7)" in _query_by_id("'; out meta; //", 7)


# --------------------------------------------------------------------------
# Which ring is the water — the rule differs by how we asked
# --------------------------------------------------------------------------


def ring(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def with_area(r: list[list[float]]) -> tuple[list[list[float]], float]:
    from app.geo.outline import _ring_area_deg

    return (r, _ring_area_deg(r))


# The main body, and a small side basin nearer the label point than the body's
# own edge. This is the Zegrze shape: a long reservoir whose geocoded point is
# a label position that need not fall inside the shoreline at all.
MAIN = with_area(ring(21.00, 52.40, 21.30, 52.48))
SIDE = with_area(ring(20.90, 52.50, 20.92, 52.51))
LABEL_LON, LABEL_LAT = 20.91, 52.505  # inside the side basin, outside the body


def test_by_id_the_largest_ring_wins() -> None:
    """We asked for one object; every ring is part of it, so size decides.

    The first live run logged "no OSM polygon contained 52.4416,21.0561 - using
    the nearest instead" on a by-id fetch. Harmless with one ring; with two it
    would have handed back a side basin as the lake.
    """
    from app.geo.outline import choose_ring

    chosen = choose_ring([SIDE, MAIN], LABEL_LON, LABEL_LAT, by_id=True)
    assert chosen == MAIN[0], "a by-id fetch preferred a side basin over the water body"


def test_by_id_does_not_need_the_point_inside_anything() -> None:
    from app.geo.outline import choose_ring

    assert choose_ring([MAIN], 0.0, 0.0, by_id=True) == MAIN[0]


def test_by_proximity_containment_still_beats_size() -> None:
    """The Wkra rule, unchanged: the river's polygon is bigger than the lake's.

    A by-id fetch and a proximity fetch must not share a tie-break - this is
    the case the id rule would get wrong, which is why it is scoped to id
    queries only.
    """
    from app.geo.outline import choose_ring

    lake = with_area(ring(20.670, 52.540, 20.682, 52.546))
    river = with_area(ring(20.690, 52.520, 20.700, 52.570))
    inside_lake = (20.676, 52.543)

    chosen = choose_ring([river, lake], *inside_lake, by_id=False)
    assert chosen == lake[0], "the river was picked over the lake containing the point"


def test_by_proximity_falls_back_to_nearest_not_largest() -> None:
    from app.geo.outline import choose_ring

    near_small = with_area(ring(20.900, 52.500, 20.902, 52.501))
    far_large = with_area(ring(21.500, 52.000, 21.900, 52.400))

    chosen = choose_ring([far_large, near_small], 20.899, 52.4995, by_id=False)
    assert chosen == near_small[0]
