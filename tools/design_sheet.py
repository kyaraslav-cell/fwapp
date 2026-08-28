"""Photograph the real app at desktop and phone width, and tile old beside new.

CLAUDE.md's second verification rule: visual design cannot be checked from your
own diff. The species icons were declared redrawn three times and still looked
identical. So a design change is not "done" until the previous render and the
current one are sitting next to each other in one image.

This differs from tools/site_audit.py, which asks whether anything is *broken*.
This one asks whether anything *changed*, and shows it.

Usage:
    # before the change
    python tools/design_sheet.py --base-url http://127.0.0.1:8091 --shoot before
    # ...make the change, restart the app...
    python tools/design_sheet.py --base-url http://127.0.0.1:8091 --shoot after
    python tools/design_sheet.py --compare            # writes the tiled sheet
"""

from __future__ import annotations

import argparse
import pathlib
import sys

OUT = pathlib.Path("tools/design_shots")

# Every page an angler actually walks through, plus the two the audit baselines
# already cover so a regression there is visible in the same sheet.
PAGES: list[tuple[str, str]] = [
    ("home", "/"),
    ("lake", "/lake/pomocnia"),
    ("login", "/auth/login"),
    ("register", "/auth/register"),
    ("places-new", "/places/new"),
    ("history", "/history"),
]

WIDTHS = {"desktop": (1280, 900), "phone": (390, 844)}


def shoot(base_url: str, label: str) -> int:
    from playwright.sync_api import sync_playwright

    target = OUT / label
    target.mkdir(parents=True, exist_ok=True)
    shot = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for device, (w, h) in WIDTHS.items():
            page = browser.new_page(viewport={"width": w, "height": h})
            for name, path in PAGES:
                try:
                    page.goto(base_url + path, wait_until="networkidle", timeout=20000)
                except Exception as exc:  # a page that will not load is a finding
                    print(f"  {device}/{name}: FAILED to load - {exc}")
                    continue
                # Motion must be stopped before the shutter or the same page
                # photographs differently every run and every diff is noise.
                page.add_style_tag(
                    content=(
                        "*,*::before,*::after{animation:none!important;"
                        "transition:none!important;scroll-behavior:auto!important}"
                    )
                )
                # Wait for every image to actually DECODE, not merely load.
                # `networkidle` only says the bytes arrived; a full-page capture
                # taken before decode renders the container background instead
                # of the image, which reads as a broken asset in the sheet.
                page.evaluate(
                    """() => Promise.all(
                        [...document.images]
                          .filter(i => i.currentSrc)
                          .map(i => i.decode().catch(() => null))
                    )"""
                )
                page.wait_for_timeout(250)
                page.screenshot(path=str(target / f"{device}-{name}.png"), full_page=True)
                shot += 1
            page.close()
        browser.close()
    print(f"{shot} shots -> {target}")
    return shot


def compare() -> int:
    from PIL import Image, ImageDraw

    before, after = OUT / "before", OUT / "after"
    if not before.exists() or not after.exists():
        print("Need both tools/design_shots/before and /after. Shoot them first.")
        return 1

    pairs = sorted(p.name for p in after.glob("*.png"))
    if not pairs:
        print("No shots in after/.")
        return 1

    # One sheet per device, so a phone column is never squeezed next to a
    # desktop one and made unreadable.
    written = []
    for device in WIDTHS:
        names = [n for n in pairs if n.startswith(device + "-")]
        if not names:
            continue
        cols = []
        for name in names:
            b_path, a_path = before / name, after / name
            b = Image.open(b_path).convert("RGB") if b_path.exists() else None
            a = Image.open(a_path).convert("RGB")
            cols.append((name, b, a))

        scale = 460 / max(c[2].width for c in cols)
        pad, label_h = 24, 34

        def fit(im: Image.Image | None) -> Image.Image:
            if im is None:
                return Image.new("RGB", (460, 200), (240, 240, 240))
            w = int(im.width * scale)
            h = int(im.height * scale)
            return im.resize((w, h), Image.LANCZOS)

        rendered = [(n, fit(b), fit(a)) for n, b, a in cols]
        col_w = max(max(b.width, a.width) for _, b, a in rendered)
        row_h = max(max(b.height, a.height) for _, b, a in rendered)
        # cap very tall full-page shots so the sheet stays viewable
        row_h = min(row_h, 1400)

        sheet_w = pad + len(rendered) * (col_w * 2 + pad * 2)
        sheet_h = label_h * 2 + row_h + pad * 2
        sheet = Image.new("RGB", (sheet_w, sheet_h), (250, 250, 250))
        draw = ImageDraw.Draw(sheet)
        draw.text((pad, 8), f"{device}   left = before, right = after", fill=(20, 20, 20))

        x = pad
        for name, b, a in rendered:
            draw.text((x, label_h - 4), name.replace(device + "-", ""), fill=(60, 60, 60))
            sheet.paste(b.crop((0, 0, b.width, min(b.height, row_h))), (x, label_h * 2))
            sheet.paste(
                a.crop((0, 0, a.width, min(a.height, row_h))), (x + col_w + pad, label_h * 2)
            )
            rule_x = x + col_w * 2 + pad + pad // 2
            draw.line(
                [(rule_x, label_h), (rule_x, sheet_h)], fill=(200, 200, 200), width=1
            )
            x += col_w * 2 + pad * 2

        out = OUT / f"sheet-{device}.png"
        sheet.save(out)
        written.append(out)

    for w in written:
        print(f"wrote {w}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8091")
    ap.add_argument("--shoot", choices=["before", "after"])
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args()

    if args.shoot:
        return 0 if shoot(args.base_url, args.shoot) else 1
    if args.compare:
        return compare()
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
