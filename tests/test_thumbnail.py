"""A water's shape as a small SVG path - pure geometry, no fixtures needed."""

from __future__ import annotations

from app.geo.thumbnail import outline_thumbnail_path

SQUARE = {
    "type": "Polygon",
    "coordinates": [[[20.0, 52.0], [20.1, 52.0], [20.1, 52.1], [20.0, 52.1], [20.0, 52.0]]],
}


def test_a_square_becomes_a_closed_path_with_four_corners() -> None:
    d = outline_thumbnail_path(SQUARE)
    assert d is not None
    assert d.startswith("M ")
    assert d.endswith(" Z")
    # 5 points in, one repeated to close the ring - all 5 must survive.
    assert d.count("L") == 4


def test_it_fits_inside_the_requested_size_with_padding() -> None:
    d = outline_thumbnail_path(SQUARE, size=56.0, padding=4.0)
    assert d is not None
    coords = [
        tuple(float(v) for v in point.split(","))
        for point in d.replace("M ", "").replace(" Z", "").split(" L ")
    ]
    xs = [x for x, _ in coords]
    ys = [y for _, y in coords]
    assert min(xs) >= 4.0 - 0.5 and max(xs) <= 56.0 - 4.0 + 0.5
    assert min(ys) >= 4.0 - 0.5 and max(ys) <= 56.0 - 4.0 + 0.5


def test_latitude_is_flipped_so_the_shape_is_not_upside_down() -> None:
    """North (higher latitude) must end up with a smaller y - SVG y grows down."""
    tall = {
        "type": "Polygon",
        "coordinates": [[[20.0, 52.0], [20.1, 52.0], [20.0, 53.0], [20.0, 52.0]]],
    }
    d = outline_thumbnail_path(tall)
    assert d is not None
    points = [
        tuple(float(v) for v in point.split(","))
        for point in d.replace("M ", "").replace(" Z", "").split(" L ")
    ]
    # The northernmost input point (52.0, ...) wait - compare directly:
    # (20.0, 52.0) is south of (20.0, 53.0), so its y must be larger (lower on screen).
    south_y = points[0][1]
    north_y = points[2][1]
    assert north_y < south_y


def test_a_dense_ring_is_downsampled() -> None:
    dense_ring = [[20.0 + 0.0001 * i, 52.0 + 0.0001 * i] for i in range(3000)]
    dense_ring.append(dense_ring[0])
    d = outline_thumbnail_path(
        {"type": "Polygon", "coordinates": [dense_ring]}, max_points=100
    )
    assert d is not None
    assert d.count("L") < 100


def test_none_and_wrong_shape_are_rejected_not_crashed() -> None:
    assert outline_thumbnail_path(None) is None
    assert outline_thumbnail_path({}) is None
    assert outline_thumbnail_path({"type": "MultiPolygon", "coordinates": []}) is None
    assert outline_thumbnail_path({"type": "Polygon", "coordinates": [[]]}) is None
    assert outline_thumbnail_path(
        {"type": "Polygon", "coordinates": [[[20.0, 52.0], [20.1, 52.0]]]}
    ) is None
