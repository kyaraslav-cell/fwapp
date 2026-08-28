"""Downscale and compress the generated stills into what the app actually ships.

kie.ai returns ~2736px PNGs at 5-7MB. That is a source file, not a web asset:
serving one over a lakeside connection would cost more than the rest of the app
put together. These are soft, low-contrast, low-detail images, which is the case
WebP handles best - so they compress to a fraction of a percent of the original
with no visible loss at the sizes they are actually displayed at.

Two widths each, picked from where the layout's breakpoints already are, so a
phone never downloads the desktop file.
"""

from __future__ import annotations

import pathlib
import sys

from PIL import Image

SRC = pathlib.Path("tools/asset_out")
DEST = pathlib.Path("app/web/static/img")

# name -> (desktop width, phone width, quality, crop)
#
# `crop` is a vertical (top, bottom) fraction of the source, applied before the
# resize. The hero needed one: seedream composed it with an enormous empty sky,
# which is correct for a full-frame image with copy on it but wrong for a 200px
# band - cropped to the whole frame the band rendered as a featureless cream
# rectangle. Taking the bottom half puts the reed line, the horizon and the
# water in the band, which is the half that carries the picture.
PLAN = {
    "water-hero": (1600, 780, 76, (0.55, 0.95)),
    "float-rings": (1100, 620, 78, (0.0, 1.0)),
}

# The stills are pulled onto the palette's temperature axis. This is a real
# per-channel scale, not a mood: an image a few percent off the ground's
# temperature reads as belonging to a different design, and the eye catches it
# long before it can name why.
#
# It was a COOLING scale under Waterline, whose ground was #eef4f4. The cosy
# tackle ground is kraft (#efe7d6), so the same images now had to be WARMED
# back - shipped once cooled, they sat on the new ground as a blue-green photo
# on a warm page, which is exactly the failure the cooling existed to prevent.
# Found by rendering the home page and looking, not by reading this file.
#
# Applied here rather than in CSS: a filter on a large image costs a repaint on
# every scroll frame, and this costs nothing at runtime.
TEMPERATURE = (1.045, 1.004, 0.945)

BUDGET_KB = 90


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    failed = False
    for name, (wide, narrow, quality, crop) in PLAN.items():
        src = SRC / f"{name}.png"
        if not src.exists():
            print(f"skip {name}: {src} not generated")
            continue
        im = Image.open(src).convert("RGB")
        top, bottom = crop
        if (top, bottom) != (0.0, 1.0):
            im = im.crop((0, round(im.height * top), im.width, round(im.height * bottom)))
        r, g, b = im.split()
        im = Image.merge(
            "RGB",
            (
                r.point(lambda v: min(255, round(v * TEMPERATURE[0]))),
                g.point(lambda v: min(255, round(v * TEMPERATURE[1]))),
                b.point(lambda v: min(255, round(v * TEMPERATURE[2]))),
            ),
        )
        for label, width in (("", wide), ("-m", narrow)):
            out = DEST / f"{name}{label}.webp"
            h = round(im.height * width / im.width)
            im.resize((width, h), Image.LANCZOS).save(
                out, "WEBP", quality=quality, method=6
            )
            kb = out.stat().st_size / 1024
            flag = "" if kb <= BUDGET_KB else f"  OVER BUDGET ({BUDGET_KB}KB)"
            print(f"{out}  {width}x{h}  {kb:.1f}KB{flag}")
            if kb > BUDGET_KB:
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
