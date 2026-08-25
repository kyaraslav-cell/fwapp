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

Full research and the decision behind this choice:
`docs/handoff/` (dated entry, "site audit tooling"). The short version: paid
AI-QA SaaS (Percy, Applitools, testRigor, BugBug, Autify...) either cost
money past a small free tier, or need the app reachable from their
infrastructure, or both - wrong fit for a self-hosted single-lake app behind
a Tailscale funnel. AI browser agents (Skyvern, Stagehand, browser-use) call
an LLM on every navigation decision, which is the opposite of "lightweight
and won't spend credits" for a fixed, well-understood set of pages. A
deterministic Playwright script, written once, is free per run.

## Where this can actually run

Only a machine with real network access to the target sees anything real:

- **Against the real deployment** (`https://dell.tailf99616.ts.net` or
  whatever the current Tailscale host is) - only from the owner's machine,
  or a local Claude Code session running there. This cloud sandbox cannot
  reach it (confirmed: the outbound proxy returns a policy 403 for that
  host).
- **Against a fresh local instance** - runs anywhere, including this cloud
  sandbox, using a throwaway SQLite DB and the seeded Pomocnia lake
  (`app/core/seed.py` - no network fetch needed). This is the cheap
  pre-flight check: run it here before ever asking the owner to redeploy,
  the same spirit as running `make check` before pushing.

```bash
# One-time per machine that lacks /opt/pw-browsers (i.e. not this sandbox):
.venv/bin/playwright install chromium

# Fresh local instance:
rm -f /tmp/audit.db*
FISHLOG_DB_PATH=/tmp/audit.db .venv/bin/uvicorn app.web.app:app --port 8090 &
.venv/bin/python tools/site_audit.py --base-url http://127.0.0.1:8090

# The owner's real deployment, from a machine on the tailnet:
.venv/bin/python tools/site_audit.py --base-url https://dell.tailf99616.ts.net \
  --lake zalew-zegrzynski
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
3. A finding outside this tool's reach - concurrent sessions from different
   locations, rate limiting, anything about *whether* two things are allowed
   to happen at once rather than *how a page renders* - is a behavioural
   question, not a browser-QA one. Write it as a `pytest` test against the
   real routes (see `tests/test_auth_routes.py`, `tests/test_throttle.py`
   for the existing pattern) instead of trying to make this tool catch it.
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

## Not yet wired to a schedule

Deliberately manual for now (per the owner, 2026-08-25) - no cron, no
milestone trigger. When that's decided, `create_trigger` /
`ScheduleWakeup`/`loop` can fire this skill on a cadence or after a deploy;
until then, run it on request or before/after a change that touches
templates, routes an angler clicks through, or client-side JS.
