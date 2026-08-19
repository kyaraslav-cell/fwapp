from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from shapely.geometry import LineString, Point, shape
from shapely.geometry.base import BaseGeometry

METERS_PER_DEGREE_LAT = 111_320.0
MAX_RAY_M = 500.0


@dataclass(frozen=True)
class GridCell:
    row: int
    col: int
    lat: float
    lon: float

    @property
    def cell_id(self) -> str:
        return f"r{self.row}c{self.col}"


@dataclass(frozen=True)
class LakeGrid:
    origin_lat: float
    origin_lon: float
    cell_m: float
    n_rows: int
    n_cols: int
    cells: list[GridCell]

    def cell_by_id(self, cell_id: str) -> GridCell | None:
        for cell in self.cells:
            if cell.cell_id == cell_id:
                return cell
        return None


def polygon_area_ha(outline_geojson: dict[str, Any]) -> float | None:
    """Area of a GeoJSON polygon's outer ring, in hectares. Pure.

    Shoelace on a local equirectangular projection - metres east and north of
    the ring's own centre. Over a few hundred metres that is exact enough that
    the error is far below the shoreline's own precision, and it needs no
    projection library for what is ultimately a number used to pick a grid
    resolution.
    """
    geometry = outline_geojson.get("geometry", outline_geojson)
    if geometry.get("type") != "Polygon":
        return None
    rings = geometry.get("coordinates") or []
    if not rings or len(rings[0]) < 4:
        return None

    ring = rings[0]
    mid_lat = sum(point[1] for point in ring) / len(ring)
    m_per_lon = meters_per_degree_lon(mid_lat)

    xs = [point[0] * m_per_lon for point in ring]
    ys = [point[1] * METERS_PER_DEGREE_LAT for point in ring]

    twice_area = 0.0
    for i in range(len(ring) - 1):
        twice_area += xs[i] * ys[i + 1] - xs[i + 1] * ys[i]
    area_m2 = abs(twice_area) / 2.0
    return area_m2 / 10_000.0 if area_m2 > 0 else None


def meters_per_degree_lon(lat: float) -> float:
    return METERS_PER_DEGREE_LAT * math.cos(math.radians(lat))


def build_grid(outline_geojson: dict[str, Any], cell_m: float) -> LakeGrid:
    """Pure. Lay a cell_m x cell_m grid over the outline's bounding box and keep
    only cells whose centre falls inside the water polygon. This is what makes
    the overlay follow the real shoreline instead of a circle."""
    polygon = shape(outline_geojson)
    min_lon, min_lat, max_lon, max_lat = polygon.bounds

    m_per_deg_lon = meters_per_degree_lon((min_lat + max_lat) / 2.0)
    dlat = cell_m / METERS_PER_DEGREE_LAT
    dlon = cell_m / m_per_deg_lon

    n_rows = max(1, int(math.ceil((max_lat - min_lat) / dlat)))
    n_cols = max(1, int(math.ceil((max_lon - min_lon) / dlon)))

    cells: list[GridCell] = []
    for row in range(n_rows):
        lat = min_lat + (row + 0.5) * dlat
        for col in range(n_cols):
            lon = min_lon + (col + 0.5) * dlon
            if polygon.contains(Point(lon, lat)):
                cells.append(GridCell(row=row, col=col, lat=lat, lon=lon))

    return LakeGrid(
        origin_lat=min_lat,
        origin_lon=min_lon,
        cell_m=cell_m,
        n_rows=n_rows,
        n_cols=n_cols,
        cells=cells,
    )


def effective_fetch_m(
    polygon: BaseGeometry, lat: float, lon: float, wind_from_deg: float
) -> float:
    """Pure geometry: distance of open water upwind of this point, in metres.

    This is the Layer 4 'effective fetch' ray-cast described in
    docs/02-DOMAIN.md - NOT the pending FORMULA_WIND_ZONE, which converts
    exposure into a scored zone preference and is still owed by the owner.
    Long fetch = wind has crossed open water to reach here (wave energy,
    food pushed in). Short fetch = sheltered.
    """
    bearing = math.radians(wind_from_deg)
    m_per_deg_lon = meters_per_degree_lon(lat)

    # Step upwind: toward the direction the wind is coming FROM.
    end_lat = lat + (MAX_RAY_M * math.cos(bearing)) / METERS_PER_DEGREE_LAT
    end_lon = lon + (MAX_RAY_M * math.sin(bearing)) / m_per_deg_lon

    start = Point(lon, lat)
    ray = LineString([(lon, lat), (end_lon, end_lat)])
    water = ray.intersection(polygon)

    if water.is_empty:
        return 0.0

    segments = [water] if water.geom_type == "LineString" else list(getattr(water, "geoms", []))

    # Only the segment still connected to the starting point counts: water on
    # the far side of an intervening headland is not fetch for this point.
    tolerance_deg = 2.0 / METERS_PER_DEGREE_LAT
    for segment in segments:
        if segment.geom_type != "LineString" or segment.is_empty:
            continue
        if segment.distance(start) <= tolerance_deg:
            return _length_in_meters(segment, lat)
    return 0.0


def _length_in_meters(line: LineString, lat: float) -> float:
    m_per_deg_lon = meters_per_degree_lon(lat)
    total = 0.0
    coords = list(line.coords)
    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        dx = (x2 - x1) * m_per_deg_lon
        dy = (y2 - y1) * METERS_PER_DEGREE_LAT
        total += math.hypot(dx, dy)
    return total


def fetch_values(
    outline_geojson: dict[str, Any], grid: LakeGrid, wind_from_deg: float
) -> list[tuple[int, int, float]]:
    """Pure. [(row, col, fetch_m)] for every water cell, for one wind direction."""
    polygon = shape(outline_geojson)
    return [
        (
            cell.row,
            cell.col,
            round(effective_fetch_m(polygon, cell.lat, cell.lon, wind_from_deg), 1),
        )
        for cell in grid.cells
    ]


def shore_distances(
    outline_geojson: dict[str, Any], grid: LakeGrid
) -> dict[tuple[int, int], float]:
    """Pure. Metres from each cell centre to the nearest bank."""
    polygon = shape(outline_geojson)
    boundary = polygon.exterior
    out: dict[tuple[int, int], float] = {}
    for cell in grid.cells:
        deg = boundary.distance(Point(cell.lon, cell.lat))
        # Degrees are anisotropic; approximate locally using the cell latitude.
        out[(cell.row, cell.col)] = deg * METERS_PER_DEGREE_LAT
    return out


def geometry_inputs(
    outline_geojson: dict[str, Any], grid: LakeGrid, wind_from_deg: float
) -> list[tuple[int, int, float, float]]:
    """Pure. [(row, col, fetch_m, shore_m)] - the inputs the zone score needs."""
    shore = shore_distances(outline_geojson, grid)
    return [
        (row, col, fetch_m, shore.get((row, col), 0.0))
        for row, col, fetch_m in fetch_values(outline_geojson, grid, wind_from_deg)
    ]
