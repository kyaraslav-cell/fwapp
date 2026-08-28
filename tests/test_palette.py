"""The design's colours must clear WCAG AA, and the stylesheet must use them.

Two separate failures are guarded here, because they happen for different
reasons and only one of them is about maths:

  1. A token is chosen that does not have enough contrast. The nightly browser
     audit catches this, but a night later and only on the pages it happened to
     walk. `tools/palette_check.py` catches it at the point the value is picked.

  2. The palette is fine and the stylesheet quietly stops using it. This is the
     one that actually happened: the app carried 43 hardcoded hex values, some
     of them from a palette two designs old, and no test noticed because every
     token in isolation was correct.

`docs/17-DESIGN-SYSTEM.md` is the prose version of this file.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from tools.palette_check import GROUNDS, REQUIRED, TOKENS, ratio

STYLESHEET = pathlib.Path("app/web/static/style.css")


@pytest.mark.parametrize("token", sorted(REQUIRED))
def test_every_foreground_clears_aa_on_every_ground(token: str) -> None:
    minimum = REQUIRED[token]
    for ground in GROUNDS:
        got = ratio(TOKENS[token], TOKENS[ground])
        assert got >= minimum, (
            f"--{token} on --{ground} is {got:.2f}:1, needs {minimum}:1. "
            f"Run tools/palette_check.py."
        )


@pytest.mark.parametrize(
    "band", ["band-green", "band-yellow", "band-orange", "band-red", "accent-soft"]
)
def test_ink_is_readable_on_every_day_band(band: str) -> None:
    """The day bands carry the whole verdict (CLAUDE.md standing rule 3), so a
    band the label cannot be read on is worse than no band at all."""
    got = ratio(TOKENS["ink"], TOKENS[band])
    assert got >= 4.5, f"--ink on --{band} is {got:.2f}:1"


def test_the_stylesheet_defines_every_palette_token() -> None:
    css = STYLESHEET.read_text(encoding="utf-8")
    for token, value in TOKENS.items():
        assert f"--{token}: {value};" in css, (
            f"--{token} is {value} in tools/palette_check.py but not in "
            f"{STYLESHEET}. The checker is then measuring a palette the app "
            f"does not use, which is worse than not checking at all."
        )


def test_the_old_palette_is_gone() -> None:
    """The Waterline design's colours, retired 2026-08-28 (docs/19). A leftover
    is invisible in review and obvious on screen: one navy card in a kraft app.
    The pastel-blue scheme before it is listed too - it was retired once already
    and a rule that survived two re-skins would survive a third."""
    css = STYLESHEET.read_text(encoding="utf-8")
    retired = {
        # Waterline - navy ink on pale water, reed green
        "#eef4f4": "Waterline --canvas",
        "#e3edee": "Waterline --canvas-deep",
        "#f4f9f9": "Waterline --surface-sunk",
        "#0f2c40": "Waterline --ink",
        "#415f72": "Waterline --ink-soft",
        "#526d7d": "Waterline --ink-faint",
        "#2a765d": "Waterline --accent",
        "#8fcdb6": "Waterline --accent-soft",
        "#dcefe7": "Waterline --accent-wash",
        "#d2e1e3": "Waterline --line",
        "#b9d0d3": "Waterline --line-strong",
        "#7fc9a8": "Waterline --band-green",
        "#e8d08a": "Waterline --band-yellow",
        "#eeb08a": "Waterline --band-orange",
        "#e59a8c": "Waterline --band-red",
        "#123f31": "Waterline --primary-text (an alias-block literal)",
        "#0e4d38": "Waterline --accent-green-text (an alias-block literal)",
        "#6b2a1c": "Waterline --accent-coral-text (an alias-block literal)",
        "#b24739": "Waterline --danger (an alias-block literal)",
        "#963a2e": "Waterline --danger-strong (an alias-block literal)",
        "#226150": "Waterline .btn-primary:hover, hardcoded",
        # the pastel blue before it
        "#f2f8fd": "pastel --bg",
        "#eaf3fb": "pastel --surface-alt",
        "#dbe9f5": "pastel --border",
        "#22384d": "pastel --text",
        "#6fb1e8": "pastel --primary",
        "#4a93d6": "pastel --primary-strong",
        "#0d3a63": "pastel --primary-text",
        "#e07a66": "pastel --danger",
    }
    for value, what in retired.items():
        # Comments may still name a retired colour to explain why it went.
        live = [
            line
            for line in css.splitlines()
            if value in line and not line.strip().startswith(("/*", "*", "//"))
        ]
        assert not live, f"{value} ({what}) is still live in {STYLESHEET}: {live}"


def test_the_alias_block_holds_no_literal_colour() -> None:
    """The defect this test exists for shipped and sat unnoticed: five colours
    were written as hex INSIDE the alias block, where tools/palette_check.py -
    which walks the palette layer - could not see them. They rendered on screen
    and were never contrast-tested. An alias may only ever be var(--something).
    """
    css = STYLESHEET.read_text(encoding="utf-8")
    marker = "Legacy role names"
    assert marker in css, "the alias block's header comment has moved"
    block = css[css.index(marker):]
    block = block[: block.index("}")]
    live = [
        line
        for line in block.splitlines()
        if re.search(r"#[0-9a-fA-F]{3,8}\b", line)
        and not line.strip().startswith(("/*", "*", "//"))
    ]
    assert not live, (
        "literal colour(s) in the alias block, invisible to palette_check.py: "
        f"{live}"
    )


def test_no_webfont_is_requested() -> None:
    """The app now ships a real typeface (docs/19b D3), but it is SELF-HOSTED.
    A third-party font origin is what this guards: it costs a DNS lookup and a
    connection on exactly the signal that can least afford one, and it re-opens
    a CSP hole nobody is watching. Checked in the stylesheet as well as the
    templates, because that is where the @font-face rules now live."""
    targets = list(pathlib.Path("app/web/templates").glob("*.html")) + [STYLESHEET]
    for target in targets:
        text = target.read_text(encoding="utf-8")
        for host in ("fonts.googleapis.com", "fonts.gstatic.com"):
            live = [
                line
                for line in text.splitlines()
                if host in line
                and "{#" not in line
                and not line.strip().startswith(("#}", "/*", "*"))
            ]
            assert not live, f"{target} requests {host}: {live}"


def test_the_faces_are_committed_and_within_budget() -> None:
    """Split by unicode-range so a reader downloads only their own alphabet: a
    Polish angler never fetches Cyrillic, and Baloo 2 ships no Cyrillic at all
    because Russian headings fall through to Nunito in the stack.

    The budget is the point. A "just add a weight" that doubles the download is
    invisible in review and costs real seconds at a waterside."""
    budget_kb = {
        "nunito-latin.woff2": 40,
        "nunito-latin-ext.woff2": 36,
        "nunito-cyrillic.woff2": 22,
        "baloo2-latin.woff2": 34,
        "baloo2-latin-ext.woff2": 28,
    }
    font_dir = pathlib.Path("app/web/static/fonts")
    css = STYLESHEET.read_text(encoding="utf-8")
    for name, budget in budget_kb.items():
        path = font_dir / name
        assert path.exists(), f"{path} is declared in {STYLESHEET} but not committed"
        kb = path.stat().st_size / 1024
        assert kb <= budget, f"{name} is {kb:.1f}KB, budget {budget}KB"
        assert f"/static/fonts/{name}" in css, f"{name} is committed but never used"
        assert path.read_bytes()[:4] == b"wOF2", f"{name} is not a woff2 file"

    assert css.count("font-display: swap") >= 5, (
        "every @font-face needs font-display: swap - invisible text on a "
        "riverbank is a worse failure than a swap"
    )


def test_the_generated_assets_stay_small() -> None:
    """Both raster assets ship in the repository, so nothing here calls kie.ai
    at runtime. The budget is the point: these load at the waterside."""
    budget_kb = {"water-hero.webp": 40, "water-hero-m.webp": 12,
                 "float-rings.webp": 20, "float-rings-m.webp": 8}
    img_dir = pathlib.Path("app/web/static/img")
    for name, budget in budget_kb.items():
        path = img_dir / name
        assert path.exists(), f"{path} is referenced by a template but not committed"
        kb = path.stat().st_size / 1024
        assert kb <= budget, f"{name} is {kb:.1f}KB, budget {budget}KB"


def test_motion_respects_reduced_motion() -> None:
    """Every animation this design adds must be answerable by the media query.
    Reduced motion means fewer and gentler, not zero - so the block must exist
    and must name each moving part."""
    css = STYLESHEET.read_text(encoding="utf-8")
    marker = "@media (prefers-reduced-motion: reduce)"
    assert marker in css
    # Every such block, not just the last one. The first version of this test
    # read `split(marker)[-1]`, so adding a SECOND reduced-motion block - which
    # is the natural way to keep a new effect's answer beside the effect -
    # hid the first block from the test and failed on rules that were present.
    blocks = css.split(marker)[1:]
    covered = "".join(blocks)
    for moving in (
        ".splash",
        ".waterline::after",
        ".js-reveal",
        ".is-biting",
        ".ambient",
    ):
        assert moving in covered, f"{moving} is not handled under reduced motion"


def test_the_reveal_cannot_permanently_hide_content() -> None:
    """The hidden state must be applied by script and never by the stylesheet
    alone. With JS off, broken, or slow, every card has to be readable.

    This is not hypothetical: the first cut hid every card on load and left the
    top of the page blank until an observer fired. Caught by looking at
    tools/design_sheet.py output, not by any test - so here is the test.
    """
    css = STYLESHEET.read_text(encoding="utf-8")
    # Exact, not a substring: `".js-reveal { opacity: 0" in css` also matches
    # `opacity: 0.99`, which is not hidden at all. Proven by mutating the value
    # and watching the first version of this test still pass.
    assert re.search(r"\.js-reveal\s*\{[^}]*opacity:\s*0\s*[;}]", css), (
        "the hidden state moved or is no longer fully transparent; re-check this test"
    )
    # The class that hides must not be reachable from markup alone.
    for template in pathlib.Path("app/web/templates").glob("*.html"):
        assert "js-reveal" not in template.read_text(encoding="utf-8"), (
            f"{template} hardcodes js-reveal; content would stay hidden without JS"
        )

    js = pathlib.Path("app/web/static/waterline.js").read_text(encoding="utf-8")
    assert 'classList.add("js-reveal")' in js
    # and something must always take it back off again
    assert "is-surfaced" in js
    # The above-the-fold skip is the actual fix. Without it every card is
    # hidden on load again, which is the bug this test exists for.
    assert "getBoundingClientRect().top < fold" in js, (
        "the above-the-fold skip is gone; content already on screen would be hidden"
    )


def test_the_landing_page_self_hosts_its_faces() -> None:
    """The landing page uses Archivo and IBM Plex Mono, which the rest of the
    app does not. They are served from this origin, never from Google.

    Asserted because the obvious way to add a face is a Google Fonts link, and
    the obvious way to make that work is to widen the CSP again. Both origins
    were removed deliberately (docs/17 §2); this keeps the landing page from
    quietly putting them back.
    """
    landing = pathlib.Path("app/web/templates/landing.html").read_text(encoding="utf-8")
    for host in ("fonts.googleapis.com", "fonts.gstatic.com"):
        assert host not in landing, f"landing.html reaches {host}"
    assert "/static/landing-fonts.css" in landing

    faces = pathlib.Path("app/web/static/landing-fonts.css").read_text(encoding="utf-8")
    assert "https://" not in faces, "a @font-face still points off-origin"
    for family in ("Archivo", "IBM Plex Mono"):
        assert family in faces
    font_dir = pathlib.Path("app/web/static/fonts")
    assert list(font_dir.glob("*.woff2")), "no self-hosted woff2 files committed"


def test_the_landing_page_ships_its_engine_and_plates() -> None:
    """landing.html is generated from scrollcraft/builds/fishlog and references
    files under /static/landing. A missing one is a page that half-renders, and
    the browser says nothing useful about it."""
    landing = pathlib.Path("app/web/templates/landing.html").read_text(encoding="utf-8")
    referenced = set(re.findall(r'/static/landing/([A-Za-z0-9_.-]+)', landing))
    assert referenced, "landing.html references nothing under /static/landing"
    present = {p.name for p in pathlib.Path("app/web/static/landing").iterdir()}
    missing = referenced - present
    assert not missing, f"landing.html references files that are not committed: {missing}"
