# Handoff — 2026-08-26/27, the PZW registry, river districts, and the first measured CPUE

A long session driven almost entirely by the owner reporting real bugs from the
live site. Two themes: **the app was silently single-water in several places**,
and **PZW's own data is the authority the project had been ignoring**.

## State

Branch `claude/repository-edit-push-ggr229`, pushed through `0540d97`, merged
and deployed. `make check` equivalent green: ruff, `mypy --strict` on the
required packages, **484 passed / 9 skipped**. Live at
`https://dell.tailf99616.ts.net`, container rebuilt and verified
hash-identical to HEAD across all app + config files.

Live database now holds 8 waters (was 4): Pomocnia, Zegrzyński, Szczęśliwice,
Poniaty, an OSM `narew` row, Kanał Żerański, and **Rzeka Narew nr 6 / nr 7**
which the owner added through the new district search.

## Decisions, and why

**A PZW fishing district is the water, not the river.** The owner's words:
rivers are cut into administrative pieces with their own laws. Narew nr 6, nr 7
and nr 8 are three waters with three permits, three sets of closed seasons and
three sets of catch statistics. One `Lake` row spanning them pools four sets of
rules and four CPUE populations, which is precisely what law 3 exists to stop.
Searching a river now offers its districts first, named and bounded by PZW.

**Three PZW sources, layered, because none is complete.** I got the shape of
this wrong twice and the owner corrected me both times:

| Source | Waters | Geometry | Notes |
|---|---|---|---|
| Okręg permit PDF | 109 | none | authority on what a permit *covers* |
| National register `pzw.pl` | 2 084 | point coords (unfetched) | patchy per okręg — Toruń 219, Legnica 1 |
| **Okręg map `ompzw.pl`** | 183 | **rings + river lines** | the best source, and the only one with both of the owner's waters |

`registry()` reads every `config/pzw/*.yaml` and merges records of the same
water. My first claim that "there is no national machine-readable registry" was
simply wrong — recorded as a correction inside ADR 0007 rather than quietly
edited away.

**Merge on key + place, never on okręg.** Grouping by okręg merged nothing
across files: the national register labels every water `poland` while the
schedule and map say `mazowiecki`. The place separates waters perfectly well on
its own — the five lakes called Czarne are in Kwilcz, Bobrowo, Olsztyn.

**Position beats name.** 126 registry keys are shared by more than one water.
Name matching must refuse those; a coordinate does not care what anything is
called. `lookup()` tries containment against the okręg map's rings first and
falls back to the name.

**An ambiguous match is not a match.** `lookup()` returns `None` when several
entries match. Picking one would put a wrong `water_type` into the CPUE
segmentation key with nobody watching.

**Favourites and removals are per angler, and removal is soft.** Anhelina
shares this database and has sessions on Szczęśliwice. A global delete would
take her water and orphan immutable prediction rows. `angler_lake` records what
one angler thinks of one water; nothing is ever deleted.

**The 2024 catch register is the project's first measured CPUE** — and it
cannot calibrate the engine. I proposed it as a way to validate the scoring and
that was wrong: the report is annual, so there is no daily resolution for a day
score and none within a water for a zone score. Ranking whole waters by annual
catch would measure stock and fertility, which the engine deliberately does not
model. `tools/calibration_check.py` says this in its own docstring so nobody
rebuilds the wrong thing.

**A course is never an outline.** Canals and rivers are lines in OSM. Buffering
the centreline by a guessed width would produce a shoreline nobody surveyed —
the fabrication ADR 0005 §4 refuses — so linear waters get a drawn course, no
polygon, and no 2D grid.

**River sections do carry a score, over my objection.** I argued they should
stay uncoloured because the zone model is wind fetch and distance-to-bank,
neither of which means anything on a 25 m canal. The owner overruled it. Rather
than half-do it, `river_section` in the ruleset follows the ADR 0002 precedent
exactly: geometry-only terms (bend sinuosity, cross-wind), weights in YAML,
`ai_authored_provisional`, `status: hypothesis`, `supersede_with:
FORMULA_RIVER_SECTION`.

## Broken / unfinished

1. **`narew` (the OSM row) cannot be auto-converted.** It sits at Wizna
   (53.23 N, 22.07 E) — Okręg **Białystok** water. Only Mazowiecki's map is
   imported, so the nearest district we hold geometry for is 41 km away and
   `tools/pzw_district_convert.py` refuses rather than guess a permit. Fix by
   scraping Białystok's map, or `--to <pzw_key>` with a district named by hand.
2. **Anhelina still has two sessions open since 2026-08-24** (Szczęśliwice,
   Pomocnia). Not touched — standing rule 18. Note the new one-session rule
   means she cannot start a new session until they are ended.
3. **The calibration loop still has nothing to compare.** It needs a water with
   both a registered baseline and an **ended** session with weighed catches.
4. **Districts with no geometry cannot be added.** `pzw.districts()` skips
   them, because a water with no position gets no weather either. That is why
   Białystok's Narew districts are unreachable from search.
5. **Only 29 of the catch report's 42 sections parse a daily rate**; the rest
   phrase their figures differently.
6. **~40 non-interactive `--muted` usages still fail WCAG AA** (backlog §20),
   deliberately left — fixing them everywhere trades against standing rule 8.

## Traps

- **A shell heredoc turns `\b` into a literal backspace (0x08).** This bit
  three separate times and is *silent*: the regex compiles and simply never
  matches. `pzw.is_district` returned False for every district; species shares
  parsed as zero. Write regexes with the Write tool, or use lookarounds
  (`(?<![a-z])`) instead of `\b`.
- **`str.replace` with a 4-space-indented pattern matches inside an
  8-space-indented line.** This corrupted `tools/pzw_okreg_map.py` into a
  syntax error by inserting a dataclass field in the middle of a function.
- **Deleting markup orphans the JavaScript bound to it, and one throw kills
  every handler after it.** Removing the "Right now" line broke the *calendar
  icon*; hiding the spot form broke the method cards and rod counter. Guarded
  by `tests/test_template_element_ids.py`, which was proven non-vacuous by
  reintroducing the bug.
- **`L.geoJSON(null)` and `gridBounds({})` both throw, and the catch hides the
  entire map** — tiles, pin, spot-picking. Kanał Żerański and Łowisko Poniaty
  both had no map at all above a line saying "everything else works".
- **Percentile ranking manufactures a spread out of floating-point noise.** A
  straight canal with the wind along it is genuinely uniform and must stay
  uniform.
- **Thinning a polygon by dropping every Nth point wrecks it.** Zegrzyńskie's
  476-point ring came back self-intersecting, so `contains()` could not answer.
  Use Douglas-Peucker with `preserve_topology`.
- **`karpiowate` is the cyprinid family and starts with `karp`.** It put a 57%
  carp share on a water whose real share is 2.8%.
- **The report writes "respectively" lists** — every figure after every name —
  so a generous regex window reads the wrong species' number.
- **The preview instance caches route code.** Template edits show up live;
  route changes need a restart, which cost a confusing "the button isn't there"
  round.
- **`docker compose up -d --build` reporting `Running` rather than `Recreated`
  is correct for docs-only commits** and a red flag for code ones.

## Verified vs assumed

**Verified by driving or filming, not by reading a diff:**

- The float's bite animation — filmed with the new
  `tools/element_filmstrip.py`. **The first attempt was invisible**: an elegant
  3px dip at 22px that both a screenshot and the keyframes hid.
- Ctrl+wheel zoom, both ways: plain wheel scrolled the page, Ctrl+wheel zoomed
  and the page stayed put.
- Session start/log/end on a non-seeded water, end to end.
- The second-session refusal, favourite reordering, remove and restore.
- Kanał Żerański's map and Narew nr 7's course, by looking at the render.
- Kanał Żerański returning **one** search result, and Jezioro Białe still
  returning **eight** — against the real geocoder.
- Pomocnia's and Szczęśliwice's catch figures, read back against the report's
  own sentences.
- Deploy: app+config hashes identical between container and HEAD.

**Assumed, not verified:** that the river section ranking is *useful*. It is
geometry with guessed weights and has never been checked against a catch. The
UI says so; nobody should read more into it.

## Next

1. **Decide the `narew` row** (see Broken §1). Either "scrape Białystok" or
   name the district and I run `--to`.
2. **End a session with weighed catches** on a water that has a registered
   baseline — Pomocnia or Szczęśliwice — and `tools/calibration_check.py`
   produces the project's first real comparison.
3. If more okręg maps are wanted, `tools/pzw_okreg_map.py --url ... --okreg ...`
   already takes them; only the page's JS shape is Mazowiecki-specific.
4. Longstanding and untouched: terrain/wind shelter (backlog §3/§8) and offline
   support (`docs/15 §A5`), both still needing an ADR before code.
