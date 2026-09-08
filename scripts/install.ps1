# Restores Fishlog on a PC from a bundle made by pack.ps1, and starts it.
#
#   git clone https://github.com/kyaraslav-cell/fwapp.git fwapp
#   cd fwapp
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Bundle C:\path\fishlog-bundle-....zip
#
# Re-running is safe. -Bundle is optional: without it you get a fresh, empty
# notebook, which is the right thing for a second machine you only want to
# develop on.
#
# Deliberately NOT a one-liner from the internet. The bundle holds live API keys
# and a second person's fishing notebook, so it travels by hand.

param(
    [string]$Bundle,
    # Overwrite an existing notebook. Off by default: restoring over a volume
    # that already has sessions in it destroys them, and the only person who
    # knows whether that is wanted is the one typing.
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Say($t, $c = 'Gray') { Write-Host $t -ForegroundColor $c }
function Native {
    param([scriptblock]$Block)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $o = & $Block 2>&1 } catch { $o = $null } finally { $ErrorActionPreference = $prev }
    return $o
}

Say ''
Say '  Fishlog - install' 'Cyan'
Say ''

# ---------------------------------------------------------------- 1. prereqs
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Say '  Docker is not installed. Installing Docker Desktop...' 'Yellow'
    $null = Native { winget install --id Docker.DockerDesktop -e --accept-source-agreements --accept-package-agreements --silent }
    Say ''
    Say '  Docker Desktop needs a reboot before it will run.' 'Yellow'
    Say '  Reboot, then run this script again - it will carry on from here.' 'Yellow'
    Say ''
    exit 0
}

# Docker Desktop takes its time after login. Waiting here rather than failing
# is the difference between "run it again" and "it just worked".
Say '  waiting for the Docker engine...'
$deadline = (Get-Date).AddMinutes(4)
$engine = $null
while ((Get-Date) -lt $deadline) {
    $engine = (Native { docker info --format '{{.ServerVersion}}' }) | Where-Object { $_ -match '^\d' } | Select-Object -First 1
    if ($engine) { break }
    Start-Sleep -Seconds 6
}
if (-not $engine) {
    Say ''
    Say '  The Docker engine did not come up. Start Docker Desktop, then re-run.' 'Red'
    exit 1
}
Say "  engine up ($engine)" 'Green'

# --------------------------------------------------------------- 2. unpack
$restore = $null
if ($Bundle) {
    if (-not (Test-Path $Bundle)) { throw "Bundle not found: $Bundle" }
    # Unpack our own copy. A half-extracted folder handed in by the user is how
    # you get a half-restored database that looks fine until it does not.
    $restore = Join-Path $env:TEMP ("fishlog-restore-" + (Get-Date -Format 'HHmmss'))
    New-Item -ItemType Directory -Force -Path $restore | Out-Null
    Say '  unpacking the bundle...'
    Expand-Archive -Path $Bundle -DestinationPath $restore -Force

    $meta = Get-Content (Join-Path $restore 'bundle.json') -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
    if ($meta) {
        Say "  packed $($meta.packed) on $($meta.from)"
        Say "  commit $($meta.commit) ($($meta.branch))"
        $here = (Native { git rev-parse HEAD }) | Select-Object -First 1
        if ($here -and $meta.commit -and $here -ne $meta.commit) {
            Say ''
            Say '  This checkout is at a different commit from the bundle.' 'Yellow'
            Say "    bundle: $($meta.commit)" 'Yellow'
            Say "    here:   $here" 'Yellow'
            Say '  Migrations are forward-only, so an OLDER checkout than the' 'Yellow'
            Say '  notebook cannot open it. If the app fails to start, run:' 'Yellow'
            Say "    git checkout $($meta.branch); git pull" 'Yellow'
            Say ''
        }
    }
} else {
    Say '  no bundle given - starting with an empty notebook' 'Yellow'
}

# --------------------------------------------------------------- 3. secrets
if ($restore -and (Test-Path (Join-Path $restore '.env'))) {
    if ((Test-Path (Join-Path $root '.env')) -and -not $Force) {
        Say '  .env already here, keeping it (-Force to overwrite)' 'Yellow'
    } else {
        Copy-Item (Join-Path $restore '.env') (Join-Path $root '.env') -Force
        Say '  restored .env' 'Green'
    }
} elseif (-not (Test-Path (Join-Path $root '.env'))) {
    if (Test-Path (Join-Path $root '.env.example')) {
        Copy-Item (Join-Path $root '.env.example') (Join-Path $root '.env') -Force
        Say '  created .env from .env.example - optional features are off' 'Yellow'
    }
}

# ------------------------------------------------------- 4. build and start
# --build, always. The image holds a frozen copy of app/ and config/, so a bare
# `up -d` on a fresh clone would build once and then never again - and every
# later pull would serve stale code with nothing to say so. Standing rule 20.
Say ''
Say '  building and starting...'
$null = Native { docker compose up -d --build }

$cid = $null
$deadline = (Get-Date).AddMinutes(3)
while ((Get-Date) -lt $deadline) {
    $cid = (Native { docker compose ps -q fishlog }) | Where-Object { $_ -match '^[0-9a-f]{12,}$' } | Select-Object -First 1
    if ($cid) { break }
    Start-Sleep -Seconds 4
}
if (-not $cid) { throw 'The container did not start. Run: docker compose logs fishlog' }
Say '  container up' 'Green'

# ------------------------------------------------------ 5. restore the data
if ($restore -and (Test-Path (Join-Path $restore 'fishlog.db'))) {

    $existing = Native {
        docker exec $cid python -c "
import sqlite3, os
db = os.environ.get('FISHLOG_DB_PATH','/data/fishlog.db')
if not os.path.exists(db): print(0); raise SystemExit
try:
    c = sqlite3.connect('file:'+db+'?mode=ro', uri=True)
    print(c.execute('select count(*) from lake').fetchone()[0])
except Exception: print(0)
"
    }
    $rows = 0
    if ($existing -match '^\d+$') { $rows = [int]($existing | Select-Object -First 1) }

    if ($rows -gt 0 -and -not $Force) {
        Say ''
        Say "  This machine already has a notebook with $rows water(s) in it." 'Yellow'
        Say '  Refusing to overwrite it. Re-run with -Force if that is what you want.' 'Yellow'
        Say ''
    } else {
        Say '  restoring the notebook...'
        # Stop first. Copying a database file under a live SQLite connection is
        # how you get a file that opens and is then subtly wrong.
        $null = Native { docker compose stop fishlog }

        # A helper container is the only way to write into a named volume while
        # the app that owns it is down.
        $null = Native { docker run --rm -v fwapp_fishlog-data:/data -v "${restore}:/b" alpine sh -c "rm -f /data/fishlog.db /data/fishlog.db-wal /data/fishlog.db-shm; cp /b/fishlog.db /data/fishlog.db; mkdir -p /data/media; cp -r /b/media/. /data/media/ 2>/dev/null; echo done" }

        $null = Native { docker compose start fishlog }
        Start-Sleep -Seconds 4
        Say '  notebook restored' 'Green'
    }
}

if ($restore) { Remove-Item $restore -Recurse -Force -ErrorAction SilentlyContinue }

# ---------------------------------------------------------------- 6. verify
# Do not declare success from having run the commands. Ask the app.
Say ''
Say '  verifying...'
$ok = $false
$deadline = (Get-Date).AddMinutes(2)
while ((Get-Date) -lt $deadline) {
    try {
        $h = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 8
        if ($h.status -eq 'ok') { $ok = $true; break }
    } catch { }
    Start-Sleep -Seconds 5
}

Say ''
if ($ok) {
    Say '  Fishlog is running: http://localhost:8000' 'Green'
    Say ''
    Say '  Next: powershell -ExecutionPolicy Bypass -File scripts\check.ps1' 'Cyan'
    Say '  That is the real test - it checks the deployment, including whether'
    Say '  the container is serving the code in this checkout.'
} else {
    Say '  Started, but /health did not answer.' 'Red'
    Say '  Look at:  docker compose logs --tail 60 fishlog' 'Yellow'
}
Say ''
