"""Freeze any element's CSS animation at fixed points and tile the frames.

    python tools/element_filmstrip.py --url http://127.0.0.1:8000/ \
        --selector .session-fab --duration 4200 --out /tmp/fab.png

`tools/animation_filmstrip.py` does this for the fish pin against a synthetic
harness. This does it for a real element on a real page, which is what you need
when the animation only exists once the app renders it.

**Why this exists at all.** Motion cannot be judged from a screenshot, and it
cannot be judged by reading keyframes: the fish pin dived TAIL FIRST through
three rounds of "improvements" because nobody had looked at it. The trick is
`animation-play-state: paused` plus a negative `animation-delay`, which pins an
animation to an exact percentage of its cycle, so the frames can be tiled and
inspected side by side.

Every animation inside the element is pinned to the same instant, so a float
and the ripple around it are seen as one event rather than two.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PIN = """
(args) => {
  const [selector, ms] = args;
  const root = document.querySelector(selector);
  if (!root) return false;
  const nodes = [root, ...root.querySelectorAll('*')];
  for (const el of nodes) {
    el.style.animationPlayState = 'paused';
    el.style.animationDelay = `-${ms}ms`;
  }
  return true;
}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--selector", required=True)
    parser.add_argument("--duration", type=int, default=1000, help="cycle length, ms")
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pad", type=int, default=14, help="pixels of margin around the element")
    parser.add_argument("--scale", type=int, default=4)
    parser.add_argument(
        "--storage-state",
        type=Path,
        default=None,
        help="playwright storage state, for an element only a signed-in angler sees",
    )
    args = parser.parse_args(argv)

    from PIL import Image
    from playwright.sync_api import sync_playwright

    shots: list[Path] = []
    args.out.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 420, "height": 900},
            device_scale_factor=args.scale,
            storage_state=str(args.storage_state) if args.storage_state else None,
        )
        page = context.new_page()
        page.goto(args.url, wait_until="networkidle", timeout=45_000)
        page.wait_for_timeout(1200)

        element = page.query_selector(args.selector)
        if element is None:
            raise SystemExit(f"no element matching {args.selector!r} on {args.url}")
        box = element.bounding_box()
        if box is None:
            raise SystemExit(f"{args.selector!r} is not visible")

        clip = {
            "x": box["x"] - args.pad,
            "y": box["y"] - args.pad,
            "width": box["width"] + args.pad * 2,
            "height": box["height"] + args.pad * 2,
        }

        for i in range(args.frames):
            at = round(args.duration * i / args.frames)
            if not page.evaluate(PIN, [args.selector, at]):
                raise SystemExit("element vanished while filming")
            page.wait_for_timeout(60)
            shot = args.out.parent / f"_frame_{i:02d}.png"
            page.screenshot(path=str(shot), clip=clip)
            shots.append(shot)
        browser.close()

    frames = [Image.open(s) for s in shots]
    width, height = frames[0].size
    strip = Image.new("RGB", (width * len(frames), height), "white")
    for i, frame in enumerate(frames):
        strip.paste(frame, (i * width, 0))
    strip.save(args.out)
    for shot in shots:
        shot.unlink(missing_ok=True)

    print(f"{len(frames)} frames across {args.duration} ms -> {args.out}")
    print("Frames run left to right, 0% to " f"{100 * (args.frames - 1) // args.frames}%.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
