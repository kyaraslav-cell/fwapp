# 12 — Spike: Pyodide + shapely on the Pages URL

**Status:** spike, not a decision. Nothing here adopts anything.
**Page:** `/spike/pyodide/` on the published site — unlinked, `noindex`.
**Built by:** `tools/build_spike.py` · **checked by:** `tools/spike_check.py`

---

## 1. The question

GitHub Pages runs no Python, so `tools/build_static.py` pre-renders twelve
30° wind buckets of zone scores and the page picks the nearest. That is why
the published overlay snaps between buckets, why it cannot answer "what about
at 15:00, when the wind backs to south-west", and why every score on the
static site was computed hours earlier by a GitHub runner.

If CPython and shapely load *in the browser*, the same static host could run
`app/geo/grid.py` and `app/rules/zone_score.py` unmodified, at any bearing,
with no server. That is a claim about megabytes and seconds, and no amount of
reading settles it — so the spike is a page that runs the real modules on the
real outline and compares its answers against the build's own, cell by cell.

## 2. What was measured, and where

Two of the four steps have been run in a real browser here; two have not,
because this sandbox's egress policy blocks every CDN (`cdn.jsdelivr.net`,
its Fastly/Gcore aliases, `unpkg`, `esm.sh`, `cdnjs`) and GitHub release
downloads outside this repository. That is a property of the build sandbox,
not of Pages. **The remaining two steps are exactly what the published page
runs for you when you open it** — which is why it prints its own verdict.

| Step | Where it ran | Result |
|---|---|---|
| Boot Pyodide 314.0.5 from a static host | headless Chromium, here | **pass**, 3.5 s cold |
| Run `zone_score.py` + `expressions.py` unmodified, score 3 564 cells | headless Chromium, here | **pass**, exact match |
| `loadPackage("shapely")` | not run — CDN blocked in sandbox | open |
| `build_grid` + fetch ray-cast in the browser | not run — needs shapely | open |

All four steps **do** pass under CPython 3.12 with real shapely, via
`tools/spike_check.py --reference`, which executes the page's own harness in a
normal interpreter. That is the control: if a step fails in the browser, the
harness is not what is wrong.

### Numbers from the browser run

| | |
|---|---|
| Pyodide | 314.0.5 (pinned in `tools/build_spike.py`) |
| Python in the browser | **3.14.2** — the app targets 3.12; see §5 |
| Cold boot, page load to interpreter ready | **3.5 s** (desktop, headless, local HTTP) |
| Core bytes | 13.1 MB raw · **≈5.9 MB gzipped** (wasm 3.4 MB + stdlib 2.4 MB) |
| Payload (outline, ruleset, sources, expected answers) | 198 KB raw · **70 KB gzipped** |
| Score 3 564 cells | **594 ms** in the browser vs 295 ms native — ≈2× |
| Agreement with the server, 3 564 cells | **exact**, worst difference 0.000000 |

The byte figures are uncompressed on the wire here (Python's `http.server`
sends no `Content-Encoding`); jsdelivr and Pages both serve gzip or brotli, so
the gzipped column is the honest one and brotli will beat it.

### Numbers still owed, and where they come from

Native timings for the shapely half, from the same 3 564-cell lake:
`build_grid` 91 ms, `geometry_inputs` (ray-cast + shore distance) 425 ms. If
the browser holds the ~2× it showed on the scoring step, a full recompute at a
new wind direction lands near **1 s**, on top of a one-off ~6 MB load. The
published page measures this for real; the estimate is not a result.

The shapely wheel itself is 
`shapely-2.1.2-cp314-cp314-pyemscripten_2026_0_wasm32.whl`, listed in the
official `pyodide-lock.json` and pulling numpy 2.4.6 with it. Note the
version: **shapely 2.1.2 in the browser is the same version this repository
pins**, which is the best possible case for the geometry agreeing. pyproj is
also in the distribution (3.7.2) — the stack line in `CLAUDE.md` names it, but
nothing in `app/` imports it today.

## 3. How to read the page

Open `/spike/pyodide/` on the published site. It prints a pass/fail verdict, a
row per step with milliseconds and the size of any disagreement, the browser's
Python/shapely/numpy versions beside the server's, and what the browser says it
transferred. Screenshot it — that is the artefact.

- `?only=core` — stop before shapely; the part that needs no CDN.
- `?index=<url>` — load Pyodide from somewhere else, e.g. a self-hosted copy.

Locally:

```bash
python tools/build_spike.py --out dist --base ""
python tools/spike_check.py --site dist                 # real browser, real CDN
python tools/spike_check.py --site dist --reference     # control, no browser
```

## 4. What this would change if it holds

Today the static site ships **728 KB** of pre-baked grids (12 × ~60 KB) and
still only answers 12 wind directions, none of them current. The Pyodide
version ships a **70 KB** payload and answers any bearing, but asks for ~6 MB
of interpreter first.

That trade is not obviously worth taking, and the spike does not take it. Two
cheaper shapes fall out of the measurements and should be weighed against it
before anyone writes an ADR:

1. **Ship the geometry, compute only the score.** `build_grid` and the shore
   distances do not depend on the wind at all; only the fetch ray-cast does.
   The scoring step needs no shapely, and it is the step already proven to run
   in the browser — so plain JavaScript, or Pyodide core without any wheels,
   could rescore live from a shipped geometry table.
2. **Finer buckets.** More pre-rendered wind buckets cost 60 KB each and no
   load time at all. Sixty of them is 3.6 MB, still under the interpreter.

The case for the full Pyodide route is not the wind slider — it is that one
implementation would then serve both the server and the static site, so the
published overlay could never drift from `app/rules/`. Whether that is worth
6 MB on a phone by the lake is the owner's call, and it needs the real
cold-load number from §3 first.

## 5. Risks the spike surfaced

- **Python 3.14 in the browser, 3.12 on the server.** Pyodide 314.0.5 ships
  CPython 3.14.2. The modules ran unmodified and matched exactly, but this is
  two minor versions of drift that nothing in CI would catch.
- **A pinned CDN version is a dependency in all but name.** `CLAUDE.md`
  requires an ADR before a new dependency. Loading a 6 MB interpreter from
  jsdelivr at page load is one, even though it never appears in
  `requirements.txt`. Self-hosting the core under `dist/` removes the third
  party but puts ~6 MB in every Pages artifact.
- **The outline in this build is `circle_fallback`.** Overpass is blocked from
  the sandbox, so the geometry compared here is a circle, not Pomocnia. The
  parity result is unaffected — both sides used the same polygon — but the
  timings come from a shape simpler than the real shoreline, and the published
  page will say which outline it used.
- **Law 1 holds either way.** The page carries the `zone_score` block from
  `config/rules.v0.3.yaml` as data in `payload.json`; no threshold or weight was
  copied into JavaScript.
