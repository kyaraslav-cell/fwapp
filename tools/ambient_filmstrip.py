"""Film the ambient fish, because motion cannot be judged any other way.

CLAUDE.md's first verification rule. The fish pin shipped diving TAIL FIRST
three times while the keyframes read correctly, so an animation is not "done"
until its frames are tiled and looked at.

Three traps this tool is written around, all of which have caught this project:

  1. A pseudo-element has no node to set inline style on, so pinning by inline
     style silently photographs the same frame N times. The ambient fish are
     real elements, so inline pinning is safe here - but the check below asserts
     the frames actually differ, which is what would have caught it.
  2. Playwright's *element* screenshot follows the element, subtracting exactly
     the translation being filmed. So this shoots a FIXED viewport clip.
  3. The arc lives on a nested element and the crossing on its parent. Both must
     be pinned to the same progress or the fish flies level.

Usage:  python tools/ambient_filmstrip.py [base_url] [out_name]
"""

from __future__ import annotations

import pathlib
import sys

from PIL import Image
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8097"
OUT = pathlib.Path("tools/design_shots") / (sys.argv[2] if len(sys.argv) > 2 else "ambient.png")

# The fish is only on screen for the first quarter of its cycle; the rest is
# the long wait that makes it occasional rather than a parade. Sample the part
# that is actually visible.
STOPS = [0.02, 0.05, 0.08, 0.11, 0.13, 0.15, 0.18, 0.21, 0.24]
# The layer is position:fixed, so the clip is viewport-relative and the
# first fish sits at 22% of 700px. Do not "helpfully" reposition the layer
# to make it easier to find - that moved it out of the clip and produced a
# strip of nine identical frames that reported the animation as dead.
CLIP = {"x": 0, "y": 120, "width": 900, "height": 130}

# An inline `opacity` does NOT hold against a running animation - the animation
# wins the cascade, so the first version of this tool filmed a fish the
# keyframes had faded to zero and reported nine identical frames. An author
# `!important` rule does beat an animation, so the opacity override is injected
# as a stylesheet instead. This is the same fix the waterline filmstrip needed
# for its pseudo-element, arrived at from the other direction.
FORCE_VISIBLE = """
.ambient-fish { opacity: 1 !important; }
"""

PIN = """
(progress) => {
  document.querySelectorAll('.ambient-fish, .ambient-fish-arc').forEach((el) => {
    // Every fish is pinned to one shared duration so the strip shows one
    // animal's arc rather than four at different phases.
    el.style.animationDuration = '10s';
    el.style.animationDelay = (-10 * progress) + 's';
    el.style.animationPlayState = 'paused';
  });
  // Keep just the first fish so the strip reads as one flight.
  document.querySelectorAll('.ambient-fish').forEach((el, i) => {
    if (i > 0) el.style.display = 'none';
    else el.style.left = '40px';
  });
}
"""


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames: list[Image.Image] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 900, "height": 700})
        page.goto(BASE + "/", wait_until="networkidle")
        page.add_style_tag(content=FORCE_VISIBLE)
        for i, stop in enumerate(STOPS):
            page.evaluate(PIN, stop)
            shot = OUT.parent / f"_ambient_f{i}.png"
            page.screenshot(path=str(shot), clip=CLIP)
            frames.append(Image.open(shot).convert("RGB"))
        browser.close()

    w, h = frames[0].size
    sheet = Image.new("RGB", (w, h * len(frames) + 4 * (len(frames) - 1)), (255, 255, 255))
    for i, f in enumerate(frames):
        sheet.paste(f, (0, i * (h + 4)))
    sheet.save(OUT)

    # A filmstrip that photographs one frame N times is worse than none: it
    # reports success for an animation that never moved. Prove the frames differ.
    first, last = frames[0].tobytes(), frames[-1].tobytes()
    identical = sum(1 for f in frames[1:] if f.tobytes() == first)
    print(f"wrote {OUT}  ({len(frames)} frames)")
    if first == last or identical >= len(frames) - 2:
        print("FAIL: the frames are (nearly) identical - the pin is not driving "
              "the animation, so this strip proves nothing.")
        return 1
    print("frames differ - the strip is measuring something real")
    return 0


if __name__ == "__main__":
    sys.exit(main())
