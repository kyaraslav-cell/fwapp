# Handoff — 2026-08-24, the first real deploy, Google + Gemini switched on, and translated/trimmed local knowledge

Continues `2026-08-24-1131`. This is the session where the app left the
sandbox for good: deployed on the owner's own Windows PC via Docker and
Tailscale Funnel, both optional integrations turned on with real keys, and a
real water (Zalew Zegrzyński) added live against Nominatim/Overpass/Gemini for
the first time. `docs/10 §6`'s list of "believed but never observed" is now
much shorter.

## State

Branch `claude/repository-edit-push-ggr229`, working tree has the changes
below, not yet committed as of writing this file (commit happens right after,
same session). `make check` run for real from a fresh venv on the owner's
machine (`python -m venv .venv`, Python 3.11 — not the pinned 3.12, worked
anyway; worth pinning 3.12 explicitly if this ever breaks): ruff clean, mypy
`--strict` clean over the required packages, **328/328 tests pass**.

The app is live at `https://dell.tailf99616.ts.net` — Docker Compose on the
owner's PC, Tailscale Funnel terminating HTTPS, `FISHLOG_TRUST_PROXY=1` set
(`.env`, gitignored, never in this repo). `docker compose up -d --build` and
`tailscale funnel 8000` both need to be running for the URL to answer; neither
survives a PC reboot on its own — nothing here auto-starts either on boot.
That is the next real gap if "always reachable" matters more than it has so
far.

## What got built

**1. Local knowledge, translated and trimmed** (`app/intel/`,
`app/jobs/handlers.py`, `app/web/routes/places.py`). The owner's own words:
"not translated, too many informations, summarize and reduce it, only
essentials."

- `MAX_FACTS` 24 → 14 (`app/intel/gemini.py`). Confirmed live: Zalew
  Zegrzyński went from 24 facts to 14.
- `stocking` capped to **one** summarising fact instead of one row per
  species — that was the single biggest source of clutter (8 of 24 facts on
  the real water were "X stocking" rows). New prompt rule 8.
- **Translation, not a second research pass.** `gemini.collect()` still runs
  once, in English, exactly as before. A new `gemini.translate_facts()` then
  takes that finalised English list and asks Gemini to translate `key`/`value`
  into Polish and Russian, in one call per language, preserving
  `topic`/`source_url`/`source_title`/`confidence` unchanged. This was a
  deliberate choice over asking Gemini to *research* in each language
  separately: a translation call is cheap, fast, and — most importantly —
  guarantees all three languages show the same claims from the same sources.
  Three independent research passes could drift (different sources found,
  different facts kept) and there would be no way to tell a real
  discrepancy from research variance.
- `WaterFact.lang` (new nullable column — see Traps for why nullable) records
  which language a row is in. `NULL` means "written before this existed",
  read as `"en"`. `intel_service.current_facts`/`facts_by_topic` now take a
  `lang` and **fall back to English if that language has nothing** — a failed
  Russian translation pass must not blank the section for a Russian-reading
  angler.
- `app/web/routes/places.py` resolves the visitor's language from the same
  cookie the rest of the site already uses (`app/core/i18n.py`) and passes it
  through. No template change needed — the topic headers were already
  translated (`t('intel.topic.' ~ topic)`); only the fact `key`/`value` text
  itself was English-only before this.
- **Verified live, twice** (docs/10 §3's rule: produce the artefact, don't
  trust your own diff): first run silently produced 0 pl/0 ru facts with no
  error surfaced anywhere reasonable to look; second, after finding and fixing
  the real bug (next section), produced 14/14/14 with correct, fluent
  translations, confirmed by reading the actual stored rows and by curling the
  live page with each language's cookie set.

**2. A real bug found only by running this for real:
`_request_body()` ignored which schema it was asked for.**
`app/intel/gemini.py`'s `_request_body(prompt)` hard-coded the module-level
`RESPONSE_SCHEMA` (the *facts* schema: topic/key/value/source_url/
confidence) regardless of what the caller actually wanted back. The first
translation attempt sent the translate prompt ("translate these items") paired
with the facts schema, and Gemini — constrained to answer in that shape —
quietly **re-ran its own knowledge lookup in Polish** instead of translating
the given English facts. No exception, no error, just plausible-looking wrong
output (the giveaway was 0 pl/0 ru facts stored, because
`translate_facts`'s id-based reassembly couldn't find any `items` key in a
response shaped as `facts`). Fixed by giving `_request_body` a `schema`
parameter and passing `TRANSLATE_SCHEMA` explicitly from `translate_facts`.
**This is exactly the kind of bug `docs/10 §6` warns about** — the code
looked correct, ruff and mypy and all the fake-transport unit tests were
green, and it was still wrong until it hit the real API.

**3. A second real bug, in the test suite's own hermeticity, found while
trying to verify the above.** `app/web/app.py` ends with a module-level
`app = create_app()` so uvicorn can target `app.web.app:app`. `create_app()`
calls `load_env_file()`, which reads the real `.env` **fresh, every time**.
The instant any test file imports `app.web.app` — which happens at pytest's
*collection* phase, before any fixture runs — the real `.env` (now containing
real Gemini and Google secrets, `FISHLOG_TRUST_PROXY=1`) gets read into
`os.environ` for the whole process. Three tests broke the moment a real
`.env` existed on this machine for the first time:
`test_the_google_button_is_hidden_when_google_is_not_configured`,
`test_os_environ_is_left_as_it_was_found`, and
`test_a_forged_forwarded_header_cannot_mint_fresh_addresses` — each one
`monkeypatch.delenv`'d the relevant var, which was already too late. Fixed
with `tests/conftest.py`, which reassigns `app.core.env.ENV_FILE` to a path
that cannot exist, **at module level** (not inside a fixture), so it runs
before pytest imports the first test module. This is a permanent fix, not a
one-off — any future session running tests on this machine would have hit the
same thing.

**4. Everything the owner already had switched on for real.**
`FISHLOG_GEMINI_API_KEY` and the three `FISHLOG_GOOGLE_*` values are set in
the owner's `.env` (never in this repo, never in this doc). Verified, not
assumed:
- Gemini: `GET .../v1beta/models?key=...` → HTTP 200, listed models. The
  `intel` job pulling 14/14/14 real facts above is the deeper proof.
- Google sign-in: `GET /auth/login` now renders the button, and
  `GET /auth/google` 303s to `accounts.google.com/o/oauth2/v2/auth` with the
  right `client_id`, the right `redirect_uri`
  (`https://dell.tailf99616.ts.net/auth/google/callback`, registered in the
  Google Cloud console during this session), and the right scopes. The actual
  human consent click-through was left to the owner — that part needs a real
  Google account interacting with a real browser, which this session cannot
  do for them.
- `docs/09-BACKLOG.md §12` and `§15` updated to reflect both are now live
  rather than "never run against Google" / "never run against Gemini".

## What this session could not do / left for the owner or a future session

Backlog `§19` (`docs/09-BACKLOG.md`) has the full write-up for each. Short
version:

1. **A real lake-shape thumbnail on the home page's water cards**, replacing
   the generic gradient square. Recommended approach: trace the already-cached
   `outline_geojson` into a small silhouette rather than fetching satellite
   tiles — free, already-available data, no new dependency.
2. **The weather-number discrepancy the owner noticed against Google
   Weather.** Deliberately *not* built as "add Google as a second source" —
   `CLAUDE.md` is explicit that there is exactly one weather series for the
   whole lake, and law 4 argues against quietly blending a second live source
   into what a `prediction` row is provably computed from. Needs investigating
   first (coordinates, timezone display), and if both check out, some
   divergence between two different forecast models is just normal and the
   real fix is making the app's own provenance visible enough to tell that
   apart from a bug.
3. **A background job for a higher-resolution heat map on large waters, for
   today only**, so a 2000+ ha water like Zalew Zegrzyński gets finer cells
   than its current 64 m without making every request pay for it. Sketch is
   in the backlog; not started.

## Also from this session, outside the repo

- **Docker Desktop would not start**: "Virtualization support not detected."
  Root cause was the `VirtualMachinePlatform` Windows feature never actually
  being enabled — an earlier attempt via `dism.exe` failed silently for lack
  of elevation, and the machine was rebooted without the feature having taken.
  Fixed with `wsl --install --no-distribution` run in a properly elevated
  PowerShell, confirmed by the "Administrator:" title bar, then a real reboot.
  Second Docker Desktop crash ("sailor-ingest.sock: The file cannot be
  accessed by the system") was a stuck AF_UNIX socket reparse point from the
  interrupted first attempt; also cleared by the same reboot.
- **Tailscale Funnel needed enabling on the tailnet** (one-time, a link the
  owner had to open) before `tailscale funnel 8000` would take — first
  attempt errored "Funnel is not enabled on your tailnet."
- **Remote access researched, not yet set up.** The owner wants to both (a)
  keep directing this Claude Code session from a laptop, and (b) get full
  remote-desktop control of this PC's screen. For (a), Claude Code has a
  built-in `claude remote-control` — run on this desktop, gives a URL/QR code,
  log into the same Claude account from the laptop's browser or the mobile
  app. For (b), **Chrome Remote Desktop** was recommended (free, no
  port-forwarding, install on this PC + sign into Google, then
  remotedesktop.google.com/access from the laptop) but not installed this
  session — the owner had not yet confirmed they wanted it set up before this
  session's context turned to the coding work.

## Traps for next time

- **`WaterFact.lang` is nullable, not `NOT NULL DEFAULT 'en'`, on purpose.**
  `app/core/migrate.py`'s `add_missing_columns` only ever emits
  `ALTER TABLE ... ADD COLUMN <type>` with no `DEFAULT` clause. A `NOT NULL`
  column added that way fails outright against a SQLite table that already
  has rows — and `water_fact` already had rows on this machine by the time
  this column was added. If a real numbered migration ever replaces the
  additive-column mechanism (`docs/03-DATA-MODEL.md` still wants this before
  a real season), this is a natural moment to backfill `lang='en'` and make
  the column `NOT NULL` for real.
- **`_request_body`'s new `schema` parameter defaults to `RESPONSE_SCHEMA`.**
  Any *third* schema added later to this module must remember to pass it
  explicitly — the default silently reverting to the facts schema is exactly
  the bug this session found and fixed once already.
- **Running `pytest` directly on this machine now requires a venv that
  doesn't exist by default.** `python -m venv .venv && .venv/Scripts/pip
  install -r requirements-dev.txt` (Windows: `Scripts`, not `bin`). Python
  3.11 was on PATH, not the pinned 3.12; ran clean anyway, but do not assume
  that holds forever.
- **`docker compose exec` output does not appear in `docker compose logs`.**
  Cost some confusion while debugging the translation bug — a one-off
  `python -c "..."` run via `exec` is a separate process from the container's
  main uvicorn process, and anything it logs via the stdlib `logging` module
  goes nowhere unless the script calls `logging.basicConfig()` itself. Print,
  don't log, when debugging this way.
