# 13 — Adding a water: the plan

The MVP backbone for turning *"Jezioro Zegrzyńskie"* typed into a box into a
lake page with a map, a forecast and an overlay. Written before the code.

**Scope decision:** named waters only. PZW waters and commercial fisheries all
have names — that is the whole target set. Unnamed forest ponds are out of
scope, which removes the entire raster/tracing branch from the MVP.

---

## 1. What the angler sees

```
type a name  →  pick from a list  →  lake page opens immediately
                                     (satellite + pin + "preparing this water")
                                        ↓  seconds to minutes, in the background
                                     outline → grid → weather → forecast
                                     the page fills in as each lands
```

Nothing blocks on a slow API. A water is usable — you can see it, pan it, drop a
pin — before any of the derived work finishes.

## 2. The pipeline, and what each step costs

| Step | Source | Cost | Blocking? |
|---|---|---|---|
| name → candidates | Nominatim | ~0.3 s, **1 req/s hard limit** | yes, it is the search |
| create the lake row | — | instant | yes |
| shoreline polygon | Overpass | 2–30 s, sometimes down | **no** |
| grid + fetch fields | local CPU | 0.1–5 s by size | no |
| 1 year of pressure history | Open-Meteo archive | ~5 s, ~8 800 rows | no |
| forecast + predictions | Open-Meteo | ~1 s | no |
| local knowledge | Gemini | 10–60 s | no |

Only the first two are in the request. Everything else is a job.

## 3. The job queue

A `job` table drained by APScheduler, which is already a dependency. No Celery,
no Redis — the stack rules stand.

- One job in flight at a time. This is a single-container app on a domestic
  connection; parallel Overpass calls would only get it rate-limited faster.
- Every job: `queued → running → done | failed`, with `attempts`, `last_error`
  and exponential backoff. A failed job is *visible*, not silent.
- Jobs are idempotent. Re-running `outline` on a lake that has one is a no-op,
  so a retry can never corrupt what already worked.
- Dependencies are explicit: `grid` waits for `outline`, `predictions` waits for
  `weather_backfill`. A job whose prerequisite is missing goes back to the queue
  rather than failing.

Kinds: `outline`, `grid`, `weather_backfill`, `predictions`, `intel`, `refresh`.

## 4. What "ready" means, and what is shown before it

The lake page renders at every stage and says which one it is at:

| Stage | Map | Day strip | Overlay |
|---|---|---|---|
| just added | satellite + pin | — | — |
| outline in | satellite + shoreline | — | — |
| weather in | + | colours | — |
| grid in | + | + | colours |

**No circle fallback for new waters.** If Overpass has no polygon, the water
keeps a satellite map and a forecast and says the shoreline is missing. A circle
is a fake lake, and every fetch computed across it is fiction (law 4 in spirit:
do not fabricate the input either).

## 5. Grid size scales with the water

Pomocnia at 5 m is 3 564 cells ≈ 60 KB of JSON. A 500 ha lake at 5 m would be
~200 000 cells ≈ 3.5 MB — per wind bucket, over a phone connection, every time
a day is tapped. So the cell size is chosen from the area to target ~5 000
cells, clamped to [5 m, 50 m]. The limit is *transfer*, not compute.

## 6. Refreshing

- OSM changes: one `refresh` job per water per month. 100 waters = 100 Overpass
  calls a month, which is nothing against a ~10 000/day allowance.
- A water already in the database is never re-discovered. Searching for it
  again just opens it; only the monthly refresh updates it.

## 7. Quotas and abuse

Adding a water costs an Overpass call, an archive backfill and (later) a Gemini
pass. Any signed-in angler may add, with a small daily quota per account. The
binding external limit is **Nominatim's 1 req/s**, so the search itself is
throttled process-wide, not just per user.

## 8. Failure, in every direction

| What fails | What happens |
|---|---|
| Nominatim down | search says so, nothing is created |
| no candidates | "no water found by that name", with the name echoed |
| Overpass down / no polygon | lake exists, satellite map works, no overlay, stage says why |
| archive fails | no day colours, strip says no data (law 4 - never invented) |
| grid too big | cell size grows; if still too big the job fails visibly |
| duplicate | existing water is opened instead of a second row |
| quota hit | told how many are left and when it resets |

## 9. Not in this step

- Raster auto-tracing for unnamed waters (needs numpy + a GeoTIFF reader → its
  own ADR, only if the named-water path proves insufficient).
- Manual shoreline tracing.
- Rivers. The beat boundaries are findable, but every score term assumes a
  closed bowl and flow is not modelled at all.
- Per-lake formula coefficients. The AI supplies *facts*, never weights
  (ADR 0005 §2).

---

## 10. The Gemini pass — what it collects, and what it is not allowed to do

Built 2026-08-19. `app/intel/`, job kind `intel`, last in the pipeline because
nothing waits on it and it is the only stage that costs money.

### The shape

```
lake name + coordinates
        │
        ▼  one call, temperature 0, responseMimeType=application/json
   Gemini, answering against a fixed responseSchema
        │
        ▼  app/intel/facts.py
   every claim without a citable http(s) URL is DROPPED
        │
        ▼  one HEAD per unique URL
   source_ok: 1 answered · 0 returned 404/410 · NULL never checked
        │
        ▼  app/intel/service.py
   water_fact rows, verified_by_owner = 0, previous rows superseded
```

### The six topics, and why the list is closed

`species`, `depth`, `bottom`, `access`, `rules`, `stocking`. A claim under any
other topic is dropped, and this is the enforcement of ADR 0005 §2 rather than
a tidiness preference: an open vocabulary is the crack through which a
"recommended depth multiplier" eventually arrives. A per-water coefficient
invented by a model is fishing knowledge with no evidence behind it, and it
makes a calibration miss unattributable — the one thing the whole calibration
loop exists to prevent. `tests/test_intel.py` feeds it `weights`, `score` and
`best_times` and asserts all three are refused.

### Nothing collected here reaches the score

ADR 0005 §2 permits collected facts to feed terms the engine already has. They
do not, and will not until a human has confirmed them — `verified_by_owner`,
which nothing currently sets. The facts are shown to the angler, marked
unverified, with their source as a link, and the angler decides. There is no
code path from `water_fact` into `zone_score`, the day score or the ranking.

### The citation is the design, and its weakness is known

A model answering without a search tool can write a URL that never existed, and
it will look exactly like one that did. Three things follow:

1. a claim with no usable URL is dropped rather than stored with an empty
   column that later reads as "source unknown";
2. each unique URL is HEAD-checked once; a definite 404/410 is marked and shown
   as **link dead** beside the claim, which is kept because pages move;
3. a check that could not run leaves NULL and drops nothing. Our own machine
   being offline is not evidence against somebody's citation.

**The upgrade, when this proves insufficient:** search grounding
(`tools: [{"google_search": {}}]`), which returns real retrieved URLs. It could
not be combined with `responseSchema` at the time this was written, so it would
mean parsing loose text — a worse trade for an MVP than a strict shape plus a
HEAD check. Revisit with a real answer in hand.

### Failure, in every direction

| What fails | What happens |
|---|---|
| no `FISHLOG_GEMINI_API_KEY` | job succeeds, reports "skipped". A deployment that has not switched this on is not a broken water |
| the answer is empty | success. For most small waters this is the true answer, and a prompt that does not make it acceptable gets a confident invention instead |
| quota, 4xx, 5xx | job fails visibly and backs off; the water keeps everything else it has |
| answer blocked | fails with the `finishReason`, so a safety block and a quota refusal are not the same log line |
| answer is not JSON | fails saying so, despite the schema |
| every claim unsourced | success, zero facts stored, the count of drops in the log |

### Costs

One call per water, plus one per monthly refresh. Nothing else in the app calls
it. `FISHLOG_GEMINI_MODEL` overrides the default model id, because the model id
is the part that goes stale and should be an environment change rather than a
redeploy.

### Known gap

The collected prose is English (the prompt asks for it), so the values inside
the section are not translated the way the labels around them are. Translating
them would mean either a second model call per language or storing a claim
three times; neither is worth it before the first real pass shows how much text
there actually is.

---

## 11. The jsonv2 field-name bug — read this before writing another fake

**Symptom:** every search result, including Zalew Zegrzyński at 3 300 ha, came
back marked "not a water", and adding one was refused. It read exactly like a
tagging problem at OpenStreetMap's end.

**Cause:** the request asks for `format=jsonv2`, and jsonv2 **renames `class` to
`category`**. `_to_candidate` read `row["class"]`, got an empty string for every
result, matched no entry in `WATER_TYPES`, and set `is_water=False` on all of
them. One field name; the entire feature dead.

**Why the tests were green:** the fixtures said `"class"` too. They were written
by reading the parser, not the API. A fake built from the same assumption as the
code under test asserts the assumption and nothing else — and this project
cannot reach Nominatim from the build sandbox, so a fake is all there is.

**The rule this earns:** when a fixture stands in for a service nobody here can
call, its field names come from that service's documentation, and the test says
in its own docstring which format it is imitating. `tests/test_discover.py` now
does, and the parser reads both names so that changing the `format` parameter
cannot resurrect this.

**And the reason it was invisible:** the picker printed "not a water" with no
hint of what the result actually was. It now prints the OSM tag beside the
badge — `place=village` is a correct refusal, an empty tag is a broken parser,
and the two were indistinguishable for as long as this bug lived.
