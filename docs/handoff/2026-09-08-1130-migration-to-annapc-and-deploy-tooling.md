# Handoff — 2026-09-08, Fishlog moved off the laptop onto annapc, and the tooling that got it there

## State

Branch `claude/repository-edit-push-ggr229`, pushed through `8944d49`.
ruff clean, `mypy --strict` clean, **512 passed / 10 skipped**.

**Live at `https://annapc.tailf99616.ts.net`** — the app now runs on a
stationary PC, not the DELL laptop. The laptop's container is stopped and its
funnel still points at it, so `https://dell.tailf99616.ts.net` returns **502**
and should be switched off.

**The live site is one commit behind the branch.** Everything through
`ecb1175` is deployed; the last commit (`8944d49`, three retired colours in
templates) is not. Confirmed by reading the served HTML: annapc still sends
`theme-color: #eef4f4` and the old reed-green fish pin. See **Next**.

Migration verified by row counts matching the source exactly: 2 users, 9 waters,
11 catches, 8 sessions, 77 232 weather rows, 8 angler_lake.

## Decisions, and why

**The stationary PC, not a cloud VM.** The owner asked for "off grid of this
laptop". A VM is only for when no owned machine can stay powered on. They have
one, so the Oracle path in `docs/16` stays a fallback — it costs an account, a
card check and a browser signup for nothing.

**The bundle is found, never made.** `bootstrap.ps1` and `install.ps1` both
search every drive root, Downloads and the home folder for
`fishlog-bundle-*.zip` and take the newest. This is the LeadFind lesson applied:
over there every attempt began by rebuilding and redeploying, so when a result
looked wrong nobody could tell whether the fix was bad or the deploy had simply
replaced nothing. One bundle, reused, deletes that ambiguity — and the wait.

**Re-running is the normal path, not the exception.** A clean Windows machine
needs two restarts (WSL2, then Docker), so the bootstrap is re-run two or three
times by design. Every step detects what is already done and skips it, and the
restore refuses to overwrite an existing notebook without `-Force`. A bootstrap
that eats data on the second run is worse than one needing five commands.

**The pack snapshots through SQLite's backup API, not a file copy.** WAL mode
keeps the newest writes in the sidecar; copying the `.db` alone loses them
silently. `.backup()` folds the WAL in and yields one self-contained file.

**`check.ps1` asks whether the container runs *this* code**, by hashing every
file under `app/` and `config/` inside the container against the working tree.
Lifted from LeadFind's worst bug — n8n reported workflows "published and in
sync" while running days-old code. Fishlog's image holds a frozen copy of
`app/`, so the same lie is available here.

**Warn, don't fail, on an empty notebook.** Empty is correct on a first install
and catastrophic after a migration; the script cannot tell which, so it says so
loudly and leaves the judgement to the reader.

**The commit check only warns when the checkout is *behind*.** Migrations are
forward-only, so ahead is fine and is the normal state after a pull. Warning on
the safe direction is how warnings get ignored in the case that matters.

## Broken / unfinished

- **The live site is a commit behind** (see State and Next).
- **`FISHLOG_TRUST_PROXY=1` is correct now** the funnel is on, but it was set
  while the app was localhost-only, which meant `X-Forwarded-For` was trusted
  from any client and per-IP rate limiting could be bypassed. Fine as it stands.
- **Google sign-in on annapc will fail** until
  `https://annapc.tailf99616.ts.net/auth/google/callback` is added in the Google
  console. `.env` was rewritten automatically; the console is manual and there
  is no API for it. Email/password is unaffected.
- **The old funnel on the laptop still serves 502.** Turn it off:
  `& "C:\Program Files\Tailscale\tailscale.exe" funnel --bg off`
- **Health monitoring is not wired.** `tools/heartbeat.sh` + a systemd timer
  exist for the Linux/VM path. annapc is Windows and has **no equivalent** — a
  `scripts/heartbeat.ps1` plus a Scheduled Task is the missing piece. This was
  the live request when the session ended.
- **Reboot readiness on annapc is unverified.** On the laptop, Docker Desktop
  had `AutoStart: false` — every container's `restart=unless-stopped` looked
  correct and nothing would have come back. Fixed here, unknown there.
- **9 unresolved ingest gaps**, all from one DNS failure at 2026-09-06 20:05
  across all nine waters — the laptop going offline. They never resolve, so
  `/health` and `check.ps1` warn about them forever. Backfill or mark resolved.
- **`tools/pzw_extract.py` was repaired but the data was not regenerated.** Two
  regexes had `\b` stored as a literal backspace, so the splits never fired.
  `config/pzw/mazowiecki.yaml` still holds a water named `'obwodu rybackiego'`
  and others carrying that prose in **both** `name` and `key` — and keys are
  what merging across the three PZW sources matches on. Regenerating changes
  keys that `Lake` rows reference for `water_type`, so it is a migration
  question, deliberately left to the owner.

## Traps

**Escapes eaten writing Windows paths — four separate instances this session.**
`\r` in `scripts\reboot-readiness`, `\b` in `.\b.ps1`, `\f` in a bundle path,
and `\t` in `\tailscale.exe`. The last one had been in `install.ps1` since it
was written and made it report Tailscale missing on the one machine where it
mattered. They are invisible: a terminal renders `scripts<CR>eboot` as
`scriptseboot`, and `repr()` renders the CR back as `\r`, so the search string
looks identical to the corrupted text in every representation that displays it.
Found only by dumping bytes. **A sweeper for this is in the scratchpad approach
used at the end** — scan for `\t \r \b \f \v \a` control characters, ignoring
indentation tabs and CRLF endings, after writing any file containing a Windows
path.

**Nested quoting through PowerShell → `docker exec` → `python -c` loses a
layer.** It made `pack.ps1` report a *good* snapshot as corrupt — the worst
direction for a backup tool. Both scripts pipe Python on stdin now; a
here-string has no quoting to lose.

**`irm | iex` bypasses the execution policy; a `.ps1` file does not.** The
one-liner works, then fails the moment it invokes a child script — and the error
is attributed to `iex` on the pasted line, so it reads as though the one-liner
was rejected. Children are launched with `-ExecutionPolicy Bypass` now.

**`var()` does not resolve in an SVG presentation attribute** in Chrome; it
fails silently to black. `fill="var(--x)"` is broken, `style="fill: var(--x)"`
works. Hit twice — the ambient fish and the fish pin.

**An element screenshot of the fish pin times out**: it animates and never
stabilises. Disable animation first, or clip a fixed region.

**`$args` is a PowerShell automatic variable.** Splatting it silently passes
nothing. Caught before shipping.

**A plain read-only SQLite open still creates `-shm`/`-wal`.** The pack's verify
step was writing sidecars into the bundle it was checking. `immutable=1` fixes it.

**`grep -c` returning 0 exits non-zero** and breaks a `&&` chain — it hid a
result mid-diagnosis.

## Verified vs assumed

**Verified by running:**
- pack against the live installation: 18 tables, integrity ok, 3.1 MB
- restore against a **throwaway volume**, not the live one — row counts
  identical to source
- the full migration on annapc, counts matching, `check.ps1` PASS
- the public URL from this laptop over the internet: `/health`, `/`,
  `/auth/login` all answering, cosy stylesheet and fonts serving
- the heartbeat's four paths (unconfigured, healthy, app down, feed stale)
- the fish pin's colours by asking the browser what it resolved —
  `rgb(143,179,164)` / `rgb(91,133,116)` = `--water` / `--water-deep` — and by
  rendering the page and looking

**Assumed / not tested:**
- the bootstrap's fresh-Windows path end to end (needs a machine without Docker)
- the Oracle VM path entirely (needs an account and a browser)
- anything on a real phone — still the standing gap from the redesign

## Next

**1. Get the live site onto the current commit.** On annapc:

```powershell
git -C C:\Users\admin\fwapp pull
docker compose -f C:\Users\admin\fwapp\docker-compose.yml up -d --build
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\admin\fwapp\scripts\check.ps1
```

The rebuild is required, not optional — the image holds a frozen copy of `app/`.
`check.ps1`'s drift section is what proves it landed.

**2. Wire the Windows heartbeat** — the open request. Write
`scripts/heartbeat.ps1` mirroring `tools/heartbeat.sh` (read `/health`, ping
only when `status == ok` and the feed is under 3 h old, `/fail` with a reason
otherwise), plus a `-Install` switch registering a Scheduled Task every 10
minutes. The owner needs a free healthchecks.io check (period 10 min, grace 20)
and its ping URL in `.env` as `FISHLOG_HEARTBEAT_URL`.

**3. Reboot readiness on annapc**, before relying on it as the always-on box.

**4. Turn off the laptop's funnel** so the old URL stops returning 502.
