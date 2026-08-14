"""The Wkra runs past Pomocnia and its polygon is much larger than the lake's.
An earlier 'largest polygon wins' heuristic therefore drew the whole heat map
over the river. These tests pin the corrected behaviour: containment first.
"""

from app.geo.outline import _min_distance_deg, _point_in_ring

LAT, LON = 52.5431, 20.6762

LAKE = [
    [LON - 0.0025, LAT - 0.0015],
    [LON + 0.0025, LAT - 0.0015],
    [LON + 0.0025, LAT + 0.0015],
    [LON - 0.0025, LAT + 0.0015],
    [LON - 0.0025, LAT - 0.0015],
]

# Long, thin, and roughly ten times the lake's area - like the real river.
RIVER = [
    [LON + 0.010, LAT - 0.020],
    [LON + 0.014, LAT - 0.020],
    [LON + 0.014, LAT + 0.020],
    [LON + 0.010, LAT + 0.020],
    [LON + 0.010, LAT - 0.020],
]


def _area(ring: list[list[float]]) -> float:
    total = 0.0
    for i in range(len(ring) - 1):
        total += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(total) / 2.0


def test_lake_contains_its_own_centroid_and_river_does_not():
    assert _point_in_ring(LON, LAT, LAKE) is True
    assert _point_in_ring(LON, LAT, RIVER) is False


def test_river_really_is_the_larger_polygon():
    """If this stops being true the regression it guards against is gone."""
    assert _area(RIVER) > _area(LAKE)


def test_containment_beats_area_when_choosing_the_outline():
    candidates = [LAKE, RIVER]
    containing = [r for r in candidates if _point_in_ring(LON, LAT, r)]
    assert containing, "the lake must be a candidate"
    assert max(containing, key=_area) is LAKE


def test_nearest_fallback_prefers_the_lake_when_nothing_contains_the_point():
    off_lat, off_lon = LAT + 0.004, LON  # just outside the lake polygon
    assert not _point_in_ring(off_lon, off_lat, LAKE)
    nearest = min([LAKE, RIVER], key=lambda r: _min_distance_deg(off_lon, off_lat, r))
    assert nearest is LAKE
