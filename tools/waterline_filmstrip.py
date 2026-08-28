"""Film the Waterline motion: the splash ring, the line ripple, the float bite.

CLAUDE.md's first verification rule: motion cannot be checked from a screenshot,
and it cannot be checked by reading your own keyframes. The fish pin dived tail
first through three rounds of "fixes" because nobody had looked at it.

tools/element_filmstrip.py pins an animation that is already running. These
three are not: they start on a real pointer event and finish in half a second.
So this drives the event for real, then pins the animation it started to exact
percentages of its cycle and tiles the frames.

    python tools/waterline_filmstrip.py --url http://127.0.0.1:8091/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# animation-play-state + a negative animation-delay pins an animation to an
# exact instant of its cycle without letting it advance while we photograph.
#
# Injected as a stylesheet rule, NOT as inline style. The waterline ripple and
# the loading swell both live on ::after / ::before, and a pseudo-element has no
# node to set `.style` on - the first version of this tool set inline styles and
# photographed eight identical frames of an animation that was running fine.
# That is the same class of mistake CLAUDE.md's motion rule exists for: the
# filmstrip looked authoritative and was measuring nothing.
PIN = """
(args) => {
  const [selector, ms] = args;
  const el = document.querySelector(selector);
  if (!el) return false;
  const style = document.createElement('style');
  style.textContent = `
    ${selector}, ${selector} *, ${selector}::before, ${selector}::after {
      animation-play-state: paused !important;
      animation-delay: -${ms}ms !important;
    }`;
  document.head.appendChild(style);
  return true;
}
"""

# Each: label, the element photographed, its animation length, and the script
# that puts the page into the state where that animation exists.
SCENES = [
    (
        "splash",
        ".splash",
        520,
        """() => {
            document.dispatchEvent(new PointerEvent('pointerdown',
              {clientX: 300, clientY: 300, button: 0, bubbles: true}));
        }""",
        (180, 180, 420, 420),
    ),
    (
        "waterline",
        ".waterline",
        620,
        """() => {
            const l = document.querySelector('.waterline');
            const r = l.getBoundingClientRect();
            document.dispatchEvent(new PointerEvent('pointerdown',
              {clientX: r.left + r.width / 2, clientY: r.top, button: 0, bubbles: true}));
        }""",
        None,
    ),
    (
        "bite",
        ".btn-primary",
        480,
        """() => {
            const b = document.querySelector('.btn-primary')
                   || document.querySelector('.btn');
            if (!b) return;
            b.classList.add('btn-primary', 'is-biting');
        }""",
        "FIXED",
    ),
]

STEPS = [0, 12, 25, 40, 55, 70, 85, 100]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8091/")
    ap.add_argument("--out", default="tools/design_shots/motion.png")
    args = ap.parse_args(argv)

    from PIL import Image, ImageDraw
    from playwright.sync_api import sync_playwright

    rows: list[tuple[str, list[Image.Image]]] = []
    tmp = Path("tools/design_shots/_frames")
    tmp.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for label, selector, duration, trigger, clip in SCENES:
            frames: list[Image.Image] = []
            fixed: dict | None = None
            for pct in STEPS:
                page = browser.new_page(viewport={"width": 900, "height": 620})
                page.goto(args.url, wait_until="networkidle")
                page.wait_for_timeout(300)
                page.evaluate(trigger)
                page.wait_for_timeout(30)
                if not page.evaluate(PIN, [selector, int(duration * pct / 100)]):
                    print(f"  {label}: selector {selector} not found at {pct}%")
                    page.close()
                    continue
                shot = tmp / f"{label}-{pct:03d}.png"
                if clip == "FIXED":
                    # A translating element must be photographed against a FIXED
                    # frame. Playwright's element screenshot follows the element,
                    # so it cancels the very translation being filmed - the first
                    # cut of this produced eight identical frames of a button
                    # that was moving 4px. Measured once, before the animation is
                    # pinned, and reused for every frame.
                    if fixed is None:
                        box = page.evaluate(
                            """(sel) => {
                                const e = document.querySelector(sel);
                                const r = e.getBoundingClientRect();
                                return {x: r.left - 6, y: r.top - 14,
                                        width: r.width + 12, height: r.height + 28};
                            }""",
                            selector,
                        )
                        fixed = box
                    page.screenshot(path=str(shot), clip=fixed)
                elif clip:
                    x0, y0, x1, y1 = clip
                    page.screenshot(
                        path=str(shot),
                        clip={"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0},
                    )
                else:
                    el = page.query_selector(selector)
                    (el or page).screenshot(path=str(shot))
                frames.append(Image.open(shot).convert("RGB"))
                page.close()
            if frames:
                rows.append((label, frames))
        browser.close()

    if not rows:
        print("nothing filmed")
        return 1

    pad, label_w, head = 8, 96, 22
    col_w = max(max(f.width for f in fr) for _, fr in rows)
    sheet_w = label_w + len(STEPS) * (col_w + pad) + pad
    sheet_h = head + sum(max(f.height for f in fr) + head + pad for _, fr in rows) + pad
    sheet = Image.new("RGB", (sheet_w, sheet_h), (250, 250, 250))
    d = ImageDraw.Draw(sheet)
    for i, pct in enumerate(STEPS):
        d.text((label_w + i * (col_w + pad), 6), f"{pct}%", fill=(40, 40, 40))

    y = head
    for label, frames in rows:
        row_h = max(f.height for f in frames)
        d.text((6, y + row_h // 2), label, fill=(20, 20, 20))
        for i, f in enumerate(frames):
            sheet.paste(f, (label_w + i * (col_w + pad), y))
        y += row_h + head + pad

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
