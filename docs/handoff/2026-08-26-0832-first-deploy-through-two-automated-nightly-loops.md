# Handoff — 2026-08-25 to 2026-08-26, the app's first real deploy through two working automated nightly loops

Long session, the one where the app stopped being sandbox-only. Continues
`2026-08-24-2152` and everything chained after it that day. By the end of
this session the app is live on the owner's own PC, two independent
unattended nightly jobs are confirmed firing on schedule, and a real second
user has started using it.

## State

Branch `claude/repository-edit-push-ggr229`, pushed through `ed18a5a`.
`make check` clean: ruff, `mypy --strict` on the required packages,
**347/347 tests pass**. Live at `https://dell.tailf99616.ts.net`
(Docker + Tailscale Funnel on the owner's Windows PC) and rebuilt/redeployed
after every fix in this session, so what's live matches what's on the
branch.

Two unattended jobs are both confirmed working **from a real unattended
fire**, not just a manual dry run:
- **Windows Task Scheduler**, task `FishlogNightlyAudit`, daily 02:00 local
  → `tools/nightly_audit.sh --public-only` against `127.0.0.1:8000`, commits
  a report to `reports/site_audit/` only when it finds something. Fired for
  real overnight 2026-08-26 02:00 and found nothing new (0 dead controls, 0
  console/network errors, 0 visual diffs, the same two already-known
  accessibility findings) - confirms last night's fixes hold.
- A **cloud Routine** ("Fishlog nightly bug triage," `0 3 * * *` UTC) that
  reads whatever's sitting directly under `reports/site_audit/` (not
  `archive/`), triages it against `CLAUDE.md`, fixes what's real, archives
  the report. Set up by a parallel session, not this one - see Traps.

## Decisions, and why

**Windows Task Scheduler, not crontab, for the nightly audit.** The
owner's deploy machine turned out to be native Windows (Git Bash/MSYS) -
`crontab` doesn't exist there at all, no cron daemon. Task Scheduler is the
direct equivalent; wired through a `.bat` wrapper calling Git Bash because
passing the nested-quoted bash command straight to `schtasks /Create`
mangled through PowerShell's argument parsing.

**Translation is a second Gemini call on the finished English list, never a
second research pass per language.** Three independent lookups (one per
language) could each find different sources and drift into showing
different claims in each language, with no way to tell real disagreement
from research variance. One collection, then one translate call per
language that only asks for wording, guarantees every language shows the
same claims from the same sources.

**`--muted-strong` added for interactive elements only; ~40 more
non-interactive `--muted` usages left alone, deliberately.** The audit
found real WCAG contrast failures site-wide, but `CLAUDE.md` rule 8
(pastel, minimal, "an instrument, not an app") is the owner's own written
design constraint, and raising contrast everywhere trades against it. Fixed
what a user has to be able to identify as clickable (language switcher,
sign-in, water-type filter); left section headers and table labels as an
explicit open question for the owner rather than a unilateral rewrite at
the end of a long session.

**The lake page's heat overlay is hidden before its own visual-diff
screenshot.** It's coloured from live wind/pressure by design, so diffing
it against a fixed baseline would flag real weather as a regression every
single night forever - exactly the kind of noise that gets an automated
check ignored. `audit_public_pages` now hides `.heat-overlay` first;
everything static in `#map-wrap` (shoreline, tiles, controls) is still
checked.

**Nothing about the real second user was touched.** See Broken/unfinished.

## Broken / unfinished

1. **A real second user's two fishing sessions were never ended.**
   `tsaranhelina5@gmail.com` ("Anhelina," registered 2026-08-24 20:33) added
   a real water (Glinianki Szczęśliwickie) and started two sessions, neither
   has `ended_at` set. Not touched - it's real user data, and ending a
   session on someone's behalf without being asked is not this session's
   call to make.
2. **The owner's own account added a second undocumented water**
   ("Łowisko Poniaty - Pod Lasem," 0.01 ha) the morning of 2026-08-25.
   Nobody has said whether that was deliberate testing or should be removed.
3. **~40 non-interactive `--muted` usages still fail WCAG AA contrast**
   (`docs/09-BACKLOG.md §20`). Deliberately left for the owner to decide
   between fixing everywhere or accepting the softer look outside
   interactive controls.
4. **`§19b`, weather provenance UI, is an open design question, not a
   build task.** Investigated the owner's Google-Weather discrepancy report
   and found no bug (coordinates, timezone, `temperature_2m` all correct) -
   likely just two different forecast models disagreeing normally. Whether
   to make the app's own provenance (source, run time, forecast-vs-observed)
   more visible is the owner's call.
5. Everything already long-standing and untouched this session: terrain/
   wind-shelter modelling (`§3`/`§8`), offline/service-worker support
   (still the single biggest gap per `docs/15 §A5`), the calibration loop
   (Phase 5 - genuinely blocked on there being logged sessions, which there
   now finally are, from the real second user).

## Traps

- **`_request_body()`'s `schema` parameter silently defaulted to the wrong
  schema.** The first live translation call paired the *translate* prompt
  with the *facts* `RESPONSE_SCHEMA` (a stale default), so Gemini
  obediently re-answered the original research question in Polish instead
  of translating the given English facts - no exception anywhere, just
  wrong output that looked plausible. Only caught by dumping the raw API
  response text and reading it, not by any test. Any *third* schema added
  to that module later must pass it explicitly.
- **`app.web.app`'s module-level `app = create_app()` reads the real
  `.env` at pytest's *collection* phase**, before any fixture runs - a test
  doing `monkeypatch.delenv(...)` to simulate "not configured" was already
  too late the moment a real `.env` existed on the machine. Fixed with
  `tests/conftest.py` reassigning `app.core.env.ENV_FILE` at *module* level
  (not inside a fixture), so it lands before the first test module imports
  `app.web.app`.
- **The in-session browser tool (`mcp__Claude_Browser`) blocks
  `/static/style.css` and same-origin `fetch()` calls like `/grid` with
  `net::ERR_BLOCKED_BY_CLIENT`** - confirmed server-side with a plain
  `curl` that both serve fine; it's the tool's own sandbox, not the app.
  Workaround used twice this session: pull the real data/CSS with `curl`,
  then either inject it directly via `document.head.appendChild` (for CSS)
  or run a `python -m http.server` on localhost and navigate the pane there
  instead of `file://` (which renders as an inert static snapshot,
  JS never runs, for files both inside and outside the project folder).
- **Git Bash mangles `/Flag`-style arguments to native Windows tools**
  (`schtasks /Query` became a bogus path). Use the PowerShell tool for
  `schtasks` and friends, not Bash.
- **A script's own safety guard can wedge itself.** `nightly_audit.sh`
  refuses to run against an unclean git tree - correct - but the script
  only ever `git add`s the report file, not a newly-written baseline image.
  The very first run against a page with no baseline left the tree dirty,
  which would have silently blocked every run after it. Committed the
  missing baseline by hand; the script itself should probably `git add
  tools/baselines/*.png` too.
- **Multiple sessions/branches are actively working this same repo in
  parallel.** Twice this session, real finished work (an auth security fix,
  the overlay-rendering bug fix, the whole site-audit tool) showed up on
  `claude/project-status-review-xtzib7` without this session having started
  it. Always `git fetch` and check that branch - not just the default
  branch's own history - before assuming you have the full picture. Merge
  and push per rule 13; don't just read and move on.

## Verified vs assumed

**Verified live, not just by test suite:**
- Gemini and Google OAuth, both reaching the real APIs.
- Translated/trimmed local knowledge, in all three languages, against a
  real added water.
- Lake thumbnail icons - actual screenshot, two real lakes, visibly
  distinct shapes.
- `§19c`'s hi-res grid - the data pipeline (real job run, real endpoint
  behaviour, real scheduler registration) *and*, after finding the overlay
  render was actually broken (see below), the pixel-level render itself,
  worked around the browser-tool block by running the exact fixed
  rendering code against real curled data.
- The nightly audit job - twice: once by hand, once through the real
  Task Scheduler mechanism, and now once more from an actual unattended
  2am fire.
- The viewport and colour-contrast a11y fixes - by rendering, per
  `CLAUDE.md`'s own rule, not by reading the diff.

**Verified, then found broken, then re-verified:** the `§19c` heat overlay
initially reported as "data-verified" was not actually looked at by this
session and turned out to have a real, visible bug (garbled/streaked
rendering from a coarse-vs-hi-res grid geometry mismatch) - caught by the
owner looking at the real page, fixed on a parallel branch, merged and
confirmed here. The lesson generalises past this one bug: **a green test
suite and a correct-looking data check are not the same claim as "someone
looked at the pixels."**

**Assumed, not verified:** the human half of the Google OAuth
consent screen click-through - needs the owner's own browser and Google
account, not something this session's tools can drive.

## Next

1. **Answer the three pending owner decisions** (session heading above) -
   nothing else is currently blocked, but these are the only open threads
   left from this session's own work.
2. If the owner wants the broader contrast pass, it needs the same
   render-and-look discipline as everything else here - don't blind
   find-replace all ~40 `--muted` usages without checking each context.
3. Otherwise the backlog is in a genuinely clean state for the first time
   this project has had one: `§19a`/`§19c`/`§20` done and live-verified,
   `§19b` is a design question waiting on the owner, and the two automated
   nightly loops are watching for regressions on their own. The next
   *build* item, when the owner is ready to pick one, is either the
   terrain/shelter gap (`§3`/`§8`, the largest scoring gap) or offline
   support (`docs/15 §A5`, the largest gap full stop) - both need an ADR
   before code, per their own backlog entries.
