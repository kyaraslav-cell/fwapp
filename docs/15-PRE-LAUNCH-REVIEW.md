# 15 — Pre-launch review: what to fix, and what to build next

Written 2026-08-19, before the app goes on a real machine. Two halves:
**A** is what an experienced reviewer would refuse to launch without, found by
reading this codebase rather than from a generic checklist. **B** is where the
product could go, judged against what anglers actually do at a lake.

Nothing here is built yet. Each item names its cost honestly.

---

## A. Before the machine

Ordered by what hurts soonest. The first four are small; the fifth is the one
that changes the product.

### A1. No security headers at all · **DONE** — `app/web/security.py`

`grep -rn "Content-Security-Policy" app/` returns nothing. On a public URL that
means:

- **No CSP.** The lake page loads Leaflet from `unpkg.com` and tiles from Esri.
  Any XSS — a species name, a lake name from Nominatim, a Gemini fact — becomes
  script execution. The collected-facts section renders text from a *language
  model* citing *arbitrary web pages*; that is precisely the input a CSP exists
  for. Jinja autoescaping is the first defence, CSP is the one that holds when
  autoescaping is bypassed once.
- **No `X-Content-Type-Options: nosniff`.** `/media` serves angler-uploaded
  files from the app's own origin. A file sniffed as HTML runs as HTML on the
  origin that holds the session cookie.
- **No `X-Frame-Options` / `frame-ancestors`.** Clickjacking on "End session".
- **No HSTS.** Behind Tailscale funnel it is https-only anyway, but the header
  is what stops the first plain-http request.

One middleware in `app/web/app.py`. The only real work is writing a CSP that
does not break Leaflet and the inline scripts already in the templates —
which is itself worth knowing before launch, not after.

### A2. Uploaded photos are stored whole, with their EXIF · ~40 lines

`app/web/routes/sessions.py` caps at 8 MB and writes the file as it arrives.
Two consequences:

- **The database backup strategy is "copy the file" (`docs/05`), but photos are
  not in the database** — they are in `media/`, which is a second thing to back
  up and is easy to forget. Worse, at 3–5 MB per phone photo, a season of
  catches is gigabytes on a Pi's SD card.
- **EXIF is preserved, including GPS.** Every catch photo carries the exact
  coordinates it was taken at. Today the notebook is private, so the exposure is
  limited — but the moment anything is shared (see B4), every shared photo
  publishes a swim to the metre. Anglers guard their spots; this is the kind of
  detail that loses trust permanently.

Downscale to ~1600 px on the long edge and strip EXIF on write. Keeps the
photo useful for identification, drops the size by ~10×, removes the leak.
Needs Pillow — a new dependency, so an ADR first (`CLAUDE.md` stack rules).

### A3. `list_sessions` runs one query per session · **DONE**

`app/notebook/sessions.py:151` selects the sessions, then line 163 selects that
session's catches **inside the loop**. A season of 200 sessions is 201 queries
per history page. SQLite on a local disk will survive it; it is still the
textbook N+1, and it is one `GROUP BY` to fix.

While there: **no index on `session.user_id`, `catch.session_id`, or
`session_leg.session_id`.** SQLite does not index foreign keys automatically.
Every history page is a full scan of both tables today. Three `Index(...)`
lines.

### A4. No `/health`, no 404 page, no 500 page · **DONE**

- **`/health` is required by `docs/05`** and does not exist. It should expose
  the last successful ingest time, because a silently dead ingest serves
  yesterday's predictions as today's and *nothing on the page says so*. That is
  the failure mode of an unattended app: not a crash, a quiet lie.
- **A 404 or an unhandled 500 currently renders FastAPI's JSON**, on a phone, in
  the rain. Two small templates.

### A5. The app does not work without a signal — and that is where it is used

This is the largest gap in the product, not just the code.

There is no service worker, no manifest, no offline anything
(`ls app/web/static/` is one CSS file). Jezioro Pomocnia is near Pomiechówek;
plenty of PZW waters have no usable data at the bank at all. Today, at the
water's edge with one bar:

- the lake page will not load;
- an active session cannot be advanced;
- **a caught fish cannot be logged.**

`docs/07-UI-SPEC.md` sets the target at ~2 seconds per fish, one thumb, wet
hands. That target is unreachable over a dead connection, and the standing rule
"conditions and map must stay reachable during an active session"
(`docs/10 §2` rule 10) is not actually satisfiable today.

The fix is genuinely large and genuinely worth it:

1. a **service worker** caching the app shell, the current lake page, its
   outline and the day's grid;
2. an **outbox** — catches logged offline queue in IndexedDB and post when the
   signal returns, each carrying **its own real timestamp** so law 2 and the
   CPUE arithmetic stay honest. A catch logged at 06:12 and synced at 14:00 is
   a 06:12 catch;
3. an idempotency key per queued write, so a retry cannot double-log a fish.

This does not break ADR 0001. A service worker is not a build step and not an
SPA framework — it is one static JS file served from `/static`. It does need
an ADR of its own, because an outbox introduces a second source of truth for a
short while, and that deserves to be written down before it is written.

---

## B. Where the product goes

Judged on one question: what would make an angler open this instead of
Windguru, and open it again next week?

### B1. "We said Fair. You caught 1.8 fish an hour." · the actual differentiator

Phase 5 in the roadmap, and it is the whole reason this project exists — but it
is also the *marketing*. Every fishing app predicts. **None of them shows you
whether it was right.**

A past day in the day strip, showing the band that was written before the
session beside the CPUE that was actually logged, is a screen no competitor has,
because no competitor stores an immutable prediction (law 2) to compare against.
It turns the app's honesty into its selling point.

Needs a season of logged sessions first. Costs nothing to design now, and the
data model already supports it — which is exactly what law 2 bought.

### B2. Let the angler mark their own water · the highest-value input the app lacks

`docs/09 §11` is blunt about it: every spatial input the score has is
distance-to-shore or fetch, so on a convex bowl the overlay can only ever be
rings and a gradient. Weed edges, drop-offs, snags, the gravel bar — none of it
is anywhere.

Ten minutes of one angler drawing on their own lake adds more spatial
information than any further weather modelling. As a feature it is also the
stickiest thing you can build: **your marks are yours**, and an angler who has
mapped their water will not move to another app.

It respects the laws cleanly — a marked weed edge is an *observation*, not a
fishing heuristic, so it belongs in the database while the weight given to it
stays in the YAML.

### B3. Is this fish legal, right now? · the question anglers actually ask

`docs/09 §12` records that closed seasons and size limits are **not** encoded —
"per okręg, needs research". In Poland that is a real, recurring, slightly
anxious question at the bank: pike in spring, zander size, the okręg's own
rules, and a fine if you get it wrong.

The app already knows the species, the length, the date and the water. It is one
YAML table per okręg away from answering "you may not keep that" at the moment
of logging — which is a genuine, defensible reason to have the phone out.

Strictly facts, strictly in YAML (law 1), and it must say **which regulation and
from when**, because a wrong legal answer is worse than none.

### B4. A session card worth sending to a mate · the growth loop

Angling spreads by WhatsApp group. A single rendered image — water, date,
conditions, the colour band, CPUE and the sample size — is one share button and
a template, and it is how apps like this actually spread in this sector.

Two constraints, both already project law: **sample size travels with the
number** (law 5), so a card from three sessions must not look like a card from
ninety; and it must **strip location** unless the angler explicitly opts in
(see A2 — this is why EXIF matters before sharing exists, not after).

### B5. Export your own log · cheap trust

There is no export route anywhere (`grep -rn "csv\|export" app/web/routes/`
finds nothing). Anglers are rightly suspicious of apps that trap a season of
records. One CSV endpoint is an afternoon and removes an objection permanently.

Also the honest hedge against A2's other half: an export means the notebook
survives even if the machine does not.

### B6. Two smaller ones

- **Moon phase.** Widely believed to matter, cheaply computed, already
  half-present via `app/features/solar.py`. Must go in the ruleset as a term
  with `provenance: ai_authored_provisional` like the zone score — never as a
  number in code (law 1). Its real value is that anglers *look for it*, and its
  absence reads as a missing feature.
- **A "conditions changed" nudge.** The engine already writes predictions daily;
  a push when tomorrow's band improves to green is the one notification an
  angler would keep switched on. Needs the app on a URL and a web-push key
  first.

---

## Recommended order

1. **A1, A3, A4** — a day's work between them, and all three are things that get
   harder to add once there is real traffic and real data.
2. **A2** — before any photo is shared anywhere.
3. **B5** — an afternoon, and it makes the season's data portable before the
   season starts.
4. **A5, the offline half** — the biggest piece here, and the one that decides
   whether the app is usable where it is meant to be used. ADR first.
5. **B2** — after offline, because marking a lake at the bank is itself an
   offline activity.
6. **B1** — when there is a season behind it. Design it now, ship it then.

B3 and B4 are the two that would most obviously attract a stranger; both are
worth doing once the app is reliably reachable, and neither is worth doing
before A5.

---

## What A1, A3 and A4 turned into

**A1.** `app/web/security.py`, applied by the outermost middleware in
`app/web/app.py` so that the responses which skip the router — a 404, a static
file, an unhandled exception — are covered too. Those are precisely the ones
that would otherwise go out bare.

Verified by loading the home page, the lake page, login and register in a real
browser under the real policy: **zero CSP violations**, and the inline map and
day-strip scripts ran. One honest gap: the sandbox blocks unpkg.com, so
`script-src https://unpkg.com` was never exercised against a Leaflet that
actually loaded. The first real page load on the owner's machine confirms it —
if the map is blank and the console says "Refused to load", that line is why.

`'unsafe-inline'` for scripts remains the weak point and is documented as such
in the module. Removing it means nonces through every template, or moving the
inline blocks into `/static`. Worth doing; it was not worth blocking on.

**A3.** One grouped `SELECT ... GROUP BY session_id` replaces the per-session
query. The test counts queries rather than timing them — a timing assertion
passes on a fast machine with the bug still in place — and asserts a bounded
count for twelve sessions, half of them blank. **Blank sessions still appear,
with a real zero** (law 3): they have no row in the grouped result, so the
lookup defaults rather than skipping.

Three indexes added, and `create_missing_indexes` in `app/core/migrate.py` to
go with them — because `create_all` skips a table that already exists **and
skips its indexes with it**, so without it every index added from now on would
reach fresh installs only, and the owner's own database, the one with the
season in it, would keep scanning forever.

**A4.** `/health` reports `ok` / `stale` / `unknown` and answers **503 for
anything but ok** — a monitor that checks the status code, which is most of
them, must not see green while the app serves last week's forecast. It reads
the database rather than calling Open-Meteo: a healthcheck that fails when
Open-Meteo is briefly slow pages somebody at 3 a.m. for nothing.

404 and 500 now render a page in the angler's own language with one button
back; HTMX and JSON requests still get JSON, because swapping an error page
into a fragment of a working page looks broken in a much more confusing way.
Rendered in all three languages and looked at.

Still open from this document: **A2** (photo downscale and EXIF strip),
**A5** (offline), and all of part B.
