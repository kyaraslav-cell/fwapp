# Handoff — 2026-08-24, a clean bug check, a branch scare that wasn't, and the Oracle runbook

Short session. Continues `2026-08-21-0945`. Three asks: check for bugs, merge
what needed merging, start on an Oracle Cloud path so the app can go on a URL
without the owner installing anything locally.

## State

Branch `claude/session-docs-cloud-options-v2dr65`, pushed. `origin/claude/
repository-edit-push-ggr229` (the project's default branch) already matches
it commit-for-commit — see Traps below for why that looked wrong for a
moment.

`make check` run for real in this session, from a clean venv (`python3.12 -m
venv .venv`, `pip install -r requirements-dev.txt`): ruff clean, `mypy
--strict` clean over the nine packages, **321/321 tests pass**. Also checked
by hand that every `.py` under `app/` and `tests/` is tracked by git (the
`app/media` bug from two sessions ago stayed fixed). No bugs found; nothing
changed in `app/`.

## Decisions, and why

**Tailscale Funnel replaces Caddy on the Oracle fallback.** `docs/10 §9`
originally said "Oracle Cloud, plus Caddy for HTTPS." Caddy needs a domain
pointed at the VM and a certificate to keep renewed; Funnel needs neither and
is already the chosen mechanism for the primary (owned-hardware) plan, so
using it on the Oracle VM too means the two deployment paths are identical
except for who owns the box — no new dependency, nothing to renew. Caddy is
kept as a documented appendix for anyone who already owns a domain and
prefers it. Written up in `docs/16-DEPLOY-ORACLE.md`, executable steps in
`tools/oracle_vm_setup.sh`.

**The security list opens port 22 only.** Funnel reaches the app over the
tailnet and Tailscale's own relay, not through the VM's public ingress rules,
so there is no reason to open 80/443/8000 to the internet at all — the
smallest correct firewall is the default one, SSH.

## What this session could not do

Provision anything. Creating the Oracle account needs a card for identity
verification and a browser; launching the VM and approving the Tailscale
device both need a human clicking through consoles. None of that is
scriptable from here, and nothing was invented or assumed working —
`docs/16` and the setup script are the runbook for a human (or a future
session with real credentials and a browser) to run, not a record of
anything actually deployed. This mirrors the standing gap in `docs/10 §6`:
Nominatim, Overpass, Open-Meteo and now Oracle/Tailscale are all still
**believed to work from a script**, never **observed** from this sandbox.

## Traps

- **The "5 commits stranded on a branch nobody merged" finding from the start
  of this session was a stale fetch, not a real problem.** `git diff
  origin/claude/repository-edit-push-ggr229...HEAD` was run against a local
  remote-tracking ref fetched at session start; by the time the same
  comparison was re-run with a fresh `git fetch`, the default branch had
  already caught up (something merged it between the two checks — most
  likely the previous session's own push landing after the ref was first
  read). **Re-fetch before trusting a stale-branch diagnosis** — a cached
  `origin/*` ref is a snapshot, not a live view, and this cost a wrong
  sentence in the reply to the owner before it was caught here.

## Next

1. A human runs `docs/16-DEPLOY-ORACLE.md` on a real Oracle account — the
   first real signal on whether Always Free ARM capacity is available in
   their region, whether `docker compose up -d --build` behaves the same on
   ARM as the `python:3.12-slim` image was implicitly tested on (amd64 in
   every sandbox so far), and whether Funnel needs the tailnet's HTTPS
   certificates flag turned on first.
2. Once that machine exists: `make preflight` from it is still the first
   thing that turns Nominatim/Overpass/Open-Meteo from "believed" to
   "observed" (`docs/10 §6`) — nothing has changed about that.
3. Everything else in `docs/10 §8`'s suggested-next-session list is
   untouched: fish icons, terrain/tree shelter, `name_ru`, numbered
   migrations, then the calibration loop.
