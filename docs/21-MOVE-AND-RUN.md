# 21 — Moving Fishlog to another PC, and checking it afterwards

Three scripts, borrowed in shape from LeadFind's `pack` / `install` / `check`
trio and cut down hard, because Fishlog is a much smaller thing to move.

| | |
|---|---|
| `scripts/bootstrap.ps1` | **the one-liner** — everything below, in order |
| `scripts/pack.ps1` | snapshot this installation into one zip |
| `scripts/install.ps1` | restore it on another PC and start it |
| `scripts/check.ps1` | is the whole chain alive, and is the container running *this* code |

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

If Docker was missing it will install it and ask you to restart Windows. Paste
the same line again afterwards — it skips everything already done.

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
..ps1 -Bundle D:\whereverishlog-bundle-....zip
```

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

`tools/heartbeat.sh`, run by a systemd timer every 10 minutes. It reads the
app's own `/health` and pings an external dead-man's switch **only while the app
is genuinely healthy**.

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

Setup, once the VM is up:

```bash
# create a free check at healthchecks.io - period 10 min, grace 20 min
echo 'FISHLOG_HEARTBEAT_URL=https://hc-ping.com/<uuid>' >> ~/fwapp/.env
~/fwapp/tools/heartbeat.sh        # should print: ok age=0.4h gaps=0
systemctl list-timers fishlog-heartbeat.timer
```

With `FISHLOG_HEARTBEAT_URL` unset the script exits quietly and changes
nothing, so it is safe to install first and configure later.

### Tested

All four paths, against the live app:

| | Result |
|---|---|
| no monitor configured | exits quietly, rc 0 |
| healthy | `ok age=0.1h gaps=9`, rc 0 |
| app unreachable | `UNHEALTHY: no response from ...`, rc 1 |
| feed stale (limit forced to 0h) | `UNHEALTHY: weather feed 0.1h behind`, rc 1 |

A monitor that is itself unreachable warns and still exits 0 — a monitoring
outage is not an application outage, and reporting it as one is how a check
gets muted.

**Not tested:** the VM path end to end, because that needs an Oracle account and
a console session. The scripts parse and the heartbeat is proven against the
real app; provisioning the box is still `docs/16` and a browser.
