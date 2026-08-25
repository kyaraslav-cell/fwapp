"""Drive the real app through its core angler flow in a real browser, and
report what a diff and a green test suite cannot: a control with nothing
wired to it, a JS/console error, a failed request, a page that no longer
matches its last-approved screenshot, an accessibility violation.

This generalises what CLAUDE.md already argues tool-by-tool -
animation_filmstrip.py (motion), icon_sheet.py and switch_sheet.py (a
control's real pixels), zone_map.py (the score's real colours). Each of
those renders one artefact and puts it beside the old one. None of them
drive an actual click through the actual JS in an actual browser - which is
exactly the kind of bug this misses: the §19c hi-res overlay bug (2026-08-25,
docs/09-BACKLOG.md §19c) lived entirely in what the browser did with a
fetch response, and no Python-side render or test could have seen it.

Deliberately NOT an LLM-in-the-loop tool. Every check here is deterministic
(Playwright + axe-core-python + Pillow, all free and self-hosted - no
account, no API key, no third-party service the app's screenshots would
have to leave your network for). A run costs compute, not credits. Judging
*whether a finding is actually a bug* is a separate, later step for a human
or an LLM reading the report - see the site-audit skill.

Usage:
    # Full flow (register, session, catch) - only against a throwaway DB.
    python tools/site_audit.py --base-url http://127.0.0.1:8090
    python tools/site_audit.py --base-url http://127.0.0.1:8090 --update-baselines

    # Read-only - safe against a real deployment's real database.
    python tools/site_audit.py --base-url http://127.0.0.1:8000 --public-only

Needs the app already running and reachable at --base-url, and
`.venv/bin/playwright install chromium` done once on this machine (not
needed in the cloud sandbox - the browser is pre-staged there).

--public-only skips registration and the session/catch flow, which write a
real user/session/catch row - use it whenever --base-url points at a real
deployment rather than a scratch database (tools/nightly_audit.sh does).
"""

from __future__ import annotations

import argparse
import pathlib
import secrets
import sys
from dataclasses import dataclass, field
from typing import Any

from axe_core_python.sync_playwright import Axe
from playwright.sync_api import Locator, Page, sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE_DIR = ROOT / "tools" / "baselines"
DIFF_DIR = pathlib.Path("/tmp/site_audit_diffs")

# Findings below this axe-core severity are almost always colour-contrast
# nits on a palette CLAUDE.md already fixes (pastel light blue and white) -
# real, but not what this tool exists to surface. Read the full JSON if you
# want everything.
A11Y_MIN_IMPACT = {"serious", "critical"}

INIT_SCRIPT = """
(() => {
  const orig = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function (...args) {
    if (this instanceof Element) this.__wired = true;
    return orig.apply(this, args);
  };
})();
"""


@dataclass
class Report:
    dead_controls: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)
    visual_diffs: list[str] = field(default_factory=list)
    a11y_violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (
            self.dead_controls
            or self.console_errors
            or self.failed_requests
            or self.visual_diffs
            or self.a11y_violations
        )


def attach_listeners(page: Page, report: Report, label: str) -> None:
    page.on(
        "console",
        lambda m: report.console_errors.append(f"[{label}] {m.text}")
        if m.type == "error"
        else None,
    )
    page.on("pageerror", lambda e: report.console_errors.append(f"[{label}] uncaught: {e}"))
    page.on(
        "response",
        lambda r: report.failed_requests.append(f"[{label}] {r.status} {r.url}")
        if r.status >= 400
        else None,
    )


def scan_dead_controls(page: Page, report: Report, label: str) -> None:
    """Every button/link on the page that has nothing observably wired to it.

    "Wired" means any of: a real href, an inline onclick, an htmx attribute,
    a JS listener attached via addEventListener (tagged by INIT_SCRIPT before
    the page ever loaded), or being a submit/reset button inside a <form>
    (the form's own action carries it). Catches exactly the class of bug the
    owner named - a button that looks real and does nothing - without
    needing to actually click every control and guess what "worked" means.
    """
    dead: list[dict[str, str]] = page.evaluate(
        """
        () => {
          const out = [];
          document.querySelectorAll('a, button, [role="button"]').forEach(el => {
            const tag = el.tagName.toLowerCase();
            const type = (el.getAttribute('type') || '').toLowerCase();
            const href = el.getAttribute('href');
            const wired = (
              el.__wired ||
              el.hasAttribute('onclick') ||
              ['hx-get','hx-post','hx-put','hx-delete','hx-patch']
                .some(a => el.hasAttribute(a)) ||
              (href && href !== '#' && href.trim() !== '') ||
              (tag === 'button' && (type === 'submit' || type === 'reset' || type === '') &&
                el.closest('form'))
            );
            if (!wired) {
              const text = (el.textContent || '').trim().slice(0, 40);
              out.push({tag, text, id: el.id || '', cls: el.className || ''});
            }
          });
          return out;
        }
        """
    )
    for d in dead:
        report.dead_controls.append(
            f"[{label}] <{d['tag']}> \"{d['text']}\" (id={d['id'] or '-'}) has no href, "
            f"handler, htmx attribute, or enclosing form"
        )


def screenshot_and_diff(
    page: Page, name: str, report: Report, update_baselines: bool, locator: str | None = None
) -> None:
    from PIL import Image, ImageChops

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    if locator is not None:
        loc = page.locator(locator)
        if not loc.is_visible():
            report.notes.append(
                f"[{name}] '{locator}' is not visible - skipped screenshot "
                f"(likely a fallback state, e.g. the map's own no-JS/no-CDN path)"
            )
            return
        target: Locator | Page = loc
    else:
        target = page
    live_path = pathlib.Path(f"/tmp/site_audit_live_{name}.png")
    target.screenshot(path=str(live_path), timeout=5000)
    baseline_path = BASELINE_DIR / f"{name}.png"

    if update_baselines or not baseline_path.exists():
        baseline_path.write_bytes(live_path.read_bytes())
        report.notes.append(f"[{name}] baseline written ({baseline_path.name})")
        return

    live = Image.open(live_path).convert("RGB")
    base = Image.open(baseline_path).convert("RGB")
    if live.size != base.size:
        report.visual_diffs.append(
            f"[{name}] size changed: baseline {base.size} vs. live {live.size}"
        )
        return

    diff = ImageChops.difference(live, base)
    bbox = diff.getbbox()
    if bbox is None:
        return
    # Grayscale histogram, not a per-pixel Python loop: 256 buckets either way,
    # however large the image, and cleanly typed (list[int]) unlike iterating
    # raw pixel tuples out of PIL's C-backed getdata().
    gray_histogram = diff.crop(bbox).convert("L").histogram()
    changed = sum(gray_histogram[31:])  # ignore antialiasing-level noise
    total = live.size[0] * live.size[1]
    pct = 100.0 * changed / total
    if pct < 0.5:
        return  # sub-pixel/antialiasing noise, not a real change
    DIFF_DIR.mkdir(parents=True, exist_ok=True)
    diff_path = DIFF_DIR / f"{name}.png"
    diff.save(diff_path)
    report.visual_diffs.append(
        f"[{name}] {pct:.1f}% of pixels changed vs. baseline - diff saved to {diff_path}"
    )


def scan_a11y(page: Page, label: str, report: Report) -> None:
    results = Axe().run(page)
    for v in results.get("violations", []):
        if v.get("impact") not in A11Y_MIN_IMPACT:
            continue
        nodes = ", ".join(n.get("target", [""])[0] for n in v.get("nodes", [])[:3])
        report.a11y_violations.append(f"[{label}] {v['impact']}: {v['id']} — {nodes}")


def register_qa_angler(page: Page, base_url: str, report: Report) -> None:
    token = secrets.token_hex(4)
    email = f"qa-audit-{token}@fishlog.invalid"
    # Deliberately unrelated to `email`: validate_password() rejects a
    # password containing the address's local part (app/auth/validation.py),
    # correctly - the first version of this script used the same token in
    # both and produced a false-positive 422 against its own test account.
    password = f"Zx9!{secrets.token_hex(6)}Qq"
    page.goto(f"{base_url}/auth/register", wait_until="domcontentloaded")
    attach_listeners(page, report, "register")
    page.fill("#email", email)
    page.fill("#display_name", f"QA Audit {token}")
    page.fill("#password", password)
    page.fill("#password_confirm", password)
    page.click("#register-form button[type=submit]")
    page.wait_for_load_state("domcontentloaded")
    if "/auth/register" in page.url:
        report.notes.append(
            "registration did not redirect away from /auth/register - check validation"
        )


def audit_public_pages(page: Page, base_url: str, lake_slug: str, report: Report,
                        update_baselines: bool) -> None:
    """Everything that reads only - safe to run against a real database.

    Home and the lake page are public by design (docs/adr/0004: "the lake,
    the weather and the map stay public"), and every check here - dead
    controls, console/network errors, accessibility, screenshot diffs -
    only ever navigates and looks. Nothing here writes a row.
    """
    page.goto(f"{base_url}/", wait_until="networkidle")
    attach_listeners(page, report, "home")
    scan_dead_controls(page, report, "home")
    scan_a11y(page, "home", report)
    screenshot_and_diff(page, "home", report, update_baselines)

    page.goto(f"{base_url}/lake/{lake_slug}", wait_until="networkidle")
    attach_listeners(page, report, "lake")
    page.wait_for_timeout(500)  # grid fetch + canvas paint
    scan_dead_controls(page, report, "lake")
    scan_a11y(page, "lake", report)
    # The heat overlay is coloured from live wind/pressure (app/web/templates/
    # lake_detail.html's renderHeat()) - it is *supposed* to look different
    # tomorrow. Diffing it against a fixed baseline would flag real weather
    # as a regression every single night, which is exactly the kind of noise
    # that gets an automated check ignored. Hidden for this screenshot only;
    # everything else in #map-wrap (shoreline, controls, legend) is static
    # and still worth catching a real regression in.
    page.evaluate(
        "document.querySelectorAll('.heat-overlay')"
        ".forEach(el => el.style.visibility = 'hidden')"
    )
    screenshot_and_diff(page, "lake", report, update_baselines, locator="#map-wrap")


def audit_authenticated_flow(page: Page, base_url: str, report: Report,
                              update_baselines: bool) -> None:
    """Register -> pick a spot -> start a session -> log a catch -> end it.

    Writes real rows: a user, a fishing session, a catch. Only ever call
    this against a throwaway database (tools/site_audit.py's own smoke-test
    instance, or a local `make dev` with a scratch DB) - never against a
    real deployment's real notebook. See CLAUDE.md law 3 and
    docs/09-BACKLOG.md §20: a nightly run against production must not
    fabricate a fake angler's fake catch into real CPUE statistics forever.
    """
    register_qa_angler(page, base_url, report)

    # Pick a spot: click the map centre, which for a real lake outline is
    # inside the polygon far more often than not.
    map_box = page.locator("#map").bounding_box()
    if map_box is None:
        report.notes.append(
            "[lake] #map has no layout box (not visible - a hidden ancestor, "
            "most likely #map-wrap's own try/catch fallback when Leaflet failed "
            "to load, e.g. its CDN being unreachable) - cannot click it"
        )
        return
    cx = map_box["x"] + map_box["width"] / 2
    cy = map_box["y"] + map_box["height"] / 2
    page.mouse.click(cx, cy)
    page.wait_for_timeout(300)
    popup_link = page.locator(".leaflet-popup a")
    if popup_link.count() == 0:
        report.notes.append(
            "[lake] clicking the map centre opened no popup - point may have "
            "landed outside the water polygon"
        )
        return
    popup_link.first.click()
    page.wait_for_load_state("domcontentloaded")
    if "/spot" in page.url:
        attach_listeners(page, report, "spot_start")
        scan_dead_controls(page, report, "spot_start")
        scan_a11y(page, "spot_start", report)
        screenshot_and_diff(page, "spot_start", report, update_baselines)
        page.click("button.btn-primary[type=submit]")
        page.wait_for_load_state("domcontentloaded")

    if "/session/active" not in page.url and page.locator(".fish-grid").count() == 0:
        report.notes.append(
            "[flow] never reached an active session - spot-start or catch-logging "
            "step did not complete; see notes above"
        )
        return

    attach_listeners(page, report, "session_active")
    scan_dead_controls(page, report, "session_active")
    scan_a11y(page, "session_active", report)
    screenshot_and_diff(page, "session_active", report, update_baselines)
    fish_btn = page.locator(".fish-btn").first
    if fish_btn.count() > 0:
        fish_btn.click()
        page.wait_for_load_state("domcontentloaded")
        if page.locator(".catch-card").count() == 0:
            report.notes.append("[session_active] logged a catch but no .catch-card appeared")
    page.goto(f"{base_url}/session/end", wait_until="domcontentloaded")
    end_btn = page.locator("button[type=submit]").first
    if end_btn.count() > 0:
        end_btn.click()
        page.wait_for_load_state("domcontentloaded")


def run(
    base_url: str, lake_slug: str, update_baselines: bool, public_only: bool
) -> Report:
    report = Report()
    with sync_playwright() as p:
        launch_kwargs: dict[str, Any] = {}
        chromium_path = pathlib.Path("/opt/pw-browsers/chromium")
        if chromium_path.exists():
            launch_kwargs["executable_path"] = str(chromium_path)
        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 420, "height": 860})
        page.add_init_script(INIT_SCRIPT)

        audit_public_pages(page, base_url, lake_slug, report, update_baselines)
        if not public_only:
            audit_authenticated_flow(page, base_url, report, update_baselines)

        browser.close()
    return report


def render_markdown(report: Report, base_url: str) -> str:
    lines = [f"# Site audit — {base_url}", ""]

    def section(title: str, items: list[str]) -> None:
        lines.append(f"## {title} ({len(items)})")
        if not items:
            lines.append("None.")
        else:
            lines.extend(f"- {i}" for i in items)
        lines.append("")

    section("Dead controls (no href/handler/htmx/form)", report.dead_controls)
    section("Console & page errors", report.console_errors)
    section("Failed requests (4xx/5xx)", report.failed_requests)
    section("Visual diffs vs. committed baseline", report.visual_diffs)
    section("Accessibility (serious/critical)", report.a11y_violations)
    section("Notes (flow could not proceed as expected)", report.notes)
    lines.append("**PASS**" if report.clean else "**FAIL**")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--lake", default="pomocnia")
    parser.add_argument("--update-baselines", action="store_true")
    parser.add_argument("--out", default="/tmp/site_audit_report.md")
    parser.add_argument(
        "--public-only",
        action="store_true",
        help=(
            "Skip registration and the session/catch-logging flow - only the "
            "read-only checks (dead controls, console/network errors, a11y, "
            "visual diffs) on the public home and lake pages. Use this against "
            "any real database: the full flow writes a real user, session and "
            "catch, which is fine against a throwaway DB and not fine against "
            "a real angler's real notebook (CLAUDE.md law 3)."
        ),
    )
    args = parser.parse_args()

    report = run(args.base_url, args.lake, args.update_baselines, args.public_only)
    markdown = render_markdown(report, args.base_url)
    pathlib.Path(args.out).write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"\nWritten to {args.out}")
    return 0 if report.clean or args.update_baselines else 1


if __name__ == "__main__":
    sys.exit(main())
