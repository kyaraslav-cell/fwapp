"""Render the water-type switch in every state, in every language, as one sheet.

A segmented switch is only right if the thumb sits under the option that is
actually on, in every language, without the label wrapping or spilling out of
the track. None of that is visible in a diff - the CSS reads the same whether
the thumb lands on the third segment or half a segment past it - so this
photographs the real control served by the real app.

`--strip` instead films the thumb sliding: navigation is suppressed and the
control is screenshotted every frame for ~300 ms, because CLAUDE.md's rule that
motion cannot be checked by reading your own keyframes applies to a transition
just as much as to an animation.

Before/after: run this on the previous revision first (`git stash` or a
worktree), keep the PNG, then run it again on the working tree and put the two
side by side. Describing the change is not evidence that it landed.

Usage:  python tools/switch_sheet.py [out.png] [--strip]
        (needs the app running on 127.0.0.1:8090)
"""

from __future__ import annotations

import base64
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8090"
CHROMIUM = "/opt/pw-browsers/chromium"
STATES = [("all", "/"), ("pzw", "/?water=pzw"), ("commercial", "/?water=commercial")]
LANGS = ["en", "pl", "ru"]

ARGS = sys.argv[1:]
STRIP = "--strip" in ARGS
ARGS = [a for a in ARGS if not a.startswith("--")]
OUT = ARGS[0] if ARGS else ("/tmp/switch_strip.png" if STRIP else "/tmp/switch_sheet.png")
TMP = pathlib.Path("/tmp/switch_frames")


def contact_sheet(rows: list[tuple[str, pathlib.Path]], out: str, width: int = 560) -> None:
    """Tile labelled PNGs into one image, inlined so nothing is fetched."""
    body = "".join(
        f'<div class="row"><div class="lab">{label}</div>'
        f'<img src="data:image/png;base64,{base64.b64encode(path.read_bytes()).decode()}"></div>'
        for label, path in rows
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM)
        page = browser.new_page(viewport={"width": width, "height": 900}, device_scale_factor=2)
        page.set_content(
            "<style>body{font:13px/1.4 system-ui,sans-serif;background:#fff;margin:0;"
            "padding:16px}.row{margin-bottom:12px}.lab{color:#667;font-weight:600;"
            "margin-bottom:4px}img{width:100%;display:block}</style>" + body
        )
        page.screenshot(path=out, full_page=True)
        browser.close()


def main() -> None:
    TMP.mkdir(exist_ok=True)
    rows: list[tuple[str, pathlib.Path]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM)
        page = browser.new_page(viewport={"width": 420, "height": 900}, device_scale_factor=3)
        # Google Fonts is unreachable from the build sandbox, so `load` never
        # fires; the markup and the stylesheet are what this tool is looking at.
        page.set_default_timeout(45_000)

        if STRIP:
            page.goto(f"{BASE}/", wait_until="domcontentloaded")
            page.evaluate(
                "document.querySelectorAll('.switch-option')"
                ".forEach(a => a.addEventListener('click', e => e.preventDefault()))"
            )
            box = page.locator(".switch").bounding_box()
            assert box is not None
            clip = {
                "x": box["x"], "y": box["y"] - 4,
                "width": box["width"], "height": box["height"] + 8,
            }
            page.locator(".switch-option").nth(len(STATES) - 1).click(no_wait_after=True)
            start = time.time()
            for i in range(9):
                frame = TMP / f"strip{i}.png"
                page.screenshot(path=str(frame), clip=clip, animations="allow")
                rows.append((f"+{int((time.time() - start) * 1000)} ms", frame))
        else:
            for lang in LANGS:
                page.goto(f"{BASE}/lang/{lang}?next=/", wait_until="domcontentloaded")
                for name, path in STATES:
                    page.goto(BASE + path, wait_until="domcontentloaded")
                    shot = TMP / f"{lang}_{name}.png"
                    page.locator(".switch").screenshot(path=str(shot))
                    rows.append((f"{lang.upper()} · {path}", shot))
        browser.close()

    contact_sheet(rows, OUT, width=460 if STRIP else 560)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
