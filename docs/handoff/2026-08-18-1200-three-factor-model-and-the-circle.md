# Handoff — 2026-08-18, the three-factor model, and the lake that was a circle

## State

Branch `claude/pyodide-shapely-pages-11ioss`, merged to the default branch
`claude/repository-edit-push-ggr229` and deployed. `make check` green: 109 tests,
ruff, `mypy --strict`. Published site at
`https://kyaraslav-cell.github.io/fwapp/`.

## Decisions, and why

- **`config/rules.v0.4.yaml` is active.** Oxygen and modelled water temperature
  now enter the score. Roll back with `FISHLOG_RULESET=rules.v0.3.yaml`; law 2
  keeps every prediction stamped with the version that wrote it.
- **Thermal phase comes from modelled water temperature, not the calendar.**
  Closes the ADR 0001 §5 violation that this document listed for two sessions as
  the weakest thing in the ruleset.
- **The factors combine as a softened `min`, not a weighted sum.** The source
  insists all three hold at once; a sum lets a good barometer paper over lethal
  oxygen.
- **Pressure is excluded from the zone term.** It is identical across 9 ha, so
  including it shifts every cell equally and implies a spatial claim that does
  not exist.
- **The pressure norm is computed, never quoted.** The source video says every
  water has its own and then withholds the formula. It is the median of this
  lake's own ERA5 series — arithmetic, not angling opinion.
- **The shoreline is committed to the repo** (`config/lakes/pomocnia.outline.geojson`)
  and beats any network fetch. See Traps.
- **Water type (`pzw` | `commercial`) is the segmentation key for CPUE.** Not
  cosmetic: averaging a stocked fishery against a wild lake produces a
  reasonable-looking number that means nothing.
- Two standing rules from the owner: replies are short; finished work merges and
  deploys automatically.

## Broken / unfinished

1. **The map can only draw rings and a gradient** — backlog §11, the real
   blocker. Every spatial input is distance-to-shore or fetch, both smooth on a
   convex bowl. Real zones need weed edges and depth, which only the owner can
   mark.
2. **`r20_mgl = 2.0`** (respiration load) is the least defensible number in the
   ruleset and the answer moves a lot with it. First thing calibration should
   attack.
3. **Rudd and ide temperature optima are LOW confidence** — no feeding
   experiment found, only aquarium and pond-keeping sources that disagree.
4. **Commercial zone weights are untested** — no commercial water logged.
5. **PZW closed seasons and size limits are not encoded.** Per-okręg, needs
   research. `is_regulated()` marks where they go.
6. The published site is still the read-only half; the notebook needs a host —
   see §9 of the handover.

## Traps

- **YAML folded scalars split expressions across lines** when continuation lines
  are more-indented than the first. Landed three times, invisible until a route
  raises. `tests/test_ruleset_expressions.py` now walks every ruleset and
  evaluates every expression.
- **A test fixture where `fetch` and `shore` co-vary** makes the zone ranking
  trivially "most exposed first" and produces a meaningless invariance result. I
  reported ±5 °C invariance off it; the real figure is rank-correlation ≥0.976
  at the model's own ±0.8 °C band.
- **Overpass throttles cloud IPs.** The GitHub runner failed the shoreline fetch
  on every build and silently fell back to a circle — so the published overlay
  scored a lake shape that does not exist, for its entire life. Never fetch
  geometry at build time.
- **This sandbox blocks** every CDN, `youtube.com`, `*.github.io`, Azure blob
  storage, Overpass and Open-Meteo. Anything needing those must be verified on a
  real machine, and `tools/save_outline.py` must be run from one.

## Verified vs assumed

**Verified by looking:** the Pyodide spike passed 8/8 on the real Pages URL with
the true OSM outline (owner's screenshot); the committed outline is 8.73 ha
against the 9 ha in config and 381 × 305 m; the grid dropped from 3564 to 3495
cells once clipped to the real shore; the model replay reproduces the source
video's own conclusion (0.17 → 0.51 across its week); every deploy green.

**Assumed:** the water-temperature model has never met a thermometer. Commercial
weights have never seen a catch. Nothing in the scoring has been validated
against real fish — that is what the calibration loop is for, and it does not
exist yet.

## Next

Backlog §11 is the highest-value thing and it is blocked on the owner: walk the
lake once and mark the weed edges and the deeper holes on the map. Ten minutes
of local knowledge adds more spatial information than any further weather
modelling, because it is the only source of the asymmetry the map is missing.

After that: a `SessionStart` hook so the venv and Playwright are rebuilt
automatically (currently done by hand every session), and the Mazowiecki PZW
limits if the regulation half of the water-type switch is wanted.
