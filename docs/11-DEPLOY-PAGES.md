# 11 — Publishing the conditions board to GitHub Pages

## What gets published, and what does not

GitHub Pages serves **files only**. No Python, no SQLite, no POST. So the
published site carries the half of Fishlog that only reads:

| Published | Not published |
|---|---|
| Conditions now | Starting a session |
| Five-day weather table | Logging / editing / deleting a catch |
| Lake outline and map | History and CPUE |
| Provisional zone overlay, per wind direction | The "refresh weather" button |
| All three languages | Anything that writes |

The notebook is the point of the project, and it needs a writable database.
A page that *looked* like it could log a fish but silently dropped it would be
worse than not offering it, so the build strips those controls and prints a
banner saying where they went. If you want the full app on a URL, it needs a
container host — the `Dockerfile` is already there.

## One-time setup

1. Merge this branch into the repository's **default** branch. `schedule` and
   `workflow_dispatch` only ever run from the default branch, so the workflow
   does nothing until it lives there.
2. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
   This cannot be done from the API token this project uses; it is a repository
   setting and a human has to flip it once.
3. Run the workflow once by hand: **Actions → "Publish conditions to GitHub
   Pages" → Run workflow**. The URL appears in the deploy job's summary, and is
   `https://<owner>.github.io/<repo>/`.

After that it refreshes on its own.

## The schedule

`20 4,16 * * *` — 04:20 and 16:20 UTC, which in summer is 06:20 and 18:20 in
Warsaw: one refresh before a morning session, one before an evening one.

**Twice a day is the publish cadence, not the weather resolution.** Every run
calls the real Open-Meteo ingest, which pulls the whole *hourly* series, so
`weather_hourly` stays hourly exactly as `docs/03-DATA-MODEL.md` requires. The
site is simply rebuilt from it twice a day.

The ingest step is `continue-on-error: true` on purpose. Law 4 says never
fabricate an observation: if Open-Meteo is unreachable the ingest writes nothing
and records a gap, and the build republishes the last *real* observations with
their true "as of" timestamp. Failing the build there would either block the
publish or tempt someone into carrying a value forward to keep the page looking
fresh.

## Two static-hosting problems, and how the build handles them

**Query strings.** The live map calls `/lake/<slug>/grid?wind_dir=270`. A static
host ignores everything after `?` and would return the same file for every
direction, so the overlay would never respond to the wind. The build
pre-renders one JSON per 30° bucket into `grid/<slug>/wd###.json`, and the page
picks the nearest bucket. Twelve files, ~60 KB each. 30° rather than something
finer because the zone score is explicitly provisional and displayed as a
percentile — resolving wind to the degree would be false precision.

**Absolute URLs.** Project Pages live at `/<repo>/`, not `/`, so every
`/static/...` and `href="/"` in the templates would 404. `tools/build_static.py`
rewrites them under `--base`. A user or organisation page served from the domain
root wants `--base ""`.

## Building it locally

```bash
python tools/build_static.py --out dist --base /fwapp
cd dist/.. && python -m http.server 8099   # then open /fwapp/
```

Serve it from a *parent* directory with the output named after the base path, or
the rewritten URLs will not resolve and you will get a stylesheet-less page.

## Known gaps

- **The map needs the network.** Leaflet and the Esri satellite tiles come from
  CDNs. That is fine on Pages and fine on a phone with signal; it is not an
  offline bank-side app. Making it offline means vendoring Leaflet and caching
  tiles in a service worker — not done.
- **`history` is absent, not empty.** The link is stripped rather than showing a
  page that would always read zero sessions.
- **The outline may be `circle_fallback`.** The build fetches the real Pomocnia
  polygon from Overpass; if that call fails the page says so in its own caveat
  line. Check which one you got after the first real run.
