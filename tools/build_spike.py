"""Build the Pyodide + shapely spike page and its payload.

THE QUESTION THIS SPIKE ANSWERS
-------------------------------
The published Pages site cannot run Python, so `tools/build_static.py`
pre-renders twelve wind buckets of zone scores and the page picks the nearest
one. That is why the overlay snaps in 30-degree steps and why nothing about the
score can respond to anything the visitor changes.

If CPython and shapely can be loaded *into the browser*, the same static host
could run `app/geo/grid.py` and `app/rules/zone_score.py` unmodified, for any
wind direction, with no server at all.

That is a claim about bytes and seconds in a real browser, and it cannot be
settled by reading anything. So this builds a page that runs the real modules
on the real lake outline, compares the browser's answers against this build's
own server-side answers cell by cell, and prints the verdict where it can be
photographed.

WHAT IT DOES NOT ANSWER
-----------------------
Nothing here decides whether to adopt Pyodide. The interesting number is the
cold-load time on a phone on the bank, and only the real Pages URL on a real
phone produces it.

Usage:  python tools/build_spike.py [--out dist] [--base /fwapp] [--wind 270]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import platform
import shutil
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import shapely  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import session_scope  # noqa: E402
from app.core.models import Lake  # noqa: E402
from app.geo import service as geo_service  # noqa: E402
from app.rules.loader import load_active_ruleset  # noqa: E402
from app.rules.zone_score import score_cells  # noqa: E402
from app.web.app import app  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "spike" / "pyodide" / "index.html"

# Pinned, not "latest". A spike that silently follows upstream stops being a
# measurement of anything. Sourced from the official `pyodide` npm package,
# whose pyodide.mjs builds this exact CDN path from its own version.
PYODIDE_VERSION = "314.0.5"
PYODIDE_INDEX_URL = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"

# The real modules, shipped as source and imported unmodified in the browser.
# If any of these needs a browser-specific edit, the spike has failed - the
# whole point is that one implementation serves both sides.
SOURCE_FILES = [
    "app/__init__.py",
    "app/rules/__init__.py",
    "app/rules/expressions.py",
    "app/rules/zone_score.py",
    "app/geo/__init__.py",
    "app/geo/grid.py",
]


def collect_sources() -> dict[str, str]:
    return {p: (ROOT / p).read_text(encoding="utf-8") for p in SOURCE_FILES}


def build_payload(slug: str, wind_dir: float, ensure_app: bool = True) -> dict[str, Any]:
    """Everything the browser needs, plus this machine's answer to compare against.

    `ensure_app` opens the FastAPI lifespan so the schema exists and the lake is
    seeded. tools/build_static.py already holds it open when it calls this, and
    starting a second one would start a second scheduler.
    """
    if ensure_app:
        with TestClient(app):
            pass

    with session_scope() as db:
        lake = db.query(Lake).filter(Lake.slug == slug).one()
        outline = geo_service.ensure_outline(db, lake)
        outline_source = lake.outline_source or "unknown"
        grid = geo_service.get_grid(lake, outline)
        inputs = geo_service.get_geometry_inputs(lake, outline, grid, wind_dir)

    ruleset = load_active_ruleset()
    phase = ruleset["zone_score"]["default_phase"]
    scored, phase_used = score_cells(ruleset, phase, inputs)

    return {
        "built_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "pyodide": {"version": PYODIDE_VERSION, "index_url": PYODIDE_INDEX_URL},
        "server": {
            "python": platform.python_version(),
            "shapely": shapely.__version__,
            "geos": shapely.geos_version_string,
        },
        "lake": {
            "slug": slug,
            "outline_source": outline_source,
            "cell_m": grid.cell_m,
            "n_rows": grid.n_rows,
            "n_cols": grid.n_cols,
            "origin_lat": grid.origin_lat,
            "origin_lon": grid.origin_lon,
        },
        "outline": outline,
        # Only the zone_score subtree: it is all `score_cells` reads, and law 1
        # means it must arrive as data from the YAML, never as numbers in the
        # page.
        "zone_score": ruleset["zone_score"],
        "phase": phase_used,
        "wind_dir": wind_dir,
        "sources": collect_sources(),
        # This machine's answers, at both stages, so the browser can be checked
        # against them separately: geometry (needs shapely) and scoring (does
        # not).
        "expected": {
            "n_cells": len(inputs),
            "inputs": [[r, c, f, s] for r, c, f, s in inputs],
            "cells": [[r, c, v] for r, c, v in scored],
        },
    }


def build(
    out: pathlib.Path, base: str, slug: str, wind_dir: float, ensure_app: bool = True
) -> int:
    target = out / "spike" / "pyodide"
    target.mkdir(parents=True, exist_ok=True)

    payload = build_payload(slug, wind_dir, ensure_app=ensure_app)
    payload_path = target / "payload.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    html = PAGE.read_text(encoding="utf-8").replace(
        'const BASE = "";', f'const BASE = "{base}";'
    )
    (target / "index.html").write_text(html, encoding="utf-8")

    size_kb = payload_path.stat().st_size / 1024
    print(f"  spike: {target / 'index.html'}")
    print(
        f"  payload: {size_kb:.0f} KB, {payload['expected']['n_cells']} cells, "
        f"outline {payload['lake']['outline_source']}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="dist")
    parser.add_argument("--base", default="", help='e.g. "/fwapp" for project Pages')
    parser.add_argument("--slug", default="pomocnia")
    parser.add_argument("--wind", type=float, default=270.0)
    parser.add_argument(
        "--clean", action="store_true", help="wipe --out first (standalone runs)"
    )
    args = parser.parse_args()

    out = pathlib.Path(args.out)
    if args.clean and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    return build(out, args.base.rstrip("/"), args.slug, args.wind)


if __name__ == "__main__":
    raise SystemExit(main())
