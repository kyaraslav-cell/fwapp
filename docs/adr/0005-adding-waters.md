# ADR 0005 — Adding waters: a job queue, named waters only, and no invented shorelines

**Status:** accepted, being built. `docs/13-ADD-A-WATER.md` is the plan it
justifies.
**Date:** 2026-08-19

---

## Context

`docs/01-SPEC.md` scoped the project to one lake and `docs/05-ARCHITECTURE.md`
noted multi-lake "requires only UI work". That was optimistic: the UI is the
smallest part. Adding a water means geocoding a name, fetching a shoreline from
a service that is slow and sometimes absent, building a grid whose size depends
on the water, backfilling a year of pressure history, and — later — collecting
local knowledge from the open web.

The owner's criteria: **lightweight, free, easy to build, good enough for tests,
with a backbone that survives being upgraded to better providers later.**

## Decisions

### 1. Named waters only

PZW waters and commercial fisheries are named, and they are the entire target
set. This deletes the hardest branch of the problem — deriving a shoreline for
an unmapped pond from satellite rasters — along with its dependencies (numpy, a
GeoTIFF reader) and its accuracy caveats. If the named path turns out to miss
too much, the raster branch gets its own ADR then, informed by how often it
actually fired.

### 2. The AI supplies facts, never coefficients

Confirmed with the owner. Gemini fills a per-water profile — species present,
water type, depths, bottom, access, rules — and those facts feed terms the
engine already has. It never proposes weights.

A per-lake coefficient invented by a model is fishing knowledge with no evidence
behind it, and it does something worse than being wrong: it makes the
calibration loop meaningless. Phase 5 exists to measure the app's predictions
against logged reality; if every water scores by its own unvalidated rule,
a miss cannot be attributed to the weather model, the formula, or the
hallucination. Law 1 says the knowledge lives in the YAML; this keeps it there.

### 3. Everything slow is a job, and jobs are visible

A `job` table drained by APScheduler. Not Celery, not Redis: the stack rules
forbid an external queue, and this app is one container with one writer.

The design constraints that matter more than the mechanism:

- **Idempotent handlers.** A retry must not corrupt what already succeeded.
- **Explicit prerequisites.** `grid` needs `outline`; `predictions` needs
  history. A job missing its prerequisite re-queues rather than failing, so a
  slow Overpass does not cascade into three red jobs.
- **Failures are shown.** The lake page names its stage and says when something
  failed. A silent stuck pipeline is the failure mode that makes a user think
  the app is broken rather than busy.
- **One at a time.** Parallelism here buys nothing and gets us rate-limited by
  Nominatim and Overpass sooner.

### 4. No circle fallback for a new water

The existing `circle_fallback` was a reasonable hedge for one known lake whose
polygon we could verify by eye. Generalised to arbitrary waters it becomes a
lie: an 18-sided circle that is not the lake, over which the engine computes
fetch across water that does not exist, and prints a coloured overlay with the
same confidence as a real one.

New waters therefore get: satellite map, pin, weather, forecast — and **no
overlay at all** until a real polygon exists. Pomocnia keeps its committed
outline and its existing behaviour.

### 5. Grid resolution follows the water's area

Fixed 5 m cells were right for 9 ha. The binding constraint at scale is not CPU
but the JSON handed to a phone: ~200 000 cells for a 500 ha lake, per wind
bucket, on every day tap. Cell size is chosen to target ~5 000 cells, clamped to
[5 m, 50 m], and stored with the grid so a cached grid and a live one can never
silently disagree about what a cell is.

### 6. Discovery order: name, then location

`Nominatim` resolves the name to a point and an OSM id. The shoreline then comes
from `app/geo/outline.fetch_osm_outline`, which already searches **by location**
and already excludes rivers and prefers a polygon containing the point.

This ordering matters: many small waters are in OSM with a shape but no `name`
tag, so a name-only lookup would report "not mapped" for a water that is mapped.
Searching by name to find *where*, then by location to find *what*, recovers
those.

## Consequences

- One new table (`job`), one new package (`app/jobs`), one new client
  (`app/discover/nominatim.py`). No new dependency.
- `app/geo/service.py` grows an area-dependent cell size; anything that cached a
  grid keyed only by lake must now key by cell size too.
- The published static site builds one water and is unaffected.
- Nominatim's 1 req/s is a **process-wide** limit, not per user, so the search
  is throttled centrally. Their usage policy also requires a real User-Agent,
  which `app/geo/outline.py` already sets for Overpass.
- None of the network paths can be exercised from the build sandbox
  (`docs/10 §6`). Every client fails closed and is tested against fakes; the
  first real search will be on the owner's machine.

---

## Addendum — the Gemini pass as built, 2026-08-19

§2 said "the AI supplies facts, never coefficients". Building it turned that
principle into three mechanisms, because a principle nobody enforced would have
lasted exactly until the first useful-looking number.

1. **A closed topic list.** Six topics, in code, in `app/intel/facts.py`. A
   claim under any other topic is dropped. An open vocabulary would have been
   the way a "depth multiplier for this lake" eventually arrived.
2. **A claim with no citable URL is not stored at all.** Not stored with a null
   source — dropped. A column that is sometimes empty gets read as "source
   unknown" within a month, and the whole value of this feature is that a claim
   about the owner's own water can be checked in one tap.
3. **Facts do not reach the score, verified or not.** §2 permitted them to feed
   terms the engine already has; that permission is not exercised, and
   `verified_by_owner` exists as the gate for the day it is. Nothing sets it
   yet.

**The known weakness, stated plainly:** an ungrounded model can fabricate a URL
that looks exactly like a real one. The mitigation is a HEAD check per URL
whose three outcomes are *answered*, *404*, and *could not check* — the last
of which drops nothing, because our being offline says nothing about the
citation. The real fix is search grounding, which could not be combined with a
strict response schema when this was written. `docs/13 §10` carries the trade.
