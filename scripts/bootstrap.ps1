# One line. Paste it into PowerShell on the new PC and walk away.
#
#   irm https://raw.githubusercontent.com/kyaraslav-cell/fwapp/claude/repository-edit-push-ggr229/scripts/bootstrap.ps1 | iex
#
# Installs Docker if it is missing, fetches the app, finds the bundle by itself,
# restores the notebook, starts it, puts it on a public URL, and checks it.
#
# TWO RULES THIS SCRIPT IS BUILT AROUND, both learned the expensive way:
#
# 1. IT NEVER MAKES A BUNDLE, AND NEVER NEEDS A FRESH ONE. It finds whatever
#    bundle is already on the machine - USB stick, Downloads, home folder - and
#    reuses it. Re-packing for every attempt is how LeadFind lost an afternoon:
#    each test started with a slow rebuild, and when the result looked wrong
#    nobody could tell whether the fix was bad or the deploy had simply not
#    replaced anything. One bundle, reused, removes that whole question.
#
# 2. IT IS SAFE AND FAST TO RE-RUN. Docker already there, repo already cloned,
#    notebook already restored: each is detected and skipped. Re-running is the
#    normal way to continue after the Docker reboot, so it must never be the
#    thing that destroys the notebook. It refuses to overwrite an existing one
#    unless you pass -Force.

param(
    # Only needed if the bundle is somewhere unusual. Normally it is found.
    [string]$Bundle,
    # Overwrite a notebook that is already on this machine. No undo.
    [switch]$Force,
    [string]$Repo   = 'https://github.com/kyaraslav-cell/fwapp.git',
    [string]$Branch = 'claude/repository-edit-push-ggr229',
    [string]$Dest   = (Join-Path $env:USERPROFILE 'fwapp')
)

$ErrorActionPreference = 'Stop'
function Say($t, $c = 'Gray') { Write-Host $t -ForegroundColor $c }
function Native {
    param([scriptblock]$B)
    $p = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $o = & $B 2>&1 } catch { $o = $null } finally { $ErrorActionPreference = $p }
    return $o
}

Say ''
Say '  Fishlog' 'Cyan'
Say ''

# ------------------------------------------------------------------ 1. docker
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Say '  Installing Docker Desktop (a few minutes)...' 'Yellow'
    $null = Native { winget install --id Docker.DockerDesktop -e --accept-source-agreements --accept-package-agreements --silent }
    Say ''
    Say '  Docker needs a restart before it can run.' 'Yellow'
    Say '  Restart Windows, then paste the same line again - it carries on' 'Yellow'
    Say '  from here and skips everything already done.' 'Yellow'
    Say ''
    exit 0
}

Say '  waiting for Docker...'
$deadline = (Get-Date).AddMinutes(5)
$engine = $null
while ((Get-Date) -lt $deadline) {
    $engine = (Native { docker info --format '{{.ServerVersion}}' }) | Where-Object { $_ -match '^\d' } | Select-Object -First 1
    if ($engine) { break }
    # Docker Desktop does not start itself after a fresh install.
    if (-not (Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue)) {
        $exe = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
        if (Test-Path $exe) { Start-Process $exe }
    }
    Start-Sleep -Seconds 6
}
if (-not $engine) { Say '  Docker did not start. Open Docker Desktop, then paste the line again.' 'Red'; exit 1 }
Say "  Docker ready ($engine)" 'Green'

# -------------------------------------------------------------------- 2. app
# git if it is here, a plain zip download if it is not - so Git is never
# something to install first.
if (Test-Path (Join-Path $Dest '.git')) {
    Say '  updating the app...'
    $null = Native { git -C $Dest fetch origin $Branch }
    $null = Native { git -C $Dest checkout $Branch }
    $null = Native { git -C $Dest pull --ff-only origin $Branch }
} elseif (Test-Path (Join-Path $Dest 'docker-compose.yml')) {
    Say '  app already here'
} elseif (Get-Command git -ErrorAction SilentlyContinue) {
    Say '  downloading the app...'
    $null = Native { git clone --branch $Branch $Repo $Dest }
} else {
    Say '  downloading the app...'
    $zipUrl = ($Repo -replace '\.git$', '') + "/archive/refs/heads/$Branch.zip"
    $tmpZip = Join-Path $env:TEMP 'fwapp.zip'
    Invoke-WebRequest $zipUrl -OutFile $tmpZip -UseBasicParsing
    $stage = Join-Path $env:TEMP 'fwapp-stage'
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
    Expand-Archive $tmpZip -DestinationPath $stage -Force
    $inner = Get-ChildItem $stage -Directory | Select-Object -First 1
    if (-not (Test-Path $Dest)) { New-Item -ItemType Directory -Force -Path $Dest | Out-Null }
    Copy-Item (Join-Path $inner.FullName '*') $Dest -Recurse -Force
    Remove-Item $stage -Recurse -Force
    Remove-Item $tmpZip -Force
}
if (-not (Test-Path (Join-Path $Dest 'docker-compose.yml'))) { throw "Could not fetch the app into $Dest" }
Set-Location $Dest
Say "  app in $Dest" 'Green'

# ----------------------------------------------------------------- 3. bundle
# Found, never made. Looks where a bundle actually ends up: a USB stick you
# just plugged in, the Downloads folder, the home folder.
if (-not $Bundle) {
    Say '  looking for a bundle...'
    $places = @()
    Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue |
        Where-Object { $_.Root -match '^[A-Z]:\\$' } |
        ForEach-Object { $places += $_.Root }
    $places += (Join-Path $env:USERPROFILE 'Downloads')
    $places += $env:USERPROFILE

    $found = @()
    foreach ($p in ($places | Select-Object -Unique)) {
        if (-not (Test-Path $p)) { continue }
        $found += Get-ChildItem -Path $p -Filter 'fishlog-bundle-*.zip' -File -ErrorAction SilentlyContinue
    }
    $pick = $found | Sort-Object LastWriteTime -Descending | Select-Object -First 1

    if ($pick) {
        $Bundle = $pick.FullName
        Say "  found: $Bundle" 'Green'
        if ($found.Count -gt 1) { Say "  ($($found.Count) bundles present - using the newest)" 'DarkGray' }
    } else {
        Say '  no bundle found - starting with an empty notebook' 'Yellow'
        Say '  (make one on the old PC:  scripts\pack.ps1)' 'DarkGray'
    }
}

# ---------------------------------------------------------------- 4. install
# NOT $args - that is a PowerShell automatic variable and splatting it does
# not do what it looks like it does.
$installArgs = @{}
if ($Bundle) { $installArgs['Bundle'] = $Bundle }
if ($Force)  { $installArgs['Force']  = $true }
& (Join-Path $Dest 'scripts\install.ps1') @installArgs

# ------------------------------------------------------------------ 5. check
Say ''
Say '  checking...' 'Cyan'
& (Join-Path $Dest 'scripts\check.ps1')
