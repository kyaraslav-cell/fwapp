"""Cutting a river district into fishable stretches.

A lake gets a 2D grid because you pick a spot in open water. A river is fished
by stretch, and it has no polygon to grid anyway - buffering the centreline by
a guessed width would manufacture a shoreline nobody surveyed, which ADR 0005
§4 refuses.

Sections deliberately carry no score. The zone model is wind fetch and
distance-to-bank and neither means anything on a 25 m canal; what actually
decides a river swim is not modelled at all.
"""

from __future__ import annotations

from app.geo import sections

# Roughly a straight kilometre of latitude, in GeoJSON (lon, lat) order.
ONE_KM_NORTH = {
    "type": "LineString",
    "coordinates": [[21.0, 52.0], [21.0, 52.008983]],
}


def _multi(*lines: list[list[float]]) -> dict[str, object]:
    return {"type": "MultiLineString", "coordinates": list(lines)}


def test_length_of_a_known_line() -> None:
    length = sections.course_length_m(ONE_KM_NORTH)
    assert 990 < length < 1010, length


def test_sections_are_cut_to_the_requested_length() -> None:
    """Boundaries land where they fall, not at the next mapped vertex.

    The course is thinned to 160 points, so vertices can be a kilometre apart.
    Snapping boundaries to them made "500 m" sections that ran to 1 100 m.
    """
    cut = sections.split_course(ONE_KM_NORTH, section_m=250.0)

    assert len(cut) == 4
    for section in cut:
        assert 240 < section.length_m < 260, section.length_m


def test_a_short_tail_is_folded_into_the_stretch_before_it() -> None:
    """A 40 m section beside a 500 m one is not a choice anybody makes."""
    cut = sections.split_course(ONE_KM_NORTH, section_m=450.0)

    assert len(cut) == 2
    assert sum(s.length_m for s in cut) > 990


def test_separate_lines_are_never_joined() -> None:
    """Narew nr 7 carries the Narew and an arm of the Bug, kilometres apart.

    A stretch spanning that gap would be a piece of water that does not exist.
    """
    far_apart = _multi(
        [[21.0, 52.0], [21.0, 52.0045]],
        [[22.0, 53.0], [22.0, 53.0045]],
    )
    cut = sections.split_course(far_apart, section_m=1000.0)

    assert len(cut) == 2
    # No section may contain points from both lines.
    for section in cut:
        lons = {round(p[1]) for p in section.points}
        assert len(lons) == 1


def test_the_stretch_length_suits_the_district() -> None:
    """A fixed 500 m makes a 78 km river into 157 unreadable choices."""
    long_river = {"type": "LineString", "coordinates": [[21.0, 52.0], [21.0, 52.7]]}
    short_spur = {"type": "LineString", "coordinates": [[21.0, 52.0], [21.0, 52.009]]}

    assert sections.suggested_section_m(long_river) > sections.suggested_section_m(short_spur)
    assert len(sections.split_course(long_river)) <= sections.MAX_SECTIONS


def test_a_midpoint_lies_on_its_own_stretch() -> None:
    """It is where a marker goes, so it has to be on the water."""
    cut = sections.split_course(ONE_KM_NORTH, section_m=250.0)
    for section in cut:
        lat, lon = section.midpoint
        lats = [p[0] for p in section.points]
        assert min(lats) - 1e-6 <= lat <= max(lats) + 1e-6
        assert abs(lon - 21.0) < 1e-6


def test_nothing_to_cut_yields_nothing() -> None:
    assert sections.split_course(None) == []
    assert sections.split_course({"type": "Polygon", "coordinates": []}) == []
    assert sections.split_course({"type": "LineString", "coordinates": [[21.0, 52.0]]}) == []


def test_the_geojson_carries_no_score() -> None:
    """The whole point: these divide the water, they do not rate it.

    A colour here would come from the lake model - wind fetch on a canal - and
    would look authoritative while meaning nothing.
    """
    payload = sections.to_geojson(sections.split_course(ONE_KM_NORTH, section_m=250.0))

    assert payload["type"] == "FeatureCollection"
    for feature in payload["features"]:
        keys = set(feature["properties"])
        assert keys == {"index", "length_m", "start_m", "mid_lat", "mid_lon"}
        assert "score" not in keys and "band" not in keys and "colour" not in keys


def test_sections_run_in_order_along_the_water() -> None:
    cut = sections.split_course(ONE_KM_NORTH, section_m=250.0)
    assert [s.index for s in cut] == sorted(s.index for s in cut)
    assert [s.start_m for s in cut] == sorted(s.start_m for s in cut)
