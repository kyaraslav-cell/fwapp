# Handoff — 2026-08-19, accounts, the day strip, and the add-a-water backbone

## State

Branch `claude/switch-button-commercial-design-385m7c`, merged into the default
branch `claude/repository-edit-push-ggr229` after every change and pushed. The
Pages workflow rebuilt green on the first of those merges.

`make check` green: ruff, `mypy --strict` over 40 files (the strict list grew to
`app/core app/rules app/features app/auth app/jobs app/discover app/geo`), 204
tests — 109 at the start of the session.

Five things shipped, in order: the water-type segmented switch, accounts and
sign-in, the day strip behind a calendar icon, its follow-up round, and the
add-a-water backbone.

## Decisions, and why

**The band label is looked up from the colour, not stored per language.** The
day-quality label ("Fair") lives in an immutable `prediction` row, so it cannot
be rewritten when the language changes. The colour is the stable identity — it
is what law-2 immutability protects and what the owner's "colour band only" rule
already treats as the meaning — so `band.yellow` is the key and the English
label in the ruleset is now only a fallback.

**scrypt from the standard library, not passlib/bcrypt/argon2.** Memory-hard, no
dependency for one function, and the cost parameters live *inside* the hash
string so raising them later leaves old passwords verifiable. Measured ~0.5 s to
verify on the build machine. **If this ends up on a Pi, drop to n=2¹⁶ with p=2**
rather than accept a three-second login.

**Server-side sessions, only the hash stored.** A signed cookie cannot be
revoked, and `docs/05` tells the owner their backup strategy is copying the
SQLite file — a database full of usable session tokens would make every backup a
set of keys.

**Google joins on `sub`, never on email.** Addresses get recycled; the subject
does not. Matching on email hands a stranger somebody's notebook the day an
address is reissued.

**The security boundary is read vs. notebook, not page vs. page.** The lake, the
weather and the map stay public; history, sessions and catches need an account.
Enforced in one place (the router includes in `app/web/app.py`) because a
boundary spread across five decorators is one that gets forgotten on the sixth.
It is also exactly what keeps `tools/build_static.py` working unchanged.

**CPUE is scoped per angler.** Pooling two anglers' fish per hour is not a
better-sampled CPUE, it is a different measurement — skill varies more than the
weather does. Same reasoning `water_type.py` already applies to PZW vs
commercial.

**No percentage on the calendar.** The owner asked for "chances of catching".
That is a calibrated probability and there is nothing to calibrate against — zero
logged sessions. The colour band is what the engine honestly produces. When
phase 5 has a season behind it, the strip is where the percentage goes.

**The day-strip explanation reads the ruleset, it does not repeat it.**
`regime_rating()` ranks the day's pressure regime among the ruleset's own
`regime_scores` at render time. An i18n string saying "falling pressure is best"
would be a second, silent copy of a law-1 rule and the wrong one the day the
owner's formula lands. A test inverts the weights and asserts the sentence
inverts with them.

**Named waters only for add-a-water.** PZW waters and commercial fisheries are
all named — that is the entire target set. This deletes the raster auto-tracing
branch and its numpy + GeoTIFF dependencies from the MVP entirely.

**No circle fallback for a discovered water.** The existing fallback was a fair
hedge for one lake whose polygon we had checked by eye. Generalised it is a lie:
18 corners that are not the lake, fetch computed across water that does not
exist, and an overlay as confident as a real one. No polygon now means satellite
map, pin, weather, forecast — and no overlay, with the page saying why.

**Grid resolution follows area.** The binding constraint is the JSON handed to a
phone (per wind bucket, on every day tap), not CPU. Targets ~5 000 cells.

## Broken / unfinished

1. **The Gemini pass is not built.** The pipeline slot exists; the handler does
   not. It supplies *facts only* — species, bottom, access, rules — never formula
   weights (ADR 0005 §2).
2. **Login rate limiting does not exist.** scrypt makes each attempt cost ~0.5 s
   of CPU, and that is the whole mitigation. **Build it before this is on a
   public URL.**
3. **No password reset.** Needs an SMTP credential and a sending domain. Until
   then the recovery path is the owner's own database.
4. **A future day's overlay uses that day's forecast wind with *today's*
   modelled water temperature and oxygen.** There is no forward water-temp run.
   The UI only ever claims wind.
5. Everything already in `docs/10 §5` — fish icons half redrawn, terrain shelter
   missing, no real migrations, zones are demo wedges, calibration loop unbuilt.

## Traps

- **`Params` with plain dataclass defaults cannot be monkeypatched.** The scrypt
  cost is read through `default_factory` precisely so the test suite can drop the
  work factor for the whole run instead of threading a cost parameter through
  every call.
- **`fetch_osm_outline` returned `None` for two different things** — Overpass
  unreachable, and Overpass answering "nothing here". A live run caught it: one
  timeout would have marked a mapped lake as unmapped until the monthly refresh.
  Now split into a strict variant that raises.
- **A 50 m cell cap does not solve the payload problem.** A test proved a
  Śniardwy-sized water still sends 40 000 cells. The cap is 150 m — the same
  fraction of that lake as 5 m is of Pomocnia.
- **Leaflet's CDN is unreachable from the sandbox**, so `#map-wrap` hides itself
  and any Playwright check touching the map silently measures nothing. Drive the
  map with a stub Leaflet (see this session's scratch approach) or you are
  testing a hidden element.
- **`wait_until="load"` never fires here** — Google Fonts is blocked, so page
  loads hang. Use `domcontentloaded`.
- **A YAML value containing `: ` must be quoted.** The Russian calendar note
  broke the whole catalogue until it was.
- **The i18n catalogue is cached per process.** New keys need a server restart,
  not just a page reload — this cost two rounds of "why is the key showing".

## Verified vs assumed

**Observed working:** the switch and its slide (filmstrip); the auth screens in
three languages, including client-side validation, a rejected sign-in and the
redirect out of `/history`; the day strip rolling, selecting, recolouring and
resetting on outside-tap; the add-a-water flow end to end with only the geocoder
stubbed, and its four jobs running to completion in order against the real
queue; the static Pages build after every structural change.

**Believed, never observed:** every outbound call. Nominatim, Overpass, Google's
OAuth token exchange, Open-Meteo, Esri tiles, Leaflet. This sandbox reaches no
external host (`docs/10 §6`), so all of it is tested to the boundary against
fakes and fails closed. The first real search, the first real sign-in with
Google and the first real overlay repaint all happen on the owner's machine.

## Next

1. **Run the add flow for real**, once, on a machine with network. Watch
   `outline_source` on the new water: `osm` means the whole chain worked;
   `none` means Overpass answered and that water has no polygon; a failed job on
   the page means the service was down. `docs/13 §8` is the table of what each
   failure should look like.
2. **Then the Gemini handler.** New job kind in `app/jobs/handlers.py`, a client
   that fails closed with no API key exactly as `app/auth/google.py` does, strict
   JSON out, every field carrying a source URL, stored in its own table — never
   in `weather_hourly` or any `derived_*` table (law 4).
3. **Login rate limiting** before any of this is publicly reachable.
