"""Every `getElementById` in a template must find something in that template.

This exists because of a real, shipped bug. The "Right now · HH:MM" line was
removed from the lake page at the owner's request; the page's JavaScript still
did `document.getElementById('now-label').textContent`, which threw a
TypeError at parse-of-first-use - **before** the calendar toggle's click
handler was bound. So deleting one line of markup silently killed an unrelated
control further down the page, and the page still rendered perfectly: every
server-side test passed, the HTML looked right, and a screenshot showed
nothing wrong. Only clicking the icon revealed it.

A browser test would catch it too, but this is static, runs in milliseconds,
and needs no Chromium. It cannot check that an element is *usable*, only that
it exists - which is exactly the class of mistake that caused the outage.

Guarded elements are those looked up unconditionally and then dereferenced.
An id that genuinely may be absent is written `{% if %}`-guarded in the
template and null-checked in the script; those are listed in OPTIONAL below,
so adding one is a deliberate act rather than an oversight.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "web" / "templates"

# Ids the script deliberately tolerates being absent, each null-checked at
# every use. `now-card` and its children only exist when there is a reading to
# show; the map fallback only exists when Leaflet did not load.
OPTIONAL: dict[str, set[str]] = {
    "lake_detail.html": {
        "now-card",
        "now-temp",
        "now-detail",
        "day-strip",
        "day-strip-note",
        "calendar-toggle",
        "zone-list-fallback",
        "map-day-badge",
    },
}

LOOKUP = re.compile(r"getElementById\(\s*['\"]([A-Za-z0-9_-]+)['\"]\s*\)")
DEFINED = re.compile(r"""\bid\s*=\s*['"]([A-Za-z0-9_-]+)['"]""")


def _templates() -> list[Path]:
    return sorted(TEMPLATES.glob("*.html"))


@pytest.mark.parametrize("template", _templates(), ids=lambda p: p.name)
def test_every_looked_up_element_exists(template: Path) -> None:
    source = template.read_text(encoding="utf-8")
    looked_up = set(LOOKUP.findall(source))
    if not looked_up:
        pytest.skip("no element lookups in this template")

    defined = set(DEFINED.findall(source))
    # Ids written by Jinja, e.g. id="chip-{{ loop.index }}", cannot be matched
    # literally; anything interpolated is out of scope for a static check.
    dynamic = bool(re.search(r"""id\s*=\s*['"][^'"]*\{\{""", source))

    missing = looked_up - defined - OPTIONAL.get(template.name, set())
    if missing and dynamic:
        pytest.skip(f"template builds ids dynamically; cannot check {sorted(missing)}")

    assert not missing, (
        f"{template.name} looks up {sorted(missing)} but never defines them. "
        "A lookup that returns null throws on first dereference and kills every "
        "handler bound after it - including ones on unrelated controls."
    )


def test_the_guard_would_have_caught_the_now_label_bug() -> None:
    """The regression itself, so the guard cannot be quietly weakened.

    `now-label` was removed from the markup and left in the script. If it ever
    reappears in a lookup without matching markup, the calendar icon stops
    working again and nothing else looks wrong.
    """
    source = (TEMPLATES / "lake_detail.html").read_text(encoding="utf-8")
    # The *lookup*, not the string: a comment explaining why the element is
    # gone is exactly the thing worth keeping, and must not trip this.
    assert "now-label" not in set(LOOKUP.findall(source)), (
        "now-label is gone from the markup; looking it up throws on first "
        "dereference, before the calendar toggle is bound"
    )
    assert 'id="now-label"' not in source
