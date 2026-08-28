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
    # ---- grounds ----
    "canvas": "#efe7d6",
    "canvas-deep": "#eae1cd",
    "surface": "#fbf7ef",
    "surface-sunk": "#f4eee0",
    "accent-wash": "#f7eadb",
    # ---- ink ----
    "ink": "#2e2a20",
    "ink-soft": "#5a5242",
    "ink-faint": "#6b6250",
    # ---- accent ----
    "accent": "#a04a14",
    "accent-soft": "#e9c9a3",
    "accent-deep": "#7a3a10",
    "line": "#ded2b8",
    # ---- day bands: the tint carries text, the mark carries the signal ----
    "band-green": "#d6e9d2",
    "band-yellow": "#e6ebcb",
    "band-orange": "#f7e2c0",
    "band-red": "#f3d2cb",
    "mark-green": "#2f7d4f",
    "mark-yellow": "#6b7f2c",
    "mark-orange": "#9e6712",
    "mark-red": "#b03d24",
    # ---- semantic inks. These four were previously LITERALS INSIDE THE ALIAS
    # BLOCK of style.css (--primary-text, --accent-green-text,
    # --accent-coral-text, --danger-strong), which meant this checker could not
    # see them and never contrast-tested them. They are palette tokens now and
    # they are checked here. Do not let one drift back into the alias block.
    "positive-ink": "#1f5c3a",
    "warn-ink": "#7a2f1a",
    "danger": "#9c3a22",
    "danger-deep": "#832e1a",
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
    "accent-deep": 4.5,
    "positive-ink": 4.5,
    "warn-ink": 4.5,
    "danger": 4.5,
    "danger-deep": 4.5,
    "line": 1.0,
}

# The four day-band marks are signals, not text. WCAG 2.1 puts non-text UI
# components and graphical objects at 3.0 against what sits next to them, which
# here is the band tint the mark is drawn on.
MARK_ON_BAND = {
    "mark-green": "band-green",
    "mark-yellow": "band-yellow",
    "mark-orange": "band-orange",
    "mark-red": "band-red",
}

# The conditions ring draws the mark as a stroke on --canvas-deep rather than on
# its own tint (the owner asked for the inside of the ring to stay in the
# design's palette). That is a different pair from the one above and it has to
# clear the same 3.0, or the day's colour stops being findable.
RING_GROUND = "canvas-deep"


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

    print()
    for mk in MARK_ON_BAND:
        r = ratio(TOKENS[mk], TOKENS[RING_GROUND])
        ok = "ok" if r >= 3.0 else "FAIL"
        print(f"{mk:<12} on {RING_GROUND:<12} {r:>6.2f}  {ok}   (conditions ring)")
        if r < 3.0:
            failures.append(f"{mk} on {RING_GROUND}: {r:.2f} < 3.0")

    print()
    for mk, band in MARK_ON_BAND.items():
        r = ratio(TOKENS[mk], TOKENS[band])
        ok = "ok" if r >= 3.0 else "FAIL"
        print(f"{mk:<12} on {band:<12} {r:>6.2f}  {ok}")
        if r < 3.0:
            failures.append(f"{mk} on {band}: {r:.2f} < 3.0")

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
