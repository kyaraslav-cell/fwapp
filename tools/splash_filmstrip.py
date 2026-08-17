"""Fire the real splash and photograph it at fixed intervals.

The dive filmstrip pins one element's CSS animation with a negative delay. The
splash cannot be checked that way: it is a dozen elements created by JS, with
staggered delays and randomised droplet arcs, so there is no single animation
to pin. This drives the real `splash()` from `lake_detail.html` and screenshots
the layer on a timer instead.

Usage:  python tools/splash_filmstrip.py [out_dir]
        (needs the app running on 127.0.0.1:8090)
"""

from __future__ import annotations

import pathlib
import sys

from playwright.sync_api import sync_playwright

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/splash")
OUT.mkdir(parents=True, exist_ok=True)

# Sampled across the full life of the splash: impact, crown, spray, spread.
STOPS_MS = [0, 60, 120, 200, 300, 420, 560, 760, 1000, 1300]

STAGE = """
<div id="map-wrap" class="map-wrap" style="width:560px;height:300px;
     background:linear-gradient(#6d9ec4,#3d6f9b);">
  <div style="position:absolute;inset:0;background:
       repeating-linear-gradient(0deg,rgba(255,255,255,.05) 0 2px,transparent 2px 9px);"></div>
</div>
"""

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    page = browser.new_page(viewport={"width": 560, "height": 300},
                            device_scale_factor=2)
    page.goto("http://127.0.0.1:8090/", wait_until="domcontentloaded")

    # Reuse the page's own splash() rather than a copy of it - a filmstrip of a
    # reimplementation would prove nothing about what ships.
    splash_src = page.evaluate(
        """async () => {
             const html = await (await fetch('/lake/pomocnia')).text();
             const start = html.indexOf('function splashLayer(');
             const end = html.indexOf('// Weather rows recolour');
             return start < 0 || end < 0 ? null : html.slice(start, end);
           }"""
    )
    if not splash_src:
        raise SystemExit("could not find splash() in the lake page - did it move?")

    page.set_content(
        '<link rel="stylesheet" href="http://127.0.0.1:8090/static/style.css">'
        f'<body style="margin:0">{STAGE}</body>'
    )
    page.add_script_tag(content=splash_src)
    page.wait_for_timeout(300)

    previous = 0
    page.evaluate("() => splash({x: 280, y: 150})")
    for stop in STOPS_MS:
        page.wait_for_timeout(max(stop - previous, 0))
        previous = stop
        page.locator("#map-wrap").screenshot(path=str(OUT / f"splash_{stop:04d}.png"))

    browser.close()

print(f"wrote {len(STOPS_MS)} frames to {OUT}")
