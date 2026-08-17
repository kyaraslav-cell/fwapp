# 10 — Session handover

Written at the end of the first build session, for whoever (or whichever
model) picks this up cold. Read `CLAUDE.md` first, then this.

---

## 1. What exists right now

A working FastAPI + SQLite app, ~3 000 lines of Python, 32 tests, `make check`
green (ruff, `mypy --strict` on `app/core` `app/rules` `app/features`, pytest).

Branch: `claude/repository-edit-push-ggr229` on `kyaraslav-cell/fwapp`.

| Area | State |
|---|---|
| Weather ingest (Open-Meteo, hourly, APScheduler) | works |
| Immutable prediction writer, `inputs_hash`, ruleset versioning | works |
| Restricted-AST expression evaluator (no `eval`) | works |
| Real OSM lake outline via Overpass, cached, circle fallback | works |
| 5 m grid clipped to the outline, ~3 564 cells | works |
| Heat overlay (canvas upscale → smooth field), red→green | works |
| Provisional zone score, v0.3, YAML-only | works |
| Session notebook: spot → method → rods → catches → end | works |
| 25-species DB, PL/EN/scientific search | works |
| Catch weight/length sliders, bait, photo, edit, delete | works |
| RU / PL / EN with on-page switcher | works |
| Fish pin: held drag, dive, splash | works |

**Run it:**
```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
rm -f fishlog.db*        # after any schema change
make check && make dev
```

---

## 2. Standing rules from the owner (this session)

These came from the owner directly and are not negotiable without asking.

1. **Stack stays server-rendered.** Jinja2 + HTMX, no build step, no React.
   The owner considered React and chose against it. ADR 0001 holds.
2. **Never show a raw fishing score.** Day quality is a colour band only
   (red / orange / yellow / green), never "7.4/10".
3. **Green = good, red = bad.** Traffic-light semantics everywhere.
4. **One lake only** — Jezioro Pomocnia. Multi-lake UI exists, the add-a-lake
   pipeline does not.
5. **Flow order is fixed:** home (places) → map → pick a spot → method +
   rod count → catch logging. Not a one-tap start.
6. **Three languages, switcher visible on the page.**
7. **Times display in Europe/Warsaw.** Storage stays UTC.
8. **Design is pastel light blue and white, minimal, uncluttered.**
   "Like an instrument, not an app."
9. **The owner will supply the real formulas later.** Until then a provisional
   AI-authored one is explicitly permitted — see §4.
10. **Conditions and map must stay reachable during an active session.**

---

## 3. Verification rules learned the hard way

Both of these cost several rounds of shipping something broken while claiming
it was fixed. They are the most important lines in this document.

- **You cannot verify motion from a screenshot, or by reading your own
  keyframes.** The fish pin dive was "improved" three times while diving
  **tail first** the whole time (the silhouette faces left, and positive CSS
  rotation swings the left side *up*). Use
  `tools/animation_filmstrip.py`, which pins an animation to exact progress
  percentages and tiles the frames.
- **You cannot verify visual design from your own diff.** The fish icons were
  declared "redrawn per species" twice and still read as one recoloured shape.
  Render the sheet, and compare old and new **side by side** before claiming
  a change landed.

Generalisation: for anything visual or temporal, produce an artefact and look
at it. A passing test suite says nothing about whether a fish is upside down.

---

## 4. The formula situation — read before touching scoring

`CLAUDE.md` law 1 forbids fishing knowledge in code, and forbids guessing at
`FORMULA_PRESSURE_DEPTH` / `FORMULA_WIND_ZONE`.

The owner **explicitly asked** for a provisional zone formula anyway. The
compromise, recorded in `docs/adr/0002-provisional-zone-score.md`:

- it lives entirely in `config/rules.v0.3.yaml`, never in code;
- it is stamped `provenance: ai_authored_provisional`, `status: hypothesis`;
- it carries `supersede_with: FORMULA_WIND_ZONE`, so the owner's real formula
  **replaces** it rather than blending with it;
- both owner slots remain **unfilled**;
- the UI states on the page that the overlay is provisional and unvalidated.

Current terms are pure geometry: `fetch_norm`, `shore_prox`, `shelter`, and
`lee_shore` (= `fetch_norm × shore_prox`, the windward-bank term that finally
made the map differentiate). Display uses **percentile ranking**, which is a
*display transform only* — colour means "better than other spots on this lake
today", never "good fishing". **Calibration must read raw scores.**

Weakest point: the thermal phase is chosen from the **calendar month**, which
contradicts ADR 0001 §5. It is labelled a stand-in in the YAML, carries
`is_measured=False` in code, prints its own caveat in the UI, and a test
asserts it never claims to be measured. **Delete it when the water-temperature
model lands.**

---

## 5. Known broken / incomplete

Ordered by how much it matters.

1. **Fish icons — root cause fixed, drawing half done.** There were two
   separate faults, which is why two redraws changed nothing:
   - *Nothing rendered them.* `shape` was added to `Species` after the table
     was seeded, and the seed refused to backfill, so every species resolved to
     `fish_icon(None)` → `#fish-roach`. The owner was looking at six roach the
     whole time. Fixed in `app/notebook/species.py`; pinned by
     `tests/test_species_seed.py`.
   - *The drawings really were one asset.* A closed oval body with fins stuck
     on, differing only in colour. The six quick-log species are now single
     continuous outlines — snout, dorsal, wrist, forked tail, anal and pelvic
     all cut into the silhouette, concave trailing edges, no ovals and no
     triangles. **The other eight (tench, pike, perch, zander, catfish, eel,
     trout, small) are still the old flat style** and need the same treatment.

   The standing rule is now in `CLAUDE.md` under "Species icons: no shared
   assets" — read it before touching them. Render with
   `tools/icon_sheet.py --compare` and show the owner, never a description.
2. **Terrain and tree-line wind shelter is missing** (backlog §3). Every score
   term is open-water geometry, so a bank with a 10 m tree line to windward is
   scored as exposed as a bare one. This systematically over-rates sheltered
   corners in summer. Needs a DEM or OSM `natural=wood` — **write an ADR
   first**.
3. **Water-temperature model not built.** Blocks the real thermal phase, the
   depth band and the oxygen proxy — which `docs/02-DOMAIN.md` argues is
   probably the dominant summer driver.
4. **PL / RU wording unchecked by a native angler.** "Fetch", "margin",
   "blank session", "CPUE" translate badly. `name_ru` is missing from
   `config/species.yaml`, so Russian shows English fish names.
5. **No real migrations.** `app/core/migrate.py` only adds missing nullable
   columns. Fine for dev, not for a season of real data. Numbered forward-only
   SQL is required by `docs/03-DATA-MODEL.md` before that point.
6. **Zones are demo wedges.** The owner has not mapped Pomocnia for real, so
   `bank_aspect_deg` and `tree_line_height_m` are unpopulated.
7. **Calibration loop unbuilt.** Phase 5 in the roadmap. Nothing yet measures
   whether any of this beats guessing.

---

## 6. Things never verified from the build sandbox

The sandbox blocks outbound HTTP to everything except a small allowlist, so
these have **never actually run**:

- live Open-Meteo ingest (fails closed into `ingest_gap`, which is correct);
- the Overpass outline fetch — the real Pomocnia polygon has never been seen,
  and `outline_source` on the lake page will say whether you got `osm` or
  `circle_fallback`;
- Esri satellite tiles and Google Fonts.

**First thing to check on a real machine:** does the map show the real
shoreline, and does "Right now" match a thermometer outside.

---

## 7. Where things live

```
CLAUDE.md                     the five laws
docs/01..08                   original spec, unchanged
docs/09-BACKLOG.md            outstanding owner requests
docs/10-SESSION-HANDOVER.md   this file
docs/adr/0001                 foundational decisions
docs/adr/0002                 provisional zone score + its provenance
config/rules.v0.3.yaml        active ruleset (day score + zone score)
config/species.yaml           25 species, sizes, icon shape, colour
config/i18n/{en,pl,ru}.yaml   translations
config/lakes/pomocnia.yaml    lake constants
app/geo/                      outline, grid, fetch ray-cast, service cache
app/rules/                    expressions, evaluator, zone_score, loader
app/features/                 pressure, solar, wind, season
tools/animation_filmstrip.py  pin a CSS animation to exact progress %, tile it
tools/splash_filmstrip.py     drive the real JS splash and photograph it
tools/icon_sheet.py           render icons; --compare puts git's set beside it
tools/build_static.py         render the read-only site for GitHub Pages
.github/workflows/pages.yml   twice-daily ingest + publish
docs/11-DEPLOY-PAGES.md       what Pages can and cannot host, and the setup
```

---

## 8. Suggested next session

1. Fix the icons properly — vendor PhyloPic, or commission real art. Compare
   side by side with the old set before declaring it done.
2. ADR + implementation for terrain/tree shelter.
3. `name_ru`, and a native pass over PL/RU.
4. Numbered migrations before the first real logged season.
5. Then Phase 5: the calibration loop, which is the entire point of the
   project.
