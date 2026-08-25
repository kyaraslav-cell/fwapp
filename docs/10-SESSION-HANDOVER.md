# 10 — Session handover

Written at the end of the first build session, for whoever (or whichever
model) picks this up cold. Read `CLAUDE.md` first, then this.

---

## 1. What exists right now

A working FastAPI + SQLite app, 321 tests, `make check` green (ruff,
`mypy --strict` on `app/core` `app/rules` `app/features` `app/auth` `app/jobs`
`app/discover` `app/geo` `app/intel`, pytest).

Per-session detail lives in `docs/handoff/` — newest file first. Use the
`session-start` and `session-end` skills.

Default branch: `claude/repository-edit-push-ggr229` on `kyaraslav-cell/fwapp`.
Every finished change is merged there and pushed (rule 13).

| Area | State |
|---|---|
| Weather ingest (Open-Meteo, hourly, APScheduler) | works |
| Immutable prediction writer, `inputs_hash`, ruleset versioning | works |
| Restricted-AST expression evaluator (no `eval`) | works |
| Real OSM lake outline via Overpass, cached, circle fallback | works |
| 5 m grid clipped to the outline, ~3 564 cells | works |
| Heat overlay (canvas upscale → smooth field), red→green | works |
| Three-factor bite model (pressure/oxygen/water temp), v0.4 active | works |
| Water temperature: lumped model + 27-member uncertainty band | modelled, never measured |
| Thermal phase from modelled water temp, not the calendar | works |
| ERA5 archive backfill (the pressure norm needs 8760 h) | works |
| Real OSM shoreline committed to the repo, no build-time fetch | works |
| Water type (pzw/commercial) + filter on the places list | works |
| Pyodide + shapely spike, passed on the real Pages URL | done |
| Session notebook: spot → method → rods → catches → end | works |
| 25-species DB, PL/EN/scientific search | works |
| Catch weight/length sliders, bait, photo, edit, delete | works |
| RU / PL / EN with on-page switcher | works |
| Fish pin: held drag, dive, splash | works |
| Water-type filter as a segmented switch | works |
| Day strip (today + 7) behind a calendar icon, map re-scores per day | works |
| Thermal-phase line on the lake page | **removed** — see backlog §14 |
| Add a water by name: search, job queue, staged build | works, **never run against Nominatim/Overpass** |
| Large waters: OSM relations, split boundaries, scaled radius | works — see `docs/13 §11` |
| Accounts: password sign-in, sessions, per-angler notebook | works |
| Login + registration rate limiting | works |
| Security headers (CSP, nosniff, frame, HSTS) | works |
| `/health`, 404 and 500 pages | works |
| Catch photos: oriented, downscaled, EXIF stripped | works |
| Nominatim / Overpass / Open-Meteo | **run for real**, live on the owner's machine (`zalew-zegrzynski` added 2026-08-24) |
| Offline / service worker | **not built** — `docs/15 §A5`, the biggest gap |
| Gemini local-knowledge pass (`intel` job, `water_fact`) | **run for real**, 2026-08-24 — translated into all 3 site languages, trimmed to essentials (`docs/handoff/2026-08-24-2152-...md`) |
| Sign in with Google | wired and verified end-to-end (real client id, correct redirect, correct consent-screen URL) — the human consent click-through is the owner's to complete |

**Run it:**
```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
rm -f fishlog.db*        # after any schema change
make check && make dev
```

**Put it on a URL:** the published Pages site is the read-only half only —
sessions, catches and history need a process and a disk. See §9.

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
11. **Replies are short.** What was done, what could not be done, what is left.
    Nothing else — the reasoning goes in the commit and the docs.
12. **The owner cannot download files.** Never deliver anything as a file to
    save — no `.skill` packages, no attachments, no "click to install". Anything
    that needs to reach them goes into the repository and is read on GitHub, or
    is shown inline. Images sent for review are fine; files to be saved are not.
13. **Merge and deploy automatically.** Every finished change goes to the
    working branch, then straight into the default branch, and the site
    rebuilds. No waiting to be asked. (Superseded the earlier rule of merging
    only on request — the owner changed it.)
14. **One sentence under a control, never a paragraph.** Explanatory text on a
    UI element is capped at a single sentence. The owner cut the day strip's
    note from five lines to one, twice. If something needs more explaining than
    that, the control is wrong.
15. **New features are MVP-first.** Lightweight, free to run, quick to build,
    with real error handling, and a core process polished enough to be upgraded
    later rather than rewritten. Better providers and larger scale come after
    the backbone works — the owner said this in those words when scoping
    add-a-water.
16. **Never show a number the data cannot support.** "% chance of a fish"
    needs calibration against logged sessions, and there are none. A colour
    band is what the engine honestly produces. This generalises rule 2 from the
    day score to anything the app might be tempted to quantify.
17. **One active session per angler, not one per browser.** Concurrent
    sign-in from different locations is not allowed (2026-08-25) - a fresh
    login revokes every session that came before it, `app/auth/service.py`'s
    `start_auth_session`. The trade this makes is deliberate: switching from
    phone to laptop mid-trip signs the phone out. Pinned by
    `tests/test_auth_routes.py::test_a_new_sign_in_revokes_the_previous_one`.

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
8. **Auth: two things still left out** (ADR 0004 and its addendum). No
   password reset (needs SMTP), no email verification. **Login rate limiting
   is now built** - `app/auth/throttle.py`, three windows, checked before the
   password is hashed. Behind a reverse proxy set `FISHLOG_TRUST_PROXY=1` or
   every request counts as one address and the per-IP limit locks everyone
   out at once. The Google flow has never reached Google from this sandbox;
   its first real exchange will be on the owner's machine, and the redirect
   URI has to be registered in the Google console first.

---

## 6. Things never verified from the build sandbox

The sandbox blocks outbound HTTP to everything except a small allowlist, so
these have **never actually run**:

- live Open-Meteo ingest (fails closed into `ingest_gap`, which is correct);
- the Overpass outline fetch — the real Pomocnia polygon has never been seen,
  and `outline_source` on the lake page will say whether you got `osm` or
  `circle_fallback`;
- Esri satellite tiles and Google Fonts;
- the Pyodide spike's second half. Every CDN is blocked from the sandbox, so
  `loadPackage("shapely")` has never been executed here. Booting Pyodide and
  running the scoring modules in a browser *has* been — see
  `docs/12-SPIKE-PYODIDE.md` §2 for what is measured and what is still owed.

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
docs/adr/0004                 accounts, sign-in, and the public/private boundary
docs/adr/0005                 adding waters: the queue, named waters, no fake shorelines
docs/13-ADD-A-WATER.md        the pipeline, its costs and its failure table
docs/16-DEPLOY-ORACLE.md      Oracle Cloud Always Free runbook, §9's fallback
tools/oracle_vm_setup.sh      bootstraps that VM: docker, repo, compose, tailscale
app/discover/                 nominatim search, dedupe, quota, add
app/jobs/                     queue state machine, handlers, runner
app/auth/                     passwords, validation, tokens, google, service
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
tools/switch_sheet.py         the water-type switch in every state x language; --strip films the thumb
tools/build_static.py         render the read-only site for GitHub Pages
tools/build_spike.py          the Pyodide spike page and its payload
tools/spike_check.py          drive the spike in a real browser, or as a control
.github/workflows/pages.yml   twice-daily ingest + publish
docs/11-DEPLOY-PAGES.md       what Pages can and cannot host, and the setup
docs/12-SPIKE-PYODIDE.md      can a browser run our geometry? the measurements
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

---

## 8a. Keys and secrets — where they go

Every optional feature is switched on by an environment variable and is off,
honestly and visibly, without one. Nothing is ever read from a file in the
repository, and no key is ever committed — a key in git history is a leaked key
after it is deleted, and the fix is revoking it, not removing it.

`.env.example` is the committed list of every variable, with no values.
`.env` is the real one and is gitignored.

**Running with docker (the deployment path, `docs/10 §9`):**

```bash
cp .env.example .env      # then edit .env and paste the key in
docker compose up -d      # compose reads .env from this directory
```

**Running with `make dev`, or in a Codespace:**

```bash
cp .env.example .env      # then edit .env and paste the key in
make dev                  # the app reads .env at startup
```

`app/core/env.py` applies `.env` when the app starts, so the same file works
inside and outside docker. **A variable already set in the shell always wins**
over the file, so `FISHLOG_GEMINI_API_KEY=... make dev` still does what it
looks like it does.

**Check it actually works — the important part:**

```bash
make preflight               # deps, env, nominatim, overpass, open-meteo, gemini
make preflight ARGS=gemini   # just one section
make install                 # after any pull that touched requirements.txt
```

The **deps** section runs before anything that imports app code. A virtualenv
older than a line in `requirements.txt` otherwise surfaces as
`ModuleNotFoundError` from the import machinery, which names the missing module
and not the reason - that is how Pillow presented after ADR 0006.

`tools/preflight.py` calls each real service and says which layer refused.
Nothing in this app has ever reached any of them from the build sandbox
(§6), so **this command is the only thing that turns "believed" into
"observed"** — run it once on a machine with network before trusting any of it.
It never prints a key (first four characters and a length), writes nothing, and
exits non-zero when a section fails.

| Variable | Switches on | Without it |
|---|---|---|
| `FISHLOG_GEMINI_API_KEY` | the local-knowledge pass (`docs/13 §10`) | the `intel` job succeeds and reports "skipped" |
| `FISHLOG_GEMINI_MODEL` | overriding a stale model id | the default in `app/intel/gemini.py` |
| `FISHLOG_GOOGLE_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` | Sign in with Google | the button is not rendered at all |
| `FISHLOG_TRUST_PROXY=1` | reading `X-Forwarded-For` | the socket peer is the address |
| `FISHLOG_FRAME_ANCESTORS` | a dev container preview pane framing the app | `frame-ancestors 'none'`, and the pane shows "refused to connect" |

A Gemini key comes from https://aistudio.google.com/apikey. The free tier
covers this comfortably: one call per water added, plus one per monthly
refresh.

**If `make preflight` says the key is not set:** the `.env` has to be in the
repository root, beside `Makefile`. `docker compose config` prints what compose
resolved for the docker path. A key that is present but refused shows as
`Gemini returned 400/403`, which is a different problem — wrong key, or the
Generative Language API not enabled on that Google project.

---

## 9. Where it runs — hosting the full app

The published Pages site (`docs/11`) is **half** the app: it reads. Sessions,
catch logging, history and CPUE all write, so they need a process and a disk,
and they are on no URL today. This section is the standing answer to "why can't
I log a fish on the published site".

**Constraint that decides everything:** the SQLite file must survive restarts
and redeploys. Law 2 makes `prediction` rows immutable evidence and the whole
calibration loop is built on a season of accumulated sessions — a host that
resets its storage does not lose "some cache", it destroys the project's only
asset. Any host without a persistent volume is disqualified, free or not.

### The decision: own the machine, rent nothing

```bash
docker compose up -d        # the full app, port 8000, SQLite on a named volume
tailscale funnel 8000       # a stable public https://<machine>.<tailnet>.ts.net
```

Free for personal use, no domain to buy, no ports forwarded on the router, no
certificate to renew — Tailscale terminates HTTPS and relays in. The database
stays on hardware the owner owns, so backup is what `docs/05` already says it
is: copy the file.

**The honest trade:** the app is reachable only while that machine is awake.
"Always-on" in `docs/01` then means "that box stays on" — an old laptop with the
lid-close action set to nothing, or a Pi. Nothing else here is free *and*
persistent *and* zero-maintenance; this one trades a few watts for all three.

### Fallback, if no machine can stay on

**Oracle Cloud Always Free** — an Ampere ARM VM, free for the account's
lifetime, with block storage. Same `docker compose up -d`, plus **Tailscale
Funnel** for HTTPS rather than Caddy — it reuses the exact mechanism the
primary plan already uses, so it needs no domain purchase and no certificate
to renew, unlike Caddy. Full runbook, including the security-list ingress
rule and a committed bootstrap script: `docs/16-DEPLOY-ORACLE.md`,
`tools/oracle_vm_setup.sh`. (A Caddy+domain path is documented there as an
appendix for anyone who already owns a domain.)

Costs that are not money: a card for identity verification at signup, ARM
capacity that is frequently unavailable in a given region, an idle-reclaim
policy to watch, and a VM to patch. As of 2026 the free ARM allocation was
halved to 2 OCPU / 12 GB — still far more than this app needs.

Provisioning the VM and approving the Tailscale device both need a human with
a browser — the build sandbox has no Oracle credentials and cannot click
through a console, so this has been written up, never run.

### Why not what `docs/05-ARCHITECTURE.md` says

That file's deployment line — *"a free tier on Fly.io / Railway"* — was written
against offers that no longer exist. `docs/01..08` are kept as the original
spec, so it is corrected here rather than edited there:

| Host | State in 2026 | Verdict |
|---|---|---|
| Fly.io | free allowance ended 2024; new accounts get a 2-VM-hour / 7-day trial. Always-on `shared-cpu-1x` ≈ $2/mo, volumes $0.15/GB/mo **billed even when stopped** | cheap, not free |
| Railway | free tier ended; trial credit only | not free |
| Render | free web services sleep on idle and have **no** persistent disk | disqualified — would wipe the notebook |

### Still owed by any host

`docs/05` requires a **healthcheck endpoint exposing the last successful ingest
time**, so that a silently dead ingest is loud instead of serving stale
predictions as current. It does not exist yet — there is no `/health` route in
`app/web/`. Build it before this runs unattended.
