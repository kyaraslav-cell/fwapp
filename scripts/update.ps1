# Bring this machine up to date with the branch, and re-run everything that
# should follow a pull. One line, in order, stopping at the first real failure.
#
# From anywhere, even if the checkout is behind (this fetches itself):
#
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/kyaraslav-cell/fwapp/claude/repository-edit-push-ggr229/scripts/update.ps1))) -PingUrl https://hc-ping.com/<uuid>
#
# With the repo already current:
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\update.ps1 -PingUrl https://hc-ping.com/<uuid>
#
# What it does, and why in this order:
#
#   1. git pull            - nothing below means anything against stale code
#   2. compose up --build  - standing rule 20. The image holds a FROZEN copy of
#                            app/ and config/, so a pull alone changes nothing
#                            the public URL serves
#   3. reboot readiness    - a box that does not come back is not always-on,
#                            and this is the cheapest moment to find out
#   4. resolve gaps        - close ingest gaps whose hours actually arrived, so
#                            the heartbeat below is not born relaying a warning
#                            that can never clear
#   5. heartbeat install   - only when a ping URL is supplied or already in .env
#   6. check.ps1           - last, because it is the only step that proves the
#                            container is running THIS code rather than a copy
#
# Every step is safe to re-run. Nothing here deletes anything: the notebook
# lives on the named volume `fishlog-data`, outside the image, and step 4 can
# only close a gap on evidence, never fill one.
#
# Run it from an Administrator window to avoid a UAC prompt at step 5. Without
# one it still works - the heartbeat installer elevates itself and waits.

param(
    [string]$RepoDir,
    [string]$PingUrl,
    [switch]$SkipRebootFix,
    [switch]$SkipGaps
)

$ErrorActionPreference = 'Continue'

function Section($t) {
    Write-Host ""
    Write-Host "== $t " -NoNewline -ForegroundColor Cyan
    Write-Host ("=" * [Math]::Max(2, 58 - $t.Length)) -ForegroundColor DarkCyan
}
function Ok($t)   { Write-Host "  [ok]   $t" -ForegroundColor Green }
function Bad($t)  { Write-Host "  [FAIL] $t" -ForegroundColor Red }
function Warn($t) { Write-Host "  [warn] $t" -ForegroundColor Yellow }
function Note($t) { Write-Host "  [--]   $t" -ForegroundColor DarkGray }

# PowerShell 5.1 wraps a native command's stderr in an ErrorRecord, so `git` and
# `docker` writing a perfectly ordinary progress line can look like a failure.
function Native {
    param([scriptblock]$B)
    $p = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $o = & $B 2>$null } catch { $o = $null } finally { $ErrorActionPreference = $p }
    return $o
}

function Die($t) {
    Bad $t
    Write-Host ""
    Write-Host "  Stopped. Nothing after this step ran." -ForegroundColor Red
    Write-Host ""
    exit 1
}

# ------------------------------------------------------- 0. find the checkout
# $PSScriptRoot is EMPTY when this arrives through `irm | iex`, which is the
# headline way to run it - so the repo can never be located relative to this
# file. It is a parameter with a searched default instead.
Section "Repository"
if (-not $RepoDir) {
    $candidates = @(
        'C:\Users\admin\fwapp',
        (Join-Path $env:USERPROFILE 'fwapp'),
        (Join-Path $env:USERPROFILE 'Desktop\Claude\fwapp')
    )
    $RepoDir = $candidates | Where-Object { Test-Path (Join-Path $_ 'docker-compose.yml') } | Select-Object -First 1
}
if (-not $RepoDir -or -not (Test-Path (Join-Path $RepoDir 'docker-compose.yml'))) {
    Die "no checkout found - pass -RepoDir C:\path\to\fwapp"
}
$RepoDir = (Resolve-Path $RepoDir).Path
Ok $RepoDir
Set-Location $RepoDir

function Run-Child {
    param([string]$Script, [string[]]$Arguments = @())
    $path = Join-Path $RepoDir $Script
    if (-not (Test-Path $path)) { Warn "$Script not in this checkout - skipped"; return $null }
    # -ExecutionPolicy Bypass on the CHILD. `irm | iex` bypasses the policy for
    # the pasted line only; the moment it launches a .ps1 file the policy
    # applies again, and the refusal is reported against the pasted line, so it
    # reads as though the one-liner was rejected.
    $childArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $path) + $Arguments
    & powershell.exe @childArgs
    return $LASTEXITCODE
}

# ------------------------------------------------------------------ 1. pull
Section "Pull"
$before = (Native { git -C $RepoDir rev-parse --short HEAD }) | Select-Object -First 1
if (-not $before) { Die "git could not read this checkout - is git installed and is $RepoDir a clone?" }

# Called plainly, not through Native. git writes progress to stderr, so
# redirecting it would manufacture a NativeCommandError out of an ordinary
# successful pull - and the exit code has to be readable, because a pull that
# was REFUSED (local edits, diverged history) otherwise leaves HEAD where it
# was and is indistinguishable from "already up to date". That is the one
# failure that would silently deploy stale code through every step below.
git -C $RepoDir pull --ff-only
if ($LASTEXITCODE -ne 0) {
    Die "git pull failed - fix it by hand (local changes, or a diverged branch), then re-run"
}

$after = (Native { git -C $RepoDir rev-parse --short HEAD }) | Select-Object -First 1
if ($before -eq $after) { Note "already at $after" } else { Ok "$before -> $after" }

# ------------------------------------------------------------- 2. rebuild
# Standing rule 20. Not `restart`, not a bare `up -d` - neither picks up a
# changed app/ because there is no bind mount and the image holds a frozen copy.
Section "Rebuild and start"
# Test the returned value, not $? - $? after an assignment reports on the
# assignment, which always succeeds, so the guard would never fire.
$ver = (Native { docker info --format '{{.ServerVersion}}' }) | Select-Object -First 1
if (-not $ver) { Die "Docker is not responding - start Docker Desktop and run this again" }
Note "docker engine $ver"
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Die "the build failed - nothing was replaced, the old container is still serving" }
Ok "container rebuilt from the current working tree"

# --------------------------------------------------------- 3. reboot readiness
Section "Reboot readiness"
if ($SkipRebootFix) {
    Note "skipped (-SkipRebootFix)"
} else {
    $null = Run-Child 'scripts\reboot-readiness.ps1' @('-Fix')
}

# ---------------------------------------------------------------- 4. the gaps
Section "Ingest gaps"
if ($SkipGaps) {
    Note "skipped (-SkipGaps)"
} else {
    # tools/ is not in the image, so the repo's copy is mounted for one
    # short-lived container against the same volume. The app keeps serving
    # throughout; SQLite in WAL mode handles the concurrent write.
    $mount = "{0}\tools:/srv/fishlog/tools" -f $RepoDir
    docker compose run --rm -v $mount fishlog python tools/resolve_gaps.py
    if ($LASTEXITCODE -ne 0) { Warn "the gap review did not complete - not fatal, the app is unaffected" }
}

# ------------------------------------------------------------- 5. heartbeat
Section "Heartbeat"
$hbArgs = @('-Install')
if ($PingUrl) { $hbArgs += @('-PingUrl', $PingUrl) }
$null = Run-Child 'scripts\heartbeat.ps1' $hbArgs

# ----------------------------------------------------------------- 6. check
Section "Health check"
$rc = Run-Child 'scripts\check.ps1'

Write-Host ""
if ($rc -eq 0) {
    Write-Host "  Done. The site is on the current commit and something is watching it." -ForegroundColor Green
} else {
    Write-Host "  Done, but check.ps1 reported problems - read its FAIL lines above." -ForegroundColor Yellow
}
Write-Host ""
exit $rc
