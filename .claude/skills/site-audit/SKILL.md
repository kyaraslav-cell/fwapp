---
name: site-audit
description: Drive the real app through its core angler flow in a real browser and report dead controls, console/JS errors, failed requests, visual regressions and accessibility violations - then triage each finding against CLAUDE.md and the docs, not against taste. Use when the owner asks for a bug sweep, a UX/design check, a pre-deploy sanity check, or says "run the audit" / "check for bugs" / "does anything look broken". Also use after any change that touches a template, a route the angler clicks through, or client-side JS.
---

# Site audit — an independent bug/UX sweep

`tools/site_audit.py` is the tool behind this skill: Playwright drives a real
browser through registration, the home page, the lake map, picking a spot,
starting a session and logging a catch, and reports anything a diff or a
green test suite cannot see - a button wired to nothing, a JS exception, a
failed request, a page that no longer matches its last-approved screenshot,
an accessibility violation. `axe-core-python` (accessibility) and Pillow
(screenshot diffing) do the rest. No LLM in the loop, no third-party
service, no API key - every run costs compute, not credits, and nothing the
app renders ever leaves the machine it runs on.

Full research and the decision behind this choice: `docs/09-BACKLOG.md §20`.
The short version: paid AI-QA SaaS (Percy, Applitools, testRigor, BugBug,
Autify...) either cost money past a small free tier, or need the app
reachable from their infrastructure, or both - wrong fit for a self-hosted
single-lake app behind a Tailscale funnel. AI browser agents (Skyvern,
Stagehand, browser-use) call an LLM on every navigation decision, which is
the opposite of "lightweight and won't spend credits" for a fixed,
well-understood set of pages. A deterministic Playwright script, written
once, is free per run.

## Two modes - and which database each one is safe against

`--public-only` skips registration and the session/catch flow, running only
the read-only checks (dead controls, console/network errors, a11y, visual
diffs) against the public home and lake pages
(`docs/adr/0004`: "the lake, the weather and the map stay public"). Nothing
in that mode writes a row.

The full flow additionally registers a throwaway angler, picks a spot,
starts a session and logs a catch - real writes. **Only ever point the full
flow at a throwaway database.** Against a real deployment's real database it
would fabricate a fake angler's fake catch into the real notebook every
time it runs, which is exactly what CLAUDE.md law 3 (CPUE integrity, never
fabricate an observation) exists to prevent. This was caught before it ever
ran against production - see docs/09-BACKLOG.md §20.

## Where this can actually run

Only a machine with real network access to the target sees anything real:

- **The nightly cron job, against the real deployment** -
  `tools/nightly_audit.sh`, `--public-only`, over `http://127.0.0.1:8000`
  (localhost, not the Tailscale funnel - the script runs on the same
  machine as the container, per the owner's explicit choice: this lives in
  cron on that machine, not as a Claude Code Remote schedule, because this
  cloud sandbox cannot reach that machine's network at all - confirmed, the
  outbound proxy returns a policy 403 for the Tailscale host). Commits
  `reports/site_audit/<date>.md` and pushes only when it finds something;
  a clean night is silent. Setup is in the script's own header comment.
- **The full flow, on demand** - the owner's machine or a local Claude Code
  session there, against either a throwaway local instance or (accepting
  the write risk deliberately, e.g. to test the real registration/session
  pipeline once) the real deployment.
- **Against a fresh local instance** - runs anywhere, including this cloud
  sandbox, using a throwaway SQLite DB and the seeded Pomocnia lake
  (`app/core/seed.py` - no network fetch needed). This is the cheap
  pre-flight check: run it here before ever asking the owner to redeploy,
  the same spirit as running `make check` before pushing.

```bash
# One-time per machine that lacks /opt/pw-browsers (i.e. not this sandbox):
.venv/bin/playwright install chromium

# Fresh local instance, full flow (writes are fine - it's a scratch DB):
rm -f /tmp/audit.db*
FISHLOG_DB_PATH=/tmp/audit.db .venv/bin/uvicorn app.web.app:app --port 8090 &
.venv/bin/python tools/site_audit.py --base-url http://127.0.0.1:8090

# The real deployment, read-only, from a machine on the tailnet or the host
# itself (what tools/nightly_audit.sh actually runs):
.venv/bin/python tools/site_audit.py --base-url http://127.0.0.1:8000 \
  --public-only
```

## Triage rule — this is the point of the skill, not just the script

The script finds candidates. Judging *whether a finding is actually a bug*
happens against **the owner's own written requirements**, never against
model taste:

1. Read `CLAUDE.md` (the five laws, the standing rules in §2 of
   `docs/10-SESSION-HANDOVER.md`, the pastel/minimal design rule, "one
   sentence under a control") and `docs/07-UI-SPEC.md` before judging
   anything the report flags.
2. For each finding, decide: **real bug** (fix it), **intentional and
   already documented** (e.g. a control that is a no-op by design - note why
   and move on), or **unclear** (put it to the owner rather than guessing -
   `AskUserQuestion` or a short question in the reply, per CLAUDE.md's own
   "do not invent the formulas" spirit: do not invent the requirement
   either).
3. A finding outside this tool's reach - concurrent sessions, rate limiting,
   anything about *whether* two things are allowed to happen at once rather
   than *how a page renders* - is a behavioural question, not a browser-QA
   one. Write it as a `pytest` test against the real routes instead of
   trying to make this tool catch it - see
   `tests/test_auth_routes.py::test_a_new_sign_in_revokes_the_previous_one`
   for exactly this shape: the owner answered "should concurrent login from
   different locations be allowed?" with "no" (2026-08-25), and that became
   a fix in `app/auth/service.py` plus that test, not anything in
   `tools/site_audit.py`.
4. Fix what's clearly a bug, then **re-run the audit** to confirm - per
   CLAUDE.md's verification rule, a fix is not "done" until it is rendered
   again and looked at, not just reasoned about.

## Baselines

`tools/baselines/*.png` are committed to the repo, the same convention as
`tools/icon_sheet.py --compare`: a visual change shows up in the diff of a
PR, not just in a script's stdout. First run (or after a *deliberate*
redesign) needs `--update-baselines` to write them; every other run compares
against what's committed and flags real drift.

## Extending the flow

`tools/site_audit.py`'s `run()` function is one linear script, not a
framework - add a step by navigating and calling `scan_dead_controls` /
`scan_a11y` / `screenshot_and_diff` at the point in the flow a new page or
control appears, the same shape as the steps already there. Keep it
deterministic; resist the pull to make it "smarter" by adding an LLM call
into the loop, which is exactly the cost this was built to avoid.

## Scheduling — two stages, split by what each side can actually reach

**Finding** happens on the owner's machine, in cron, because that is the
only place with real network to the real app - a Claude Code Remote Routine
fired from this cloud sandbox's environment cannot reach it (confirmed: the
outbound proxy returns a policy 403 for the Tailscale host), so a
cloud-scheduled *finder* could only ever repeat the degraded smoke-test
path. `tools/nightly_audit.sh` in the host's own cron (2026-08-25) runs
`--public-only` against `http://127.0.0.1:8000` and, only when it finds
something, commits `reports/site_audit/<date>.md` and pushes it - straight
to disk, no LLM involved, so this half costs compute, not credits.

**Fixing** does not need that network - it needs git and the ability to
read and edit code, which this cloud environment already has. So a second,
separate Claude Code Remote Routine ("Fishlog nightly bug triage",
2026-08-25) fires a few hours after the local cron would have run, pulls
the branch, and looks for exactly one thing: any file directly under
`reports/site_audit/` (not `reports/site_audit/archive/`). That is the
whole signal - a file sitting there un-archived means "found last night,
not yet triaged."

For each one it finds, the fired session follows the triage rule above:
fix what is clearly a bug (small, unambiguous, zero design impact - the
same bar as the viewport-meta fix, 2026-08-25), confirm with `make check`,
push straight to `claude/repository-edit-push-ggr229`. For anything
ambiguous, it does not guess - it writes its conclusion into the report
file itself and leaves the decision for the owner. Either way, once a
report has been looked at, `git mv` it into `reports/site_audit/archive/`
as part of the same commit, so the same finding is never triaged twice and
an empty `reports/site_audit/` (ignoring `archive/`) always means "nothing
outstanding." A run that finds no un-archived reports does nothing and
stays quiet - `notifications: {push: true}` on that Routine means the
owner's phone only hears about it when something was actually fixed or
needs a decision.

This is the actual closed loop: cron finds it for free with real network,
a scheduled session fixes it for free (no network needed, just git) with
the same triage discipline a human-requested run would use, and the owner
only ever sees a push notification when there is something to act on -
never a report to go read commands off of.
