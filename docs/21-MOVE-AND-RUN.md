# 21 — Moving Fishlog to another PC, and checking it afterwards

Three scripts, borrowed in shape from LeadFind's `pack` / `install` / `check`
trio and cut down hard, because Fishlog is a much smaller thing to move.

| | |
|---|---|
| `scripts/pack.ps1` | snapshot this installation into one zip |
| `scripts/install.ps1` | restore it on another PC and start it |
| `scripts/check.ps1` | is the whole chain alive, and is the container running *this* code |

---

## The short version

**On this PC**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\pack.ps1
```

Writes `fishlog-bundle-<date>.zip` to your home folder. About **3 MB**.

**On the other PC**

```powershell
git clone https://github.com/kyaraslav-cell/fwapp.git fwapp
cd fwapp
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Bundle C:\path\fishlog-bundle-....zip
powershell -ExecutionPolicy Bypass -File scripts\check.ps1
```

That is the whole process. No test suite on the target machine — see
"Why there is no long test" below.

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
- Nothing here sets up the Tailscale funnel on the new machine; `check.ps1`
  reports its absence but does not fix it. See `docs/16-DEPLOY-ORACLE.md`.
- `-Force` on the installer overwrites an existing notebook. There is no undo,
  and no second copy is taken first. Pack the target machine before forcing.
