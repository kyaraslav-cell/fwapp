"""Render the read-only half of Fishlog into a static site for GitHub Pages.

WHAT THIS CAN AND CANNOT DO
---------------------------
GitHub Pages serves files. It runs no Python, holds no SQLite, and accepts no
POST. So this build carries the parts of the app that only *read*:

    conditions now, the five-day table, the lake outline and the zone overlay.

It deliberately does NOT carry the notebook - starting a session, logging a
catch, editing or deleting one. Those need a writable database, and a page that
looked like it could log a fish but silently dropped it would be worse than not
offering it. The build injects a banner saying so, and drops the nav links that
would lead to a dead end.

The weather itself is refreshed by the workflow that calls this
(`.github/workflows/pages.yml`), which runs the real Open-Meteo ingest twice a
day before building. Law 4 still holds: if that fetch fails, the ingest writes
nothing and records a gap, and this build simply publishes the last real
observations with an honest "as of" timestamp.

TWO STATIC-HOSTING PROBLEMS THIS SOLVES
---------------------------------------
1. Query strings. The live map calls `/lake/x/grid?wind_dir=270`. A static host
   ignores `?...` and would hand back the same file for every direction, so the
   overlay would never change with the wind. The build pre-renders one JSON per
   wind bucket and points the page at those instead.
2. Absolute URLs. Project Pages are served from `/<repo>/`, not `/`, so every
   `/static/...` and `href="/"` in the templates would 404. Everything is
   rewritten to sit under the base path.

Usage:  python tools/build_static.py [--out dist] [--base /fwapp]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

import tools.build_spike as build_spike  # noqa: E402
from app.core.i18n import COOKIE_NAME  # noqa: E402
from app.web.app import app  # noqa: E402

# One grid file per 30 degrees of wind. Twelve files rather than a continuous
# range: the zone score is explicitly provisional and percentile-displayed, so
# resolving wind finer than half a compass point would be false precision, and
# every extra bucket is another ~60 KB in the published site.
WIND_STEP = 30

BANNER = """
<div class="callout" style="margin:0 0 14px;">
  <strong>{title}</strong><br>{body}
</div>
"""

BANNER_TEXT = {
    "en": (
        "Read-only conditions board",
        "This is the published snapshot. Weather refreshes twice a day. "
        "Session and catch logging need the full app - they are not available here.",
    ),
    "pl": (
        "Tablica warunków — tylko do odczytu",
        "To jest opublikowana migawka. Pogoda odświeża się dwa razy dziennie. "
        "Zapis wędkowania i połowów wymaga pełnej aplikacji — tutaj nie działa.",
    ),
    "ru": (
        "Сводка условий — только просмотр",
        "Это опубликованный снимок. Погода обновляется дважды в день. "
        "Запись сессий и уловов требует полного приложения — здесь недоступна.",
    ),
}


def rewrite(html: str, base: str, lang: str) -> str:
    """Point every absolute URL at the base path and neuter the dead links."""
    if base:
        # href="/x" and src="/x", but never "//cdn..." which is protocol-relative.
        html = re.sub(r'(href|src)="/(?!/)', rf'\1="{base}/', html)
        html = html.replace('"/static/', f'"{base}/static/')

    # The language switcher points at /lang/<code>, a server redirect that sets a
    # cookie. Statically, each language is simply its own directory.
    html = re.sub(
        r'href="[^"]*/lang/(\w+)\?next=[^"]*"',
        lambda m: f'href="{base}/{"" if m.group(1) == "en" else m.group(1) + "/"}"',
        html,
    )

    # History and any session entry point lead nowhere without a database.
    html = re.sub(r'<a href="[^"]*/history"[^>]*>.*?</a>', "", html, flags=re.S)
    html = re.sub(
        r'<a[^>]+href="[^"]*/lake/[^"]*/spot[^"]*"[^>]*>.*?</a>', "", html, flags=re.S
    )

    # Accounts need a server. The notebook they guard is not published here
    # either, so the sign-in link would be a 404 on Pages - drop it rather than
    # publish a door with no room behind it. (The sign-out form goes with the
    # POST forms below.)
    html = re.sub(r'<a[^>]+class="account-signin"[^>]*>.*?</a>', "", html, flags=re.S)

    # Every POST form is dead here - a static host has nothing to receive it.
    # "Refresh weather & prediction" is the visible one, and leaving a button
    # that silently does nothing is worse than not showing it: the workflow's
    # cron is what refreshes this site, not the reader.
    html = re.sub(r'<form[^>]+method="post".*?</form>', "", html, flags=re.S | re.I)

    title, body = BANNER_TEXT.get(lang, BANNER_TEXT["en"])
    return html.replace(
        '<main class="page', BANNER.format(title=title, body=body) + '<main class="page', 1
    ) if "<main" in html else html


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="dist")
    parser.add_argument("--base", default="", help='e.g. "/fwapp" for project Pages')
    parser.add_argument("--slug", default="pomocnia")
    parser.add_argument(
        "--no-spike",
        action="store_true",
        help="skip /spike/pyodide/ (see tools/build_spike.py)",
    )
    args = parser.parse_args()

    base = args.base.rstrip("/")
    out = pathlib.Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # As a CONTEXT MANAGER, so the FastAPI lifespan actually runs. A bare
    # `TestClient(app)` issues requests without ever starting the app, so
    # `init_db()` never fires and the first query dies on "no such table:
    # species" whenever the database file does not already exist. That is
    # invisible in a working tree with a stale fishlog.db and fatal on a fresh
    # CI runner, which is exactly where this build runs.
    with TestClient(app) as client:
        return build(client, out, base, args.slug, spike=not args.no_spike)


def build(
    client: TestClient, out: pathlib.Path, base: str, slug: str, spike: bool = True
) -> int:
    # Static assets, copied wholesale.
    shutil.copytree("app/web/static", out / "static")

    languages = ["en", "pl", "ru"]
    for lang in languages:
        cookies = {COOKIE_NAME: lang}
        target = out if lang == "en" else out / lang
        target.mkdir(parents=True, exist_ok=True)

        response = client.get(f"/lake/{slug}", cookies=cookies)
        response.raise_for_status()

        html = response.text
        # Point the page at the pre-rendered buckets instead of the live route.
        html = html.replace(
            "const STATIC_GRID = null;",
            f'const STATIC_GRID = "{base}/grid/{slug}";',
        )
        (target / "index.html").write_text(rewrite(html, base, lang), encoding="utf-8")
        print(f"  {lang}: {target / 'index.html'}")

    # One grid per wind bucket. These are what make the overlay respond to the
    # wind without a server.
    grid_dir = out / "grid" / slug
    grid_dir.mkdir(parents=True, exist_ok=True)
    for bucket in range(0, 360, WIND_STEP):
        r = client.get(f"/lake/{slug}/grid", params={"wind_dir": float(bucket)})
        r.raise_for_status()
        (grid_dir / f"wd{bucket:03d}.json").write_text(json.dumps(r.json()))
    print(f"  {360 // WIND_STEP} wind buckets -> {grid_dir}")

    # The Pyodide spike, at /spike/pyodide/. Unlinked from the angler-facing
    # pages on purpose - it is an engineering measurement, not a feature - but
    # it has to be published, because the question it answers ("can a browser on
    # a static host run our geometry?") can only be answered on the real URL.
    if spike:
        build_spike.build(out, base, slug, 270.0, ensure_app=False)

    # Tell Pages not to run the output through Jekyll, which would eat any
    # directory whose name starts with an underscore.
    (out / ".nojekyll").write_text("")

    print(f"built into {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
