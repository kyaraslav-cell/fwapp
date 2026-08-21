#!/usr/bin/env python
"""Does this machine's setup actually work? Run it where the network is.

    make preflight              # everything
    make preflight ARGS=gemini  # one section

Everything this app talks to is unreachable from the sandbox it was written in
(`docs/10 §6`), so every client in it is "believed, never observed". This is the
command that converts that, one section at a time, on a machine that *can*
reach them. It is not a test - it is a diagnosis, and it is meant to be read.

Three rules it keeps:

- **It never prints a secret.** A key is shown as its first four characters and
  its length. That is enough to tell "the wrong key" from "no key" and not
  enough to be worth anything in a screenshot or a pasted log.
- **It names the layer that failed.** "Gemini returned 429 (quota)" and
  "DNS did not resolve" are different problems with different fixes, and
  "something went wrong" is neither.
- **It changes nothing.** No lake is created, no row is written, nothing is
  queued. Run it as often as you like.
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.core.env import ENV_FILE, load_env_file  # noqa: E402

OK = "  ok   "
BAD = " FAIL  "
SKIP = " skip  "
INFO = "       "

# A water that certainly exists, for the sections that need a real query.
PROBE_NAME = "Zalew Zegrzynski"
PROBE_LAT, PROBE_LON = 52.4416, 21.0561


def line(mark: str, text: str) -> None:
    print(f"[{mark}] {text}")


def masked(value: str) -> str:
    """First four characters and a length. Never the key."""
    if not value:
        return "(not set)"
    return f"{value[:4]}… ({len(value)} chars)"


# --------------------------------------------------------------------------


def section_env() -> bool:
    print("\n== environment ==")
    applied = load_env_file()
    if ENV_FILE.exists():
        line(OK, f".env found at {ENV_FILE}")
        line(INFO, f"applied: {', '.join(applied) if applied else 'nothing new'}")
    else:
        line(INFO, f"no .env at {ENV_FILE} (fine if you export variables yourself)")

    wanted = {
        "FISHLOG_GEMINI_API_KEY": "local-knowledge pass",
        "FISHLOG_GEMINI_MODEL": "model override (optional)",
        "FISHLOG_GOOGLE_CLIENT_ID": "sign in with Google",
        "FISHLOG_GOOGLE_CLIENT_SECRET": "sign in with Google",
        "FISHLOG_GOOGLE_REDIRECT_URI": "sign in with Google",
        "FISHLOG_TRUST_PROXY": "only behind a reverse proxy",
        "FISHLOG_FRAME_ANCESTORS": "dev container preview pane only",
    }
    for name, purpose in wanted.items():
        value = os.environ.get(name, "")
        shown = (
            value
            if name.endswith(("_URI", "_MODEL", "_PROXY", "_ANCESTORS"))
            else masked(value)
        )
        line(OK if value else INFO, f"{name} = {shown or '(not set)'}  — {purpose}")

    if os.environ.get("FISHLOG_FRAME_ANCESTORS", "").strip():
        line(
            INFO,
            "FRAME_ANCESTORS is set: this app can be framed, and "
            "X-Frame-Options is dropped while it is. Correct for an editor "
            "preview pane; never set it on a deployment.",
        )

    if os.environ.get("FISHLOG_TRUST_PROXY") == "1":
        line(
            INFO,
            "TRUST_PROXY is on: correct ONLY if something in front of this app "
            "sets X-Forwarded-For. Wrong either way breaks rate limiting.",
        )
    return True


def section_deps() -> bool:
    """Is this virtualenv actually what `requirements.txt` asks for?

    Added after `uvicorn` died with `ModuleNotFoundError: No module named
    'PIL'`. Pillow had been added to `requirements.txt` days earlier; the
    virtualenv predated it. A dependency does not install itself, and the
    symptom is a forty-line traceback from the import machinery that names the
    missing module and not the reason.

    A stale environment is the single most common way a working checkout
    refuses to run, and it is entirely diagnosable in advance - so it goes
    first, before any section that imports app code.
    """
    print("\n== dependencies ==")
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as installed_version

    requirements = pathlib.Path(__file__).resolve().parent.parent / "requirements.txt"
    missing: list[str] = []
    wrong: list[str] = []

    for raw in requirements.read_text(encoding="utf-8").splitlines():
        # Not `line` - that is the reporting helper above, and shadowing it
        # here turns every success message into a TypeError.
        entry = raw.split("#")[0].strip()
        if not entry or "==" not in entry:
            continue
        name, _, wanted = entry.partition("==")
        # `uvicorn[standard]` - the extras are not part of the package name.
        name = name.split("[")[0].strip()
        try:
            have = installed_version(name)
        except PackageNotFoundError:
            missing.append(f"{name}=={wanted}")
            continue
        if have != wanted.strip():
            wrong.append(f"{name}: have {have}, want {wanted.strip()}")

    if not missing and not wrong:
        line(OK, "every pinned dependency is installed at its pinned version")
        return True

    for item in missing:
        line(BAD, f"not installed: {item}")
    for item in wrong:
        line(BAD, f"wrong version: {item}")
    line(
        INFO,
        "fix with:  .venv/bin/pip install -r requirements-dev.txt   (or `make install`)",
    )
    return False


def _reach(name: str, call: object) -> bool:
    """Run one probe, and name the layer that refused rather than the exception."""
    started = time.monotonic()
    try:
        detail = call()  # type: ignore[operator]
    except httpx.ConnectError as exc:
        line(BAD, f"{name}: cannot connect — {exc}")
        return False
    except httpx.ConnectTimeout:
        line(BAD, f"{name}: connection timed out (firewall, or the service is down)")
        return False
    except httpx.ReadTimeout:
        line(BAD, f"{name}: connected, then no answer in time")
        return False
    except httpx.ProxyError as exc:
        line(BAD, f"{name}: blocked by a proxy — {exc}")
        return False
    except Exception as exc:  # noqa: BLE001 - the point is to report, not to survive
        line(BAD, f"{name}: {type(exc).__name__}: {exc}")
        return False
    elapsed = time.monotonic() - started
    line(OK, f"{name}: {detail}  [{elapsed:.1f}s]")
    return True


def section_nominatim() -> bool:
    print("\n== nominatim (search by name) ==")
    from app.discover import nominatim

    def probe() -> str:
        found = nominatim.search(PROBE_NAME)
        if not found:
            raise RuntimeError(f"answered, but found nothing for {PROBE_NAME!r}")
        top = found[0]
        # The bug that made every result "not a water" showed up exactly here:
        # a blank kind means the class/category field was not read.
        if not top.kind:
            raise RuntimeError(
                "results carry no OSM tag — the response field names have "
                "changed again (see docs/13 §11)"
            )
        water = sum(1 for c in found if c.is_water)
        if not water:
            raise RuntimeError(
                f"{len(found)} results, none recognised as water. "
                f"Top result is {top.kind!r} — if that looks like a lake, the "
                "water-type list in app/discover/nominatim.py needs it."
            )
        return f"{len(found)} results, {water} water, top = {top.name!r} ({top.kind})"

    return _reach("search", probe)


def section_overpass() -> bool:
    print("\n== overpass (shoreline) ==")
    from app.discover import nominatim
    from app.geo.outline import fetch_osm_outline_strict

    def probe() -> str:
        found = [c for c in nominatim.search(PROBE_NAME) if c.is_water]
        osm_type = found[0].osm_type if found else None
        osm_id = found[0].osm_id if found else None
        area = found[0].area_ha if found else None
        outline = fetch_osm_outline_strict(
            PROBE_LAT, PROBE_LON, osm_type=osm_type, osm_id=osm_id, area_ha=area
        )
        if outline is None:
            raise RuntimeError(
                "answered, but no water polygon. For a large water this used "
                "to mean a relation was being skipped — docs/13 §11."
            )
        ring = outline["coordinates"][0]
        # The area is the part worth reading: a shoreline of the right shape
        # and a tenth of the right size looks identical in a point count, and
        # picking a side basin instead of the main body is a real failure mode.
        from app.geo.grid import polygon_area_ha

        area_ha = polygon_area_ha(outline)
        expected = f", geocoder said ~{area:.0f} ha" if area else ""
        return (
            f"polygon of {len(ring)} points, {area_ha:.0f} ha"
            f"{expected}, via {osm_type or 'proximity'}"
        )

    return _reach("outline", probe)


def section_openmeteo() -> bool:
    print("\n== open-meteo (weather) ==")
    from app.ingest.open_meteo import fetch_forecast

    def probe() -> str:
        rows = fetch_forecast(PROBE_LAT, PROBE_LON, past_days=1, forecast_days=1)
        if not rows:
            raise RuntimeError("answered with no hours")
        pressures = [r.get("pressure_msl") for r in rows if r.get("pressure_msl")]
        if not pressures:
            raise RuntimeError(
                "hours came back but every pressure is empty — a variable name "
                "in HOURLY_VARS is no longer one Open-Meteo knows"
            )
        return f"{len(rows)} hours, pressure {min(pressures):.0f}–{max(pressures):.0f} hPa"

    return _reach("forecast", probe)


def section_gemini() -> bool:
    print("\n== gemini (local knowledge) ==")
    from app.intel import gemini

    config = gemini.load_config()
    if config is None:
        line(SKIP, "no FISHLOG_GEMINI_API_KEY — the intel job will report 'skipped'")
        return True
    line(INFO, f"model = {config.model}, key = {masked(config.api_key)}")

    def probe() -> str:
        collection = gemini.collect(
            config, name=PROBE_NAME, lat=PROBE_LAT, lon=PROBE_LON
        )
        dead = sum(1 for ok in collection.source_ok.values() if not ok)
        parts = [f"{len(collection.facts)} facts kept"]
        if collection.rejected:
            parts.append(f"{len(collection.rejected)} dropped")
        if dead:
            parts.append(f"{dead} source(s) 404")
        return ", ".join(parts)

    reached = _reach("collect", probe)
    if reached:
        # Print what it actually said. The plumbing working and the answer
        # being worth having are two different questions, and only a human
        # looking at the facts can settle the second.
        collection = gemini.collect(
            config, name=PROBE_NAME, lat=PROBE_LAT, lon=PROBE_LON
        )
        for fact in collection.facts[:8]:
            line(INFO, f"  {fact.topic}/{fact.key}: {fact.value[:80]}")
            line(INFO, f"      ← {fact.source_url}")
        for reason in collection.rejected[:5]:
            line(INFO, f"  dropped: {reason}")
        if not collection.facts:
            line(
                INFO,
                "no facts. For a small water that is the correct answer; for "
                "this one it means the model found nothing it could cite.",
            )
    return reached


SECTIONS = {
    "env": section_env,
    # Before anything that imports app code: a stale virtualenv makes every
    # later section fail with a traceback that names the wrong culprit.
    "deps": section_deps,
    "nominatim": section_nominatim,
    "overpass": section_overpass,
    "openmeteo": section_openmeteo,
    "gemini": section_gemini,
}


def main(argv: list[str]) -> int:
    wanted = [a for a in argv[1:] if not a.startswith("-")] or list(SECTIONS)
    unknown = [name for name in wanted if name not in SECTIONS]
    if unknown:
        print(f"unknown section(s): {', '.join(unknown)}")
        print(f"available: {', '.join(SECTIONS)}")
        return 2

    # env then deps first, always: every other section depends on what env
    # loaded, and on the packages deps checks for.
    ordered = ["env", "deps"] + [n for n in wanted if n not in ("env", "deps")]
    results = {name: SECTIONS[name]() for name in dict.fromkeys(ordered)}

    print("\n== summary ==")
    for name, passed in results.items():
        line(OK if passed else BAD, name)
    failed = [n for n, ok in results.items() if not ok]
    if failed:
        print(f"\n{len(failed)} section(s) failed: {', '.join(failed)}")
        return 1
    print("\nall clear.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
