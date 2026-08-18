"""Render the zone overlay to a PNG so it can actually be looked at.

CLAUDE.md is explicit that visual output cannot be verified from a diff, and
this is the case that proves it: the v0.4 zone score passed every test, had a
raw spread of 0.33 across 1352 distinct values, and rendered as one flat stain
with a green rim. The numbers looked fine. The map was useless.

Draws the same cells the browser canvas draws, through the same red-to-green
ramp, with the outline on top. `--compare` puts two models side by side, which
is the only view that answers "did that change anything".

    python tools/zone_map.py out.png
    python tools/zone_map.py out.png --compare        # v0.4 beside v0.3 geometry
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app.core.db import session_scope  # noqa: E402
from app.core.models import Lake, WeatherHourly  # noqa: E402
from app.core.time import iso  # noqa: E402
from app.geo import service as geo  # noqa: E402
from app.rules.loader import load_active_ruleset  # noqa: E402
from app.rules.zone_score import score_cells  # noqa: E402
from app.web import bite_view  # noqa: E402
from app.web.app import app  # noqa: E402

SCALE = 3  # pixels per grid cell


def seed_weather(db, lake: Lake, hours: int = 120, hi: float = 24.0, lo: float = 14.0) -> None:
    """A plausible settled week, so the renderer exercises the live path.

    Written to the database of a throwaway run only - `weather_hourly` in a real
    deployment never receives anything but a real observation (law 4).
    """
    now = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0)
    for h in range(hours):
        ts = now - dt.timedelta(hours=hours - 1 - h)
        frac = (1 - math.cos((ts.hour - 4) / 24 * 2 * math.pi)) / 2
        db.add(WeatherHourly(
            lake_id=lake.id, source="zone_map_preview", ts_utc=iso(ts), is_forecast=0,
            temperature_2m=lo + (hi - lo) * frac, dewpoint_2m=lo - 5 + (hi - lo) * frac * 0.5,
            relative_humidity_2m=70.0, pressure_msl=1014 + 0.8 * math.sin(h / 24 * 2 * math.pi),
            wind_speed_10m=4.0, wind_direction_10m=270.0, wind_gusts_10m=7.0, cloud_cover=30.0,
            shortwave_radiation=max(0.0, 800 * math.sin(max(0.0, (ts.hour - 5) / 14) * math.pi)),
            precipitation=0.0, fetched_at=iso(now)))


def ramp(value: float) -> tuple[int, int, int]:
    """Red -> orange -> yellow -> green, matching the app's traffic-light rule."""
    stops = [
        (0.0, (208, 74, 58)), (0.33, (226, 140, 62)),
        (0.66, (226, 205, 74)), (1.0, (74, 176, 118)),
    ]
    for (a, ca), (b, cb) in zip(stops, stops[1:], strict=False):
        if value <= b:
            f = 0.0 if b == a else (value - a) / (b - a)
            return tuple(int(ca[i] + (cb[i] - ca[i]) * f) for i in range(3))  # type: ignore[return-value]
    return stops[-1][1]


def percentile(raw: list[tuple[int, int, float]]) -> list[tuple[int, int, float]]:
    order = sorted(range(len(raw)), key=lambda i: raw[i][2])
    n = len(raw)
    if n < 2:
        return [(r, c, 0.5) for r, c, _ in raw]
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and raw[order[j + 1]][2] == raw[order[i]][2]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0
        i = j + 1
    return [(raw[i][0], raw[i][1], ranks[i] / (n - 1)) for i in range(n)]


def draw(cells: list[tuple[int, int, float]], rows: int, cols: int, title: str) -> Image.Image:
    img = Image.new("RGB", (cols * SCALE, rows * SCALE + 18), (240, 246, 252))
    d = ImageDraw.Draw(img)
    for r, c, v in cells:
        y = (rows - 1 - r) * SCALE
        d.rectangle([c * SCALE, y, c * SCALE + SCALE - 1, y + SCALE - 1], fill=ramp(v))
    d.text((4, rows * SCALE + 4), title, fill=(34, 56, 77))
    return img


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="zone-map.png")
    ap.add_argument("--compare", action="store_true", help="beside the v0.3 geometry model")
    ap.add_argument("--wind", type=float, default=270.0)
    args = ap.parse_args()

    with TestClient(app):
        pass
    with session_scope() as db:
        lake = db.query(Lake).filter(Lake.slug == "pomocnia").one()
        seed_weather(db, lake)
    with session_scope() as db:
        lake = db.query(Lake).filter(Lake.slug == "pomocnia").one()
        ruleset = load_active_ruleset()
        outline = geo.ensure_outline(db, lake)
        grid = geo.get_grid(lake, outline)
        inputs = geo.get_geometry_inputs(lake, outline, grid, args.wind)
        view = bite_view.build(db, lake, ruleset)
        raw = bite_view.zone_scores(db, lake, ruleset, inputs, view, 25.0, 400.0)

        panels = []
        if raw:
            spread = max(v for _, _, v in raw) - min(v for _, _, v in raw)
            panels.append(draw(percentile(raw), grid.n_rows, grid.n_cols,
                               f"v0.4 three-factor  (raw spread {spread:.3f})"))
        else:
            print("v0.4 produced no cells")
        if args.compare:
            legacy = {"zone_score": ruleset["zone_score"]["fallback"]}
            old, _ = score_cells(legacy, "summer_stagnation", inputs)
            panels.append(draw(old, grid.n_rows, grid.n_cols, "v0.3 geometry only"))

    if not panels:
        return 1
    gap = 12
    sheet = Image.new("RGB", (sum(p.width for p in panels) + gap * (len(panels) - 1),
                              max(p.height for p in panels)), (240, 246, 252))
    x = 0
    for p in panels:
        sheet.paste(p, (x, 0))
        x += p.width + gap
    out = pathlib.Path(args.out).resolve()
    sheet.save(out)
    print(f"wrote {out}  ({sheet.width}x{sheet.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
