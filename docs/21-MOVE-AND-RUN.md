# 21 — Moving Fishlog to another PC, and checking it afterwards

Borrowed in shape from LeadFind's `pack` / `install` / `check` trio and cut down
hard, because Fishlog is a much smaller thing to move. `update.ps1` and
`heartbeat.ps1` came later, for the machine that already has it.

| | |
|---|---|
| `scripts/bootstrap.ps1` | **the one-liner** — everything below, in order |
| `scripts/pack.ps1` | snapshot this installation into one zip |
| `scripts/install.ps1` | restore it on another PC and start it |
| `scripts/check.ps1` | is the whole chain alive, and is the container running *this* code |
| `scripts/update.ps1` | **after a change** — pull, rebuild, gaps, heartbeat, check, in one line |
| `scripts/doctor.ps1` | **when it falls over** — tests every link and leaves evidence behind |

---

## The short version

**On this PC — once.** Makes a ~3 MB zip in your home folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\pack.ps1
```

Copy it to a USB stick.

**On the other PC — one line.** Plug the stick in, open PowerShell, paste:

```powershell
irm https://raw.githubusercontent.com/kyaraslav-cell/fwapp/claude/repository-edit-push-ggr229/scripts/bootstrap.ps1 | iex
```

That is the whole install. It installs Docker if missing, fetches the app,
**finds the bundle on the USB stick by itself**, restores the notebook, starts
it, puts it on a public URL, and runs the health check.

If something is missing it installs it and asks you to restart Windows. Paste
the same line again afterwards — it skips everything already done. Expect up to
two restarts on a clean machine: one for WSL2, one for Docker.

**One step may need an Administrator window.** Docker Desktop runs its engine
inside WSL2, and on a clean Windows install WSL is absent — Docker then installs
happily and refuses to start with *"WSL is not installed"*, which is a dead end
unless you know to go and fix a prerequisite it never mentioned beforehand. The
bootstrap checks first and, if it cannot fix it itself, prints exactly this:

```powershell
# in an Administrator PowerShell, then restart Windows
wsl --install --no-distribution
```

`--no-distribution` keeps it to the engine Docker actually needs, with no Ubuntu
image nobody asked for. Everything else in the bootstrap runs in a normal
window.

### Two rules the bootstrap is built around

**It never makes a bundle and never needs a fresh one.** It searches every
drive root, Downloads and your home folder for `fishlog-bundle-*.zip` and
reuses the newest. Re-packing for every attempt is how LeadFind lost an
afternoon: each try began with a slow rebuild, and when the result looked wrong
nobody could tell whether the fix was bad or the deploy had simply not replaced
anything. One bundle, reused, deletes that question.

**It is safe and fast to re-run.** Docker present, app already fetched,
notebook already restored — each is detected and skipped. Re-running is the
normal way to continue after the Docker restart, so it must never be the thing
that destroys a notebook: it refuses to overwrite an existing one unless you
pass `-Force`.

Only if the bundle is somewhere unusual:

```powershell
irm https://raw.githubusercontent.com/kyaraslav-cell/fwapp/claude/repository-edit-push-ggr229/scripts/bootstrap.ps1 -OutFile b.ps1
.\b.ps1 -Bundle D:\wherever\fishlog-bundle-....zip
```

### Before you restart anything

Installing WSL2 forces a reboot, and a reboot is only safe on a machine that
quietly hosts other things if those things come back by themselves. Check first:

With the repo cloned:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\reboot-readiness.ps1
powershell -ExecutionPolicy Bypass -File scripts\reboot-readiness.ps1 -Fix
```

On a machine that has nothing yet - check, then repair:

```powershell
irm https://raw.githubusercontent.com/kyaraslav-cell/fwapp/claude/repository-edit-push-ggr229/scripts/reboot-readiness.ps1 | iex
```

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/kyaraslav-cell/fwapp/claude/repository-edit-push-ggr229/scripts/reboot-readiness.ps1))) -Fix
```

**Do not download it to a file and run that.** Windows blocks running a
downloaded `.ps1` under the default execution policy, so
`-OutFile r.ps1; .\r.ps1` fails with *"running scripts is disabled on this
system"*. Piping to `iex` never creates a file, so the policy does not apply -
which is why the bootstrap one-liner works and that did not. The
`[scriptblock]::Create(...)` form is the same trick with a way to pass an
argument like `-Fix`.

(A file downloaded from an Administrator window lands in `C:\\WINDOWS\\system32`,
because that is where an elevated prompt starts. Worth deleting if it happened.)

It reports on **every** container on the box, not just Fishlog's, plus whatever
is registered to start at login.

**The trap it exists for:** a container with `restart=unless-stopped` still does
not come back if **Docker Desktop itself is not set to start at login**. The
policy reads as correct and nothing starts, because the thing that would honour
the policy is not running. That was the state of this laptop until it was
checked — `AutoStart: false`, so a reboot would have taken Fishlog down and left
it down.

Two things it will not fix for you:

- A container that is **stopped right now** stays stopped through a reboot.
  `unless-stopped` honours a deliberate stop, which is correct and still worth
  saying, because "it has a restart policy" reads as "it will come back".
- Anything running **outside Docker** — a native n8n, a watcher script — has no
  restart policy at all. If it is not in a Startup folder or a scheduled task, a
  reboot simply ends it. The script lists what is registered so the gap is
  visible.

### Afterwards

- **Stop the old machine** — `docker compose stop fishlog`. Two copies running
  means two notebooks drifting apart, and there is no sync.
- **Google sign-in only:** the new PC has a different address. The installer
  prints it and rewrites `.env`; you must add that exact address in the Google
  console under *Credentials → Authorised redirect URIs*. Email and password
  sign-in works without this.

---

## What travels, and what does not

| Travels | Why it cannot be recreated |
|---|---|
| `fishlog.db` | the notebook: sessions, catches, waters — **and 77 000 hours of weather observations** that accumulated in real calendar time |
| `/data/media` | catch photos |
| `.env` | the API keys the app reads at runtime |
| `bundle.json` | which commit it was packed from |

**The repository does not travel.** It is public, so the other machine clones
it. That is the one real difference from the LeadFind bundle, which had to
carry a private repo and came out at 128 MB. This one is 3 MB.

Nothing here has LeadFind's worst coupling either: n8n stores credentials that
workflows reference *by id*, so its bundle also has to carry `~/.n8n/config`
(the encryption key) or every node points at an id that no longer resolves.
Fishlog has no equivalent — the `.env` is read at runtime and nothing references
anything by generated id.

## Three things the pack script does that a plain copy does not

**1. It snapshots through SQLite's backup API, not by copying files.**
The database runs in WAL mode, so the most recent writes live in
`fishlog.db-wal` and *not* in `fishlog.db`. Copying the `.db` alone silently
loses whatever happened most recently. `.backup()` takes a consistent snapshot
of a database that is still being written to and folds the WAL in, so the
bundle holds one self-contained file with no sidecar to forget.

**2. It verifies the snapshot before trusting it.** `pragma integrity_check`
plus a table count, run against the file in the bundle. A corrupt backup nobody
opened until restore day is worse than no backup, because it was believed.

**3. It records the commit, and warns about uncommitted work.** Migrations are
forward-only, so restoring a notebook onto an *older* checkout cannot work. The
installer compares and says so rather than failing obscurely. And because the
other machine clones rather than copies, uncommitted changes here will not
arrive — the packer says so at pack time, not after the move.

## Why there is no long test

The 511-test suite tests the *code*, and the code is identical on both machines
— it came from the same git commit. Re-running it on the target proves nothing
that the source machine did not already prove.

What is genuinely different after a move is the **deployment**: Docker, the
volume, the restored data, the secrets, the proxy setting, the funnel. That is
what `check.ps1` looks at, and it takes seconds.

So: `pytest` on the machine you develop on, `check.ps1` on the machine you
deploy to.

## The check that earns its place

`check.ps1` asks something the others do not: **is the container running the
code in this working tree?**

This is lifted directly from LeadFind's worst bug. n8n reported three workflows
as "published and in sync" while the scheduler quietly executed code from days
earlier — because activating an already-active workflow does not replace the
running copy. Every check they had said green.

Fishlog has the same failure in a different costume. The image holds a **frozen
copy** of `app/` and `config/` — there is no bind mount — so editing a file
changes nothing the public URL serves, and neither `docker compose restart` nor
a bare `docker compose up -d` picks it up. Standing rule 20 exists because of
exactly this.

So the check hashes every file under `app/` and `config/` **inside the running
container** and compares against the working tree, and names the files that
differ when they do:

```
== Is the container running THIS code? =======================
  [ok]   container matches the working tree (138 files, C1363ECD6EFA)
```

or

```
  [FAIL] container is serving DIFFERENT code from the working tree
         image A1B2C3D4E5F6  vs  tree 9F8E7D6C5B4A
         ~ app/web/static/style.css
         ~ app/web/templates/base.html
         Fix: docker compose up -d --build
```

A green test suite and a running container together still do not tell you this.

## What else `check.ps1` covers

- Docker engine and compose service status
- `/health`, plus `/`, `/auth/login`, `/history` returning sensibly
- **weather feed age** — a stale feed is the quiet failure, because the app
  serves perfectly while every score it shows is yesterday's. Law 4 forbids
  inventing the missing hours, so the age is the only honest signal.
- row counts per table, and that the named volume exists
- which optional API keys are set (all of them are optional by design — a
  missing one is a note, never a failure)
- `FISHLOG_TRUST_PROXY`, which is wrong in both directions if it does not match
  what sits in front of the app
- the Tailscale funnel and the public URL

Exit code is the number of failures, so it can gate a script.

## Both halves were tested, not assumed

- `pack.ps1` run against the live installation: 18 tables, integrity ok, 3.1 MB.
- The restore path run **against a throwaway volume**, not the live one, and the
  restored notebook opened with row counts identical to the source: 2 users,
  9 waters, 11 catches, 8 sessions, 77 232 weather rows, 576 predictions.

Two flaws that only showed up by running it:

- Nesting a Python string through PowerShell → `docker exec` → `python -c` loses
  a quote layer, which made the verify step report a **good snapshot as
  corrupt**. Both scripts now pipe Python in on stdin, which has no quoting to
  lose.
- A plain read-only open of a WAL database still creates `-shm` and `-wal`, so
  the verify step was writing two sidecars into the bundle it was checking.
  It opens with `immutable=1` now.

`install.ps1`'s full first-run path — winget installing Docker Desktop, the
reboot, the wait loop — has **not** been run end to end, because doing that
needs a machine without Docker on it. The restore logic inside it has been.

## Security

The bundle holds live API keys **and a second real person's fishing notebook**.
It is written outside the repo, is never committed, and should move by USB or
local network — not email, not cloud storage. Delete it from both machines once
`check.ps1` passes on the target.

## Known gaps

- The installer's fresh-Windows path is untested (above).
- `install.ps1` turns the funnel on and rewrites `FISHLOG_GOOGLE_REDIRECT_URI`
  for the new host, but the matching URI still has to be added by hand in the
  Google console — Google matches it exactly and there is no API for it.
- `-Force` on the installer overwrites an existing notebook. There is no undo,
  and no second copy is taken first. Pack the target machine before forcing.

---

## Off the laptop entirely — the autonomous path

Everything above moves Fishlog to *another PC*. If the point is that no laptop
has to stay on, the target is a free cloud VM, and the runbook for that already
exists: [`docs/16-DEPLOY-ORACLE.md`](16-DEPLOY-ORACLE.md). Oracle's Always Free
tier is the only free host with a real persistent block volume, which is the
constraint that rules out the others.

Three things were missing from that runbook for a genuinely unattended box, and
are now in `tools/oracle_vm_setup.sh`:

**1. It can restore your notebook, instead of starting empty.**

```bash
# on the laptop
powershell -ExecutionPolicy Bypass -File scripts\pack.ps1
# copy the ~3 MB zip to the VM, then on the VM
./oracle_vm_setup.sh --bundle ~/fishlog-bundle-....zip
```

**2. The public hostname changes, and that breaks Google sign-in silently.**
The URL is the Tailscale *node name*, which is per-machine, and the bundle
carries the laptop's `FISHLOG_GOOGLE_REDIRECT_URI`. Google matches the redirect
exactly, so a stale one fails with nothing readable. The script says so; the new
URI still has to be added in the Google console by hand. Email and password
sign-in is unaffected.

**3. Nothing was watching it.** Which matters far more once the box is one you
never look at.

### The heartbeat

Two scripts, one contract. **`scripts/heartbeat.ps1` is the one that runs on
annapc** — a Scheduled Task every 10 minutes. `tools/heartbeat.sh` is the same
check for the Linux/VM fallback in `docs/16`, run by a systemd timer. Both read
the app's own `/health` and ping an external dead-man's switch **only while the
app is genuinely healthy**, and both exit with the same codes.

Outbound rather than an uptime service polling the URL, because one mechanism
then covers three different failures:

| Failure | What the monitor sees |
|---|---|
| VM dead, or no network | no ping at all — it alerts on the silence |
| container down or erroring | an immediate failure ping, with the reason |
| **up, but the weather feed is stale** | a failure ping — the quiet one |

That third row is why this is not just `curl -f /health`. A stale feed means
the app serves perfectly while every score it shows is old, and law 4 forbids
inventing the missing hours — so it stays visibly stale forever and nothing
else would ever complain.

Unresolved ingest gaps are **reported but do not fail** the check. A gap is a
record that an hour was missed; it stays on the books until somebody backfills
it, so failing on one would mean alerting forever about a past incident, which
just teaches you to ignore the alert.

#### Setup on annapc — two lines

Create a free check at [healthchecks.io](https://healthchecks.io) first —
**period 10 minutes, grace 20 minutes** — and copy its ping URL. Then, in
PowerShell on annapc:

```powershell
git -C C:\Users\admin\fwapp pull
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\admin\fwapp\scripts\heartbeat.ps1 -Install -PingUrl https://hc-ping.com/<uuid>
```

The second line writes the URL into `.env`, asks for administrator (a
**UAC prompt will appear — approve it**), registers the task, runs one check
immediately to prove it, and prints the result back into the original window.

Registering a Scheduled Task is an administrator action on a default Windows
install — denied even for a task in your own folder, and the refusal arrives as
`HRESULT 0x80070005`, which reads like a broken script rather than a missing
privilege. Rather than make that a third pasted line, the installer re-launches
itself through UAC and waits. Elevated, it registers with **S4U** logon: no
stored password, no console window flashing every ten minutes, and the check
keeps running when nobody is signed in. If a machine's policy refuses S4U it
falls back to an Interactive task, which still covers this box — Docker Desktop
is a session app, so the app only serves while somebody is logged in anyway.

Two triggers are registered on purpose: the repeating one is the check, and an
at-logon one fires immediately after a reboot, which is exactly when the answer
is least certain and the next repetition may still be minutes away.

Afterwards:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\admin\fwapp\scripts\heartbeat.ps1 -Status
```

which prints the task state, its last result, the next run, and the last ten
checks from `logs\heartbeat.log`. The ping URL is printed **masked** — the uuid
in it is the credential, and anyone holding it can post a fake "all is well".
`-Uninstall` removes the task and leaves `.env` alone.

With `FISHLOG_HEARTBEAT_URL` unset the script exits quietly and changes
nothing, so it is safe to install first and configure later. `-EveryMinutes`
changes the interval; keep the healthchecks.io period in step with it.

#### Setup on the Linux/VM fallback

```bash
# create a free check at healthchecks.io - period 10 min, grace 20 min
echo 'FISHLOG_HEARTBEAT_URL=https://hc-ping.com/<uuid>' >> ~/fwapp/.env
~/fwapp/tools/heartbeat.sh        # should print: ok age=0.4h gaps=0
systemctl list-timers fishlog-heartbeat.timer
```

### Tested

`tools/heartbeat.sh`, all four paths against the live app:

| | Result |
|---|---|
| no monitor configured | exits quietly, rc 0 |
| healthy | `ok age=0.1h gaps=9`, rc 0 |
| app unreachable | `UNHEALTHY: no response from ...`, rc 1 |
| feed stale (limit forced to 0h) | `UNHEALTHY: weather feed 0.1h behind`, rc 1 |

A monitor that is itself unreachable warns and still exits 0 — a monitoring
outage is not an application outage, and reporting it as one is how a check
gets muted.

`scripts/heartbeat.ps1`, all five paths against the **live annapc app** over the
funnel, with a local sink standing in for healthchecks.io so that what the
monitor actually received could be read rather than assumed:

| | Result | What the monitor received |
|---|---|---|
| no monitor configured | exits quietly, rc 0 | nothing |
| healthy | `ok age=0.6h gaps=9`, rc 0 | `POST /ping-test :: ok age=0.6h gaps=9` |
| feed stale (limit forced to 0h) | rc 1 | `POST /ping-test/fail :: weather feed 0.6h behind (limit 0h) …` |
| app unreachable | rc 1 | `POST /ping-test/fail :: no response from … (Unable to connect …)` |
| monitor itself unreachable | `ok`, then a warning, rc 0 | — (sink stopped) |

The task **definition** was validated by building it with `New-ScheduledTask`
for both S4U and Interactive principals: two triggers, repetition `PT10M`, and
an empty repetition duration, which is how PowerShell 5.1 spells *indefinitely*
(passing `[TimeSpan]::MaxValue` there throws instead).

**Not tested:** the registration itself, which needs administrator — this
laptop refused it, which is how the elevation path came to exist in the first
place. It is proven on annapc by the `-Status` output after the install, not
before. The VM path end to end is also untested, because that needs an Oracle
account and a console session.

---

## The old URL is switched off

`https://dell.tailf99616.ts.net` served **502** from the moment the app moved:
the laptop's container was stopped but its Tailscale funnel was still on,
proxying a public HTTPS name at a dead port 8000. A 502 is worse than nothing —
it looks like an app that is broken rather than an address that has moved.

Turned off on 2026-09-08, on the laptop, after confirming the container was
stopped and nothing answered on 8000:

```powershell
& "C:\Program Files\Tailscale\tailscale.exe" funnel --bg off
```

`tailscale funnel status` now reports `No serve config`, and the old hostname no
longer answers at all. Nothing on annapc was touched; its funnel and `/health`
were re-checked afterwards.

Reversible with `tailscale funnel --bg 8000` if that machine ever serves again.

---

## Ingest gaps that never closed

`/health` reported `unresolved_gaps: 9` for days, and would have reported it
forever. All nine came from a single DNS failure at **2026-09-06 20:05**, one
per water, when the laptop dropped off the network mid-move.

The cause was not the DNS failure. It was that **nothing in this project ever
set `ingest_gap.resolved`** — gaps were written and never closed, by any code
path. So the count only ever grows, and a monitor whose warning never clears is
a monitor that gets ignored, which defeats the heartbeat installed above.

`tools/resolve_gaps.py` closes a gap **only on evidence**: `weather_hourly`
contains every hour the gap covers, normally because the next scheduled fetch an
hour later wrote them. A gap whose hours are genuinely still absent stays open,
however old and however irritating, because law 4 makes a hole in the record
honest and its concealment a bug.

The asymmetry is the design: this tool can close a gap, and it can never fill
one. It does not call Open-Meteo at all.

A forecast gap stores the *moment* a fetch failed, so it covers the single hour
containing it; an archive gap stores a chunk of days. Both reduce to the same
question once the ends are floored to the hour. Coverage is counted across
**any** source — an hour the archive later supplied for a failed forecast fetch
is on record just as truly, and refusing to see it would keep a gap open over a
bookkeeping detail.

On annapc, where `tools/` is not in the image and the database lives in a docker
volume, mount the repo's tools for the run:

```powershell
docker compose run --rm -v C:\Users\admin\fwapp\tools:/srv/fishlog/tools fishlog python tools/resolve_gaps.py --dry-run
```

then the same without `--dry-run` to apply. Run it from `C:\Users\admin\fwapp`,
so compose finds `docker-compose.yml`. The path is spelled out rather than
`${PWD}` because that expands to a Windows path with backslashes in the middle
of a colon-separated mount argument, which is exactly the kind of string that
fails in a way nobody reads twice.

`docker compose run` starts a second, short-lived container against the **same**
`fishlog-data` volume and overrides the command, so the app keeps serving
throughout. SQLite in WAL mode handles the concurrent write.

### Tested

Against a throwaway database shaped like annapc's — nine waters, one DNS
failure across all of them, the hour recovered for eight and genuinely lost for
the ninth:

| | Result |
|---|---|
| `--dry-run` | reports `would close 8 of 9`, writes nothing |
| apply | closes 8, prints the ninth's missing hour |
| re-run | only the ninth remains; idempotent |

`tests/test_resolve_gaps.py` pins the direction that matters: a gap is **not**
closed when its hour is missing, when only part of a range is present, when the
matching hour belongs to another lake, or during a dry run.

**Not run on annapc yet** — the nine gaps there are still open. The expectation
is that all nine close, because the app has ingested hourly since, but that is
a prediction and `--dry-run` is what turns it into an observation.

---

## After a change — one line

`bootstrap.ps1` moves the app to a machine. `update.ps1` is the other half:
bring the machine that already has it up to date, and re-run everything that
should follow a pull.

On annapc, from anywhere, even when the checkout is behind — it fetches itself:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/kyaraslav-cell/fwapp/claude/repository-edit-push-ggr229/scripts/update.ps1))) -PingUrl https://hc-ping.com/<uuid>
```

`-PingUrl` is only needed the first time; after that it is in `.env` and the
line is the same without it. Run it from an **Administrator** window to avoid a
UAC prompt at the heartbeat step — without one it still works, because that
installer elevates itself and waits.

Six steps, stopping at the first real failure:

| | Step | Why here |
|---|---|---|
| 1 | `git pull --ff-only` | nothing below means anything against stale code |
| 2 | `docker compose up -d --build` | standing rule 20 — the image holds a frozen copy of `app/`, so a pull alone changes nothing the URL serves |
| 3 | `reboot-readiness.ps1 -Fix` | a box that does not come back is not always-on, and this is the cheapest moment to find out |
| 4 | `resolve_gaps.py` | close gaps whose hours arrived, so step 5 is not born relaying a warning that can never clear |
| 5 | `heartbeat.ps1 -Install` | skipped quietly when no ping URL exists anywhere |
| 6 | `check.ps1` | last, because it is the only step that proves the container runs *this* code |

Every step is safe to re-run, and nothing deletes anything: the notebook is on
the named volume `fishlog-data`, outside the image, and step 4 can only close a
gap on evidence, never fill one. `-SkipRebootFix` and `-SkipGaps` drop steps 3
and 4; `-RepoDir` points it at a checkout somewhere unusual.

### Two failures it was built to not have

**A refused pull looked exactly like an up-to-date one.** `git pull` leaves HEAD
where it was when it refuses — local edits, a diverged branch — so comparing the
commit before and after reports "already at abc1234" and every step below then
runs against stale code, rebuilding and blessing it with a green `check.ps1`.
The exit code is read instead, and a refusal stops the run. `git` is called
plainly rather than through the stderr-swallowing wrapper for exactly this
reason: redirecting a native command's stderr in PowerShell 5.1 both
manufactures errors out of ordinary progress output and hides the code that
matters.

**`$?` after an assignment reports on the assignment.** The Docker guard was
written as `$null = Native { docker info }; if (-not $?)`, which can never fire,
because assigning always succeeds. It tests the returned value now. A guard that
cannot fail is worse than no guard: it reads as a check.

### Tested

Not end to end — running it on the laptop would rebuild and **restart** the
container that was deliberately stopped there, resurrecting a second app writing
to a second notebook. The pieces were exercised individually instead:

| | Result |
|---|---|
| bogus `-RepoDir` | `[FAIL] no checkout found`, "Nothing after this step ran", rc 1 |
| child launching (`-ExecutionPolicy Bypass`, arguments) | ran `heartbeat.ps1 -Status`, rc 0 |
| the docker mount string | `C:\...\fwapp\tools:/srv/fishlog/tools`, target exists |
| the Docker guard | engine `29.7.2` read back, so it passes rather than never firing |
| parse + control-character sweep | clean — `\t`, `\r`, `\b`, `\f` intact in every Windows path |

That last row is not ceremony. Four separate escapes were eaten writing Windows
paths during the migration session, including `\t` in `\tailscale.exe`, which
made `install.ps1` report Tailscale missing on the one machine where it
mattered. They are invisible in every representation that displays them.

---

## When it falls over — `scripts/doctor.ps1`

`check.ps1` answers *did the deploy land*. `doctor.ps1` answers *why did it fall,
and which link is about to*. Run it on annapc when something looks wrong, or
straight after a fall:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\admin\fwapp\scripts\doctor.ps1
```

`-Ping` additionally sends one real ping to the monitor. `-Quiet` prints nothing
and only writes the report, for a scheduled run. Exit code is the number of
failures, so a scheduler can act on it.

Nine sections, in dependency order — machine, docker, the environment inside the
container, the app, monitoring, background jobs, code drift, public URL, verdict.
Read the **first** `[FAIL]`, not the last: they cascade, and a missing container
makes everything below it fail too. Sections that cannot run say `skipped - no
container` rather than inventing a failure.

### The three things it does that nothing else here does

**1. It reads the environment INSIDE the container.** `check.ps1` reads `.env`
on the host, and those are different things — `.env` is not copied into the
image. Believing the host copy is exactly how the dead man's switch sat unset
for a day while every check reported it configured. `doctor.ps1` lists what is
in `.env`, then asserts each one actually arrived, with a short exemption list
for the settings that legitimately never travel (`KIE_AI_API_KEY` is build-time
only, `FISHLOG_HEARTBEAT_URL` is read by a host script).

**2. It tests paths instead of reading state.** Egress to the monitor is tried
*from inside the container* — the only place it matters — by fetching the ping
host's root rather than the check's own URL, so connectivity is proven without
marking the check "up" and masking a real outage. `-Ping` sends a genuine ping,
also from inside the container, through the same `httpx` the app uses.

**3. It collects post-mortem evidence.** Container start time, restart count,
OOM kills, the previous exit code, tracebacks in the log, Windows boot time and
unexpected-shutdown events. An app that fell and recovered leaves nothing behind
otherwise, which is why "it fell again" was unanswerable every previous time.
Every run writes `logs\doctor-<timestamp>.txt` and appends one line to
`logs\doctor-history.txt`, so a pattern across falls becomes readable instead of
remembered. The last 30 reports are kept.

The single most useful line is the container's age. A container that *is
running* but started eleven minutes ago fell over eleven minutes ago, and
nothing else on the box will tell you that.

### Four bugs found by running it, not by reading it

Every one of these looked correct in the source and was wrong in practice.

**`docker logs` was returning nothing.** Python's logging writes to **stderr**,
and the `Native` wrapper that guards every docker call discards stderr. So the
script reported "no heartbeat line in the log" and "no ingest activity" against
a container that was logging both — the precise false alarm it exists to
prevent. `docker logs` now goes through `cmd /c "... 2>&1"`, letting cmd do the
redirection, because `2>&1` on a native command in PowerShell 5.1 wraps each
stderr line in an ErrorRecord.

**The drift check would have cried wolf forever.** The first version hashed one
stream per side, walking the container with `os.walk` — which sorts only within
a directory — against a globally sorted host list. Those orderings disagree on
*identical* code. Replaced with `check.ps1`'s proven per-file recipe, then
verified by building a fresh image and confirming both sides agree: 140 files,
same hash.

**The test ping travelled the wrong path.** It was sent from the host while
every real ping comes from inside the container. The host can reach a monitor
the container cannot, and the reverse; a test that does not travel the real path
proves nothing. It now runs inside the container.

**`$ping` silently became a switch.** `[switch]$Ping` in the param block is a
*type-constrained* variable and PowerShell is case-insensitive, so assigning a
here-string to `$ping` coerced it to a `SwitchParameter` and piped nothing into
python. The probe reported failure with an empty error message while working
perfectly by hand.

### Tested

Against a real container on the laptop, started deliberately for the purpose
against a local sink (never the real check) and stopped again afterwards:

| | Result |
|---|---|
| no container | 5 sections say `skipped`, 1 FAIL, no cascade |
| live container | environment inside verified, drift matched, logs parsed |
| egress probe | `REACHABLE ... 200` from inside the container, sink saw `GET /` only |
| `-Ping` | `SENT 200`, sink saw `POST /<check> :: doctor test ping` |
| `-Quiet` | 0 lines printed, report still written |
| drift, identical code | 140 files both sides, same hash — no false alarm |
| exit code | equals the failure count |

**Not tested:** an actual OOM kill, a crash loop, and the unexpected-shutdown
event reader, which needs administrator on this machine and reported so rather
than failing.
