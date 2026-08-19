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
