"""Render every fish icon at UI size and tile them into one sheet.

The icons were declared "redrawn per species" three times and still read as one
recoloured shape, because nobody rendered them - the diff looked different, the
pixels did not. This renders the real `_fish_icons.html` sprite through the real
stylesheet at the real button size.

`--compare [REV]` pulls the sprite from git (default HEAD) and puts the previous
drawing directly beside the working-tree one, species by species. That is the
only view that answers "did this actually change", and CLAUDE.md requires it
before claiming an icon change landed.

Usage:  python tools/icon_sheet.py [out.png] [--compare [REV]]
        (needs the app running on 127.0.0.1:8090)
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARGS = sys.argv[1:]
COMPARE = "--compare" in ARGS
if COMPARE:
    i = ARGS.index("--compare")
    REV = ARGS[i + 1] if len(ARGS) > i + 1 else "HEAD"
    ARGS = ARGS[:i]
else:
    REV = "HEAD"
OUT = ARGS[0] if ARGS else "/tmp/icon_sheet.png"

# Every distinct silhouette in the sprite, in the order a reader meets them.
SHAPES = [
    # quick-log six first: these are the buttons the owner actually looks at.
    "roach", "bream", "rudd", "ide", "carp", "crucian",
    "tench", "pike", "perch", "zander", "catfish", "eel", "trout", "small",
]

TEMPLATE = "app/web/templates/_fish_icons.html"


def sprite_svg(source: str) -> str:
    """Pull just the sprite <svg> out of the Jinja template, dropping the macro."""
    return source[source.index("<svg"): source.index("</svg>") + 6]


def namespaced(svg: str, prefix: str) -> str:
    """Rename every id so two sprite versions can share one document.

    Symbol ids and gradient ids both collide, and a collision silently renders
    the wrong version - which is exactly the class of bug this tool exists to
    catch, so it must not introduce one.
    """
    svg = re.sub(r'id="([^"]+)"', rf'id="{prefix}\1"', svg)
    svg = re.sub(r'url\(#([^)]+)\)', rf'url(#{prefix}\1)', svg)
    # Internal <use href="#..."> too. Missing these renames the definition but
    # not the reference, so every <use> silently resolves to nothing and the
    # fish render as bare detail lines with no body - which looks exactly like a
    # catastrophic drawing bug and is purely an artefact of this tool.
    svg = re.sub(r'((?:xlink:)?href)="#([^"]+)"', rf'\1="#{prefix}\2"', svg)
    return svg


CURRENT = sprite_svg((ROOT / TEMPLATE).read_text(encoding="utf-8"))

if COMPARE:
    previous = subprocess.run(
        ["git", "show", f"{REV}:{TEMPLATE}"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    # The previous sprite may declare a shorter canvas; `<use>` centres a
    # symbol's own viewBox inside the viewport, so both render comparably.
    SPRITES = namespaced(sprite_svg(previous), "old-") + namespaced(CURRENT, "new-")
    COLUMNS = 2
    CELLS = "".join(
        f"""<div class="cell">
              <div class="pair">
                <div class="side"><em>before</em>
                  <svg class="fish-icon" width="112" height="58" viewBox="0 0 100 52">
                    <use href="#old-fish-{s}"></use></svg></div>
                <div class="side"><em>after</em>
                  <svg class="fish-icon" width="112" height="58" viewBox="0 0 100 52">
                    <use href="#new-fish-{s}"></use></svg></div>
              </div>
              <span>{s}</span>
            </div>"""
        for s in SHAPES
    )
    WIDTH = 900
else:
    SPRITES = namespaced(CURRENT, "new-")
    COLUMNS = 4
    CELLS = "".join(
        f"""<div class="cell">
              <svg class="fish-icon" width="92" height="48" viewBox="0 0 100 52">
                <use href="#new-fish-{s}"></use>
              </svg>
              <span>{s}</span>
            </div>"""
        for s in SHAPES
    )
    WIDTH = 780

PAGE = f"""
<link rel="stylesheet" href="http://127.0.0.1:8090/static/style.css">
<style>
  body {{ margin:0; background:#fff; font-family:system-ui,sans-serif; }}
  #sheet {{ display:grid; grid-template-columns:repeat({COLUMNS},1fr); gap:10px;
            padding:14px; width:{WIDTH - 20}px; }}
  .cell {{ display:flex; flex-direction:column; align-items:center; gap:6px;
           padding:14px 6px; border:1px solid #dbe6ef; border-radius:12px; background:#fff; }}
  .cell span {{ font-size:13px; font-weight:600; color:#3c5c75; }}
  .cell .fish-icon {{ animation:none !important; }}
  .pair {{ display:flex; gap:8px; width:100%; justify-content:center; }}
  .side {{ display:flex; flex-direction:column; align-items:center; gap:2px;
           flex:1; padding:6px 0; border-radius:8px; background:#f6fafc; }}
  .side em {{ font-size:10px; font-style:normal; letter-spacing:0.08em;
              text-transform:uppercase; color:#8aa5b8; }}
</style>
<body>{SPRITES}<div id="sheet">{CELLS}</div></body>
"""

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    page = browser.new_page(viewport={"width": WIDTH, "height": 900},
                            device_scale_factor=2)
    page.goto("http://127.0.0.1:8090/", wait_until="domcontentloaded")
    page.set_content(PAGE)
    page.wait_for_timeout(500)
    page.locator("#sheet").screenshot(path=OUT)
    browser.close()

print(f"wrote {OUT}")
