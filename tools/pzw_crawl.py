"""Crawl PZW's national fishery database into committed YAML.

    python tools/pzw_crawl.py                      # every water, names only
    python tools/pzw_crawl.py --pages 3            # a sample, for checking
    python tools/pzw_crawl.py --details            # also fetch coordinates

`https://pzw.pl/strefa-wedkarza/lowiska-i-wody-pzw` is PZW's own national
register: every water its okregi manage, alphabetical, ~1 800 of them across
174 pages. Each listing card carries the water's name, its kind, its
place and voivodeship, the okreg that manages it and the koło that hosts it.
Each water's own page additionally carries **coordinates**.

This supersedes the per-okreg PDF that `tools/pzw_extract.py` reads (ADR 0007
originally claimed no national machine-readable register existed - it does,
and the owner pointed it out).

Run by hand when the register changes; the output is committed and read at
runtime, so the app never fetches any of this. See ADR 0007.

## Why it drives a browser

The pagination endpoint answers `200` with an **empty body** to a plain
request, however faithfully the query string and headers are reproduced. It
answers properly from inside a real page session. Rather than guess at what
else it wants, this drives the site's own page and calls the endpoint the way
the site does - which is also the honest thing to do: it is the site's
mechanism, used as the site uses it.

Needs `playwright`, already a dev dependency (`requirements-dev.txt`), never a
runtime one.

## Politeness

One request at a time, with a delay between them, and it stops on the first
error rather than hammering. A full names-only run is 174 requests. `--details`
is one request per water on top, ~1 800, which is why it is opt-in and
throttled harder.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

LIST_URL = "https://pzw.pl/strefa-wedkarza/lowiska-i-wody-pzw"
PAGE_URL = (
    "/pioro/myajaxlist/fishery_list/getcontent/0"
    "?search_fishery_class=&type_fishery_class=&voivod_fishery_class="
    "&gmina_fishery_class=&membership_fishery_class=&host_fishery_class=&active_page={page}"
)

DEFAULT_DELAY_S = 0.7
DETAIL_DELAY_S = 1.0

CARD = re.compile(
    r'<a href="(?P<href>/strefa-wedkarza/lowiska-i-wody-pzw/[^"]+)".*?'
    r'class="etiquette\s*">(?P<kind>[^<]*)</span>.*?'
    r"<h3>(?P<name>[^<]*)</h3>(?P<rest>.*?)</article>",
    re.S,
)
PLACE = re.compile(r'class="item_category place">([^<]*)<')
BELONGS = re.compile(r"Przynależność:\s*([^<]*)<")
HOST = re.compile(r"Gospodarz:\s*([^<]*)<")
SLUG = re.compile(r"/lowiska-i-wody-pzw/([^?#]+)")
# The detail page embeds the water's position in a Google Maps embed URL.
COORDS = re.compile(r"maps/embed/v1/place\?[^\"']*?q=(-?\d+\.\d+),(-?\d+\.\d+)")


@dataclass
class Water:
    name: str
    slug: str
    kind: str = ""
    place: str = ""
    voivodeship: str = ""
    okreg: str = ""
    host: str = ""
    lat: float | None = None
    lon: float | None = None
    notes: list[str] = field(default_factory=list)


def _text(value: str) -> str:
    value = value.replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def parse_page(html: str) -> list[Water]:
    waters: list[Water] = []
    for m in CARD.finditer(html):
        name = _text(m.group("name"))
        href = m.group("href")
        slug_match = SLUG.search(href)
        if not name or slug_match is None:
            continue
        rest = m.group("rest")
        place_raw = PLACE.search(rest)
        place, voivodeship = "", ""
        if place_raw:
            parts = [_text(p) for p in place_raw.group(1).split(",")]
            place = parts[0] if parts else ""
            voivodeship = parts[1] if len(parts) > 1 else ""
        belongs = BELONGS.search(rest)
        host = HOST.search(rest)
        waters.append(
            Water(
                name=name,
                slug=_text(slug_match.group(1)),
                kind=_text(m.group("kind")),
                place=place,
                voivodeship=voivodeship,
                okreg=_text(belongs.group(1)) if belongs else "",
                host=_text(host.group(1)) if host else "",
            )
        )
    return waters


def _fetch(page: object, url: str) -> str:
    """Call the site's own endpoint from inside its page session."""
    script = (
        "async (u) => (await (await fetch(u, "
        "{headers: {'X-Requested-With':'XMLHttpRequest'}})).text())"
    )
    raw = page.evaluate(script, url)  # type: ignore[attr-defined]
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return str(raw)
    return str(loaded.get("content_html", ""))


def crawl(max_pages: int | None, want_details: bool, delay: float) -> list[Water]:
    from playwright.sync_api import sync_playwright

    waters: list[Water] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3000)

        total = page.evaluate(
            """() => { const e = document.querySelector('[data-pagescount]');
                       return e ? parseInt(e.getAttribute('data-pagescount'), 10) : 0; }"""
        )
        total = int(total or 0)
        if not total:
            raise SystemExit("could not read the page count - the site's markup has changed")
        limit = min(total, max_pages) if max_pages else total
        print(f"{total} pages advertised; fetching {limit}", file=sys.stderr)

        seen: set[str] = set()
        for n in range(1, limit + 1):
            html = _fetch(page, PAGE_URL.format(page=n))
            found = parse_page(html)
            if not found:
                raise SystemExit(f"page {n} returned nothing - stopping rather than hammering")
            for water in found:
                if water.slug in seen:
                    continue
                seen.add(water.slug)
                waters.append(water)
            print(f"  page {n}/{limit}: {len(found)} waters ({len(waters)} total)", file=sys.stderr)
            time.sleep(delay)

        if want_details:
            print(f"fetching coordinates for {len(waters)} waters", file=sys.stderr)
            for i, water in enumerate(waters, 1):
                detail = _fetch(page, f"/strefa-wedkarza/lowiska-i-wody-pzw/{water.slug}")
                if not detail:
                    page.goto(
                        f"{LIST_URL}/{water.slug}", wait_until="domcontentloaded", timeout=60_000
                    )
                    detail = page.content()
                found = COORDS.search(detail)
                if found:
                    water.lat = round(float(found.group(1)), 6)
                    water.lon = round(float(found.group(2)), 6)
                if i % 25 == 0:
                    print(f"  {i}/{len(waters)}", file=sys.stderr)
                time.sleep(DETAIL_DELAY_S)

        browser.close()
    return waters


# Some okregi prefix every water with their own catalogue number - Opole lists
# "0.101 Stobrawa - staw". It is part of the printed name, so it is kept for
# display, but it is noise in a match key and is stripped before normalising.
CATALOGUE_PREFIX = re.compile(r"^\d+(?:\.\d+)*\s+")


def match_key(name: str) -> str:
    from tools.pzw_extract import normalise_name

    return normalise_name(CATALOGUE_PREFIX.sub("", name))


def to_yaml(waters: list[Water]) -> str:

    lines = [
        "# Every water PZW's own national register lists.",
        "#",
        "# GENERATED by tools/pzw_crawl.py from",
        f"# {LIST_URL}",
        "# Do not hand-edit: re-run the tool.",
        "#",
        "# `name` is PZW's own spelling, which is what the permit prints and",
        "# therefore what the app displays. `key` is the normalised form used",
        "# for matching; see app/discover/pzw.py.",
        "okreg: poland",
        "waters:",
    ]
    for water in sorted(waters, key=lambda w: (match_key(w.name), w.slug)):
        key = match_key(water.name)
        if not key:
            continue
        lines.append(f"  - name: {water.name!r}")
        lines.append(f"    key: {key!r}")
        lines.append(f"    slug: {water.slug!r}")
        if water.kind:
            lines.append(f"    section: {water.kind!r}")
        if water.place:
            lines.append(f"    place: {water.place!r}")
        if water.voivodeship:
            lines.append(f"    voivodeship: {water.voivodeship!r}")
        if water.okreg:
            lines.append(f"    okreg_name: {water.okreg!r}")
        if water.host:
            lines.append(f"    host: {water.host!r}")
        if water.lat is not None and water.lon is not None:
            lines.append(f"    lat: {water.lat}")
            lines.append(f"    lon: {water.lon}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=None, help="stop after N listing pages")
    parser.add_argument(
        "--details", action="store_true", help="also fetch each water's coordinates"
    )
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_S)
    parser.add_argument("-o", "--out", type=Path, default=Path("config/pzw/poland.yaml"))
    args = parser.parse_args(argv)

    waters = crawl(args.pages, args.details, args.delay)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    open(args.out, "w", encoding="utf-8").write(to_yaml(waters))

    with_coords = sum(1 for w in waters if w.lat is not None)
    print(f"{len(waters)} waters -> {args.out}")
    print(f"  with coordinates: {with_coords}")
    okregi = {w.okreg for w in waters if w.okreg}
    print(f"  okregi represented: {len(okregi)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
