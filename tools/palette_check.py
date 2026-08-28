"""Measure every foreground/background pair the design actually uses.

The nightly audit (`reports/site_audit/`) found colour-contrast failures by
driving a browser with axe-core, which is the truth but is also slow and only
sees the pairs that happen to be on screen. This checks the palette itself, so
a failing pair is caught when the token is chosen rather than a night later.

WCAG 2.1 relative luminance and contrast ratio. No dependency.
"""

from __future__ import annotations

import sys

Rgb = tuple[float, float, float]


def srgb(value: str) -> Rgb:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def luminance(colour: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in srgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    lo, hi = sorted((a, b))
    return (hi + 0.05) / (lo + 0.05)


TOKENS = {
    "canvas": "#eef4f4",
    "canvas-deep": "#e3edee",
    "surface": "#ffffff",
    "surface-sunk": "#f4f9f9",
    "ink": "#0f2c40",
    "ink-soft": "#415f72",
    "ink-faint": "#526d7d",
    "accent": "#2a765d",
    "accent-soft": "#8fcdb6",
    "accent-wash": "#dcefe7",
    "line": "#d2e1e3",
    "band-green": "#7fc9a8",
    "band-yellow": "#e8d08a",
    "band-orange": "#eeb08a",
    "band-red": "#e59a8c",
    "danger": "#b24739",
}

GROUNDS = ("canvas", "canvas-deep", "surface", "surface-sunk", "accent-wash")

# fg token -> minimum ratio it must clear on every ground in GROUNDS.
# 4.5 is WCAG AA body text; 3.0 is large text (>=24px, or >=19px bold) and the
# non-text minimum for controls and focus rings.
REQUIRED = {
    "ink": 4.5,
    "ink-soft": 4.5,
    "ink-faint": 4.5,
    "accent": 4.5,
    "danger": 4.5,
    "line": 1.0,
}


def main() -> int:
    failures: list[str] = []
    print(f"{'':<14}" + "".join(f"{g:>14}" for g in GROUNDS))
    for fg, minimum in REQUIRED.items():
        cells = []
        for ground in GROUNDS:
            r = ratio(TOKENS[fg], TOKENS[ground])
            mark = " " if r >= minimum else "!"
            cells.append(f"{r:>12.2f}{mark} ")
            if r < minimum:
                failures.append(f"{fg} on {ground}: {r:.2f} < {minimum}")
        print(f"{fg:<14}" + "".join(cells))

    print()
    for band in ("band-green", "band-yellow", "band-orange", "band-red", "accent-soft"):
        r = ratio(TOKENS["ink"], TOKENS[band])
        mark = "ok" if r >= 4.5 else "FAIL"
        print(f"ink on {band:<12} {r:>6.2f}  {mark}")
        if r < 4.5:
            failures.append(f"ink on {band}: {r:.2f} < 4.5")

    r = ratio("#ffffff", TOKENS["accent"])
    print(f"{'white on accent':<19} {r:>6.2f}  {'ok' if r >= 4.5 else 'FAIL'}")
    if r < 4.5:
        failures.append(f"white on accent: {r:.2f} < 4.5")

    print()
    if failures:
        for f in failures:
            print("FAIL " + f)
        return 1
    print("All pairs clear their minimum.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
