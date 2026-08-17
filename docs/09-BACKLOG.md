# 09 — Backlog

Requested by the project owner, not yet built. Written down so work can resume
without re-deriving the brief. Ordered roughly by the owner's emphasis.

Status key: **TODO** · **PARTIAL** · **DONE** (done items are dropped once
verified in the app).

---

## 1. Multi-language UI — RU / PL / EN · DONE (needs a native check)

- Three languages: **Russian, Polish, English**. Translate everything the
  angler actually reads: nav, buttons, labels, table headers, weather terms,
  the provenance note, species names, empty states, validation messages.
- **Language switch control visible on the page**, not buried in settings.
- Species already carry `name_en` and `name_pl` in `config/species.yaml`;
  a `name_ru` column needs adding there and to the `species` table.
- Approach: a small dict-based catalogue (`config/i18n/{en,pl,ru}.yaml`) and a
  Jinja global `t("key")`, with the choice stored in a cookie. No new
  dependency — gettext/babel would be heavier than this earns.
- **Still open:** Polish and Russian angling vocabulary needs a native check.
  Translations were written without a native angler reviewing them, and terms
  like "fetch", "margin", "blank session" and "CPUE" are exactly the kind that
  read wrong when translated literally. Species names come from
  `config/species.yaml` (`name_pl`); **`name_ru` is still missing**, so Russian
  currently falls back to English species names.

## 2. Drop the manual phase buttons · DONE

- Remove the `spring warming / summer stagnation / autumn cooling` button row
  from the lake page.
- Derive **one** season/phase automatically from the current period and show
  it as plain text, not a control.
- **Constraint that still stands** (`CLAUDE.md`, ADR 0001 §5): thermal phase
  is a state derived from *modelled water temperature and its trend*, never
  from the calendar. Deriving it from "current period" is a temporary stand-in
  and must be labelled as such in the UI until the water-temperature model
  (`docs/02-DOMAIN.md` Layer 2) exists. Do not quietly turn a date lookup into
  a claimed measurement.

## 3. Terrain and shelter in the heat map · TODO

- Wind shelter from **trees, tree lines, banks and elevation**: a bank with a
  10 m tree line to windward is sheltered no matter what the open-water fetch
  says.
- Needs an elevation/landcover source (SRTM or Copernicus DEM for terrain,
  OSM `natural=wood` / `landuse=forest` polygons for tree cover). New data
  source ⇒ **write an ADR before coding it** (`docs/05-ARCHITECTURE.md`).
- Feeds a shelter multiplier applied to effective fetch per cell, and finally
  makes `bank_aspect_deg` / `tree_line_height_m` on `zone` earn their place.

## 4. Make the map differentiate visibly · DONE (first pass)

Problem the owner reported: **almost the whole lake renders one colour**, so
the overlay says nothing.

- Add more terms to the provisional score so cells actually separate:
  distance to weed edge, shore proximity bands, depth proxy, shelter (§3),
  sun/shade from tree line, and a wind-shadow term.
- Consider **percentile (rank) normalisation** for display instead of min-max:
  guarantees the full colour ramp is used even when raw scores cluster. This
  is a *display* transform — it must not be mistaken for the score itself, and
  must be documented as such.
- Owner's standing instruction: build a provisional formula now, they will
  supply the real one later. Keep it in YAML, keep `provenance:
  ai_authored_provisional`, keep `FORMULA_WIND_ZONE` unfilled.
  See `docs/adr/0002-provisional-zone-score.md`.

## 5. Fish pin interaction · DONE

- **While dragging:** the pin must stay visibly held under the cursor/finger
  (currently the browser's default drag ghost, which looks wrong on mobile).
  Use pointer events + a follower element rather than HTML5 drag-and-drop.
- **On release:** play a **dive animation, then the splash** — fish enters the
  water, ripples expand. Current build splashes but does not dive.
- Keep the idle bob animation.

## 6. Catch logging UI · DONE (first pass)

- **Species icons**: recognisable per-species silhouettes on the quick-log
  buttons, not text-only chips. Inline SVG (no icon-font dependency).
- **Sliders for weight and length**, pre-centred on that species' typical
  size, so the common case is one drag and no typing. Needs a
  `typical_weight_g` / `typical_length_cm` range per species in
  `config/species.yaml`.
- Rework the catch buttons generally — the current chips and the details
  `<details>` block are slower to use than they should be.
- Governing constraint (`docs/07-UI-SPEC.md`): **~2 seconds per fish**, one
  thumb, wet hands, bright sun. Every added control must pay for itself
  against that.

## 7. General · TODO

- Keep the design fast and uncluttered; the interface should read like an
  instrument, not an app.

---

## Recently closed

- End session button rendered nearly invisible: `--danger` was referenced but
  never defined in the pastel palette, so the background resolved to nothing
  and only the hover rule (a literal colour) showed. Fixed — constant pastel
  red.
- Heat map drawn over the Wkra river instead of the lake: outline selection
  took the largest nearby water polygon. Now containment-first.
- Colour ramp inverted so green = best, red = poor.
- Duplicated Places/History nav on desktop.


---

## Added since

## 8. Terrain shelter is still the big missing input · TODO

Item 3 above remains untouched and is now the largest single gap in the score.
Every term in `zone_score` is open-water geometry; a bank with a tall tree line
to windward is scored as exposed as one with none. Until that lands, the
overlay systematically over-rates sheltered corners in summer.

## 10. Live zone scores on the published site · SPIKED, undecided

The Pages build answers only twelve wind directions because it has to pre-render
them. `/spike/pyodide/` tests whether the browser could run `app/geo/grid.py` and
`app/rules/zone_score.py` itself instead. Booting CPython in the browser and
scoring all 3 564 cells to an exact match with the server is done and measured;
loading the shapely wheel could not be tested from the build sandbox and is
verified by opening the published page.

**Next:** open it, screenshot the verdict, then decide between the three shapes
in `docs/12-SPIKE-PYODIDE.md` §4. Adopting Pyodide needs an ADR first — a 6 MB
interpreter fetched at page load is a dependency whatever `requirements.txt`
says.

## 9. Session UI while fishing · DONE

`/lake/{slug}` no longer redirects away during an active session, and the
session screen links back to conditions and history.
