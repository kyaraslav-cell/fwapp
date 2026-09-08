# Packs this Fishlog installation into one bundle for another PC.
#
#   powershell -ExecutionPolicy Bypass -File scripts\pack.ps1
#
# What has to move, and why each part:
#
#   fishlog.db      the notebook. Sessions, catches, waters, and 77k hours of
#                   weather observations that took real calendar time to
#                   accumulate and cannot be backfilled for free.
#   fishlog.db-wal  SQLite runs in WAL mode, so the most recent writes live in
#                   the sidecar and NOT in the .db file. Copying the .db alone
#                   silently loses whatever happened most recently - LeadFind
#                   learned this the same way with n8n's sqlite.
#   media/          catch photos, inside the volume.
#   .env            the API keys the app reads at runtime.
#
# What does NOT travel: the repository. It is public, so the other machine
# clones it. That is the whole difference from the LeadFind bundle, which had
# to carry a private repo and came out at 128 MB; this one is about 25 MB.
#
# The bundle contains live API keys AND another person's fishing notebook -
# there is a second real user on this database. It is written outside the repo,
# must never be committed, and should travel by USB or local network.

$ErrorActionPreference = 'Stop'

$root  = Split-Path $PSScriptRoot -Parent
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$out   = Join-Path $env:USERPROFILE "fishlog-bundle-$stamp"
$zip   = "$out.zip"

function Say($t, $c = 'Gray') { Write-Host $t -ForegroundColor $c }
function Native {
    param([scriptblock]$Block)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $o = & $Block 2>$null } catch { $o = $null } finally { $ErrorActionPreference = $prev }
    return $o
}

Say ''
Say '  Packing Fishlog' 'Cyan'
Say ''

if (-not (Native { docker info --format '{{.ServerVersion}}' })) {
    throw 'Docker is not running. Start Docker Desktop and try again.'
}

$cid = (Native { docker compose ps -q fishlog }) | Select-Object -First 1
if (-not $cid) { throw 'The fishlog container is not running. Run: docker compose up -d' }

New-Item -ItemType Directory -Force -Path $out | Out-Null

# ------------------------------------------------------------- 1. the notebook
# Copied through SQLite's own backup API rather than by copying files. A live
# WAL database copied file-by-file can land mid-transaction; .backup takes a
# consistent snapshot of a database that is still being written to, and folds
# the WAL in, so the result is one self-contained file with nothing left in a
# sidecar to forget.
Say '  snapshotting the notebook (consistent, WAL folded in)...'
# Python is piped in on stdin rather than passed with -c. Nesting quotes
# through PowerShell -> docker exec -> python loses a layer somewhere every
# time; a here-string on stdin has none to lose. The verify step below failed
# for exactly that reason on the first run, and reported a good snapshot as
# corrupt - which is the worst possible direction for a backup tool to be
# wrong in.
$snapshot = @'
import sqlite3, os
src = os.environ.get('FISHLOG_DB_PATH', '/data/fishlog.db')
s = sqlite3.connect('file:' + src + '?mode=ro', uri=True)
d = sqlite3.connect('/tmp/fishlog-snapshot.db')
s.backup(d)
d.close()
s.close()
print('ok')
'@
$null = Native { $snapshot | docker exec -i $cid python - }
$null = Native { docker cp "${cid}:/tmp/fishlog-snapshot.db" (Join-Path $out 'fishlog.db') }
$null = Native { docker exec $cid rm -f /tmp/fishlog-snapshot.db }

if (-not (Test-Path (Join-Path $out 'fishlog.db'))) { throw 'The database snapshot failed - nothing was written.' }

# Verify the snapshot before trusting it. A corrupt backup that nobody opened
# until restore day is worse than no backup, because it was believed.
# immutable=1, not just mode=ro. A plain read-only open of a WAL database still
# creates -shm and -wal beside it, so the first version of this quietly wrote two
# sidecars INTO the bundle it was checking. Harmless here, but a verify step that
# modifies what it verifies is a bad habit to leave in a backup tool.
$check = @'
import sqlite3
c = sqlite3.connect('file:/b/fishlog.db?immutable=1', uri=True)
print(c.execute('pragma integrity_check').fetchone()[0])
print(c.execute("select count(*) from sqlite_master where type='table'").fetchone()[0], 'tables')
'@
$verify = Native { $check | docker run --rm -i -v "${out}:/b" python:3.12-slim python - }

if ($verify -match 'ok') { Say "  snapshot verified: $($verify -join ', ')" 'Green' }
else { throw "The snapshot failed its integrity check: $verify" }

# ------------------------------------------------------------------ 2. media
Say '  copying catch photos...'
$mediaOut = Join-Path $out 'media'
New-Item -ItemType Directory -Force -Path $mediaOut | Out-Null
$null = Native { docker cp "${cid}:/data/media/." $mediaOut }
$photos = @(Get-ChildItem $mediaOut -Recurse -File -ErrorAction SilentlyContinue).Count
# Compress-Archive silently drops an empty directory, so with no photos yet the
# bundle would contain no media/ at all and the restore's `cp -r /b/media/.`
# would fail into /dev/null. A marker file keeps the shape constant either way.
if ($photos -eq 0) { Set-Content (Join-Path $mediaOut '.keep') '' -Encoding ascii }
Say "  $photos photo(s)"

# ---------------------------------------------------------------- 3. secrets
if (Test-Path (Join-Path $root '.env')) {
    Copy-Item (Join-Path $root '.env') (Join-Path $out '.env') -Force
    Say '  copied .env'
} else {
    Say '  no .env - the app will run with every optional feature off' 'Yellow'
}

# ------------------------------------------------------------- 4. provenance
# Pin the commit. Restoring a notebook onto a much older or newer checkout is
# how a schema mismatch happens, and migrations here are forward-only.
$commit = (Native { git -C $root rev-parse HEAD }) | Select-Object -First 1
$branch = (Native { git -C $root rev-parse --abbrev-ref HEAD }) | Select-Object -First 1
$remote = (Native { git -C $root remote get-url origin }) | Select-Object -First 1
$dirty  = (Native { git -C $root status --porcelain }) | Measure-Object | Select-Object -ExpandProperty Count

@{
    packed      = (Get-Date).ToString('s')
    from        = $env:COMPUTERNAME
    commit      = $commit
    branch      = $branch
    repo        = $remote
    uncommitted = $dirty
    photos      = $photos
} | ConvertTo-Json | Out-File (Join-Path $out 'bundle.json') -Encoding utf8

if ($dirty -gt 0) {
    Say ''
    Say "  WARNING: $dirty uncommitted change(s) in the working tree." 'Yellow'
    Say '  The other machine clones the repo, so those changes will NOT travel.' 'Yellow'
    Say '  Commit and push first if you want them.' 'Yellow'
}

# -------------------------------------------------------------------- 5. zip
Say ''
Say '  compressing...'
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $out '*') -DestinationPath $zip -CompressionLevel Optimal
Remove-Item $out -Recurse -Force

$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)

Say ''
Say "  Done: $zip  ($mb MB)" 'Green'
Say ''
Say '  On the other PC:' 'Cyan'
Say "    git clone $remote fwapp"
Say '    cd fwapp'
Say "    powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Bundle <path to the zip>"
Say ''
Say '  Contains live API keys and a second person''s fishing notebook.' 'Yellow'
Say '  Move it by USB or local network. Not by email or cloud storage.' 'Yellow'
Say '  Delete it from both machines once the restore is verified.' 'Yellow'
Say ''
