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

# `irm ... | iex` runs piped TEXT, which the execution policy does not govern -
# which is why the one-liner works on a default machine. The moment this script
# invokes a .ps1 FILE, the policy applies again and blocks it. That is exactly
# where the first real run failed, at the last step, after WSL and Docker had
# both already succeeded.
#
# Process scope: nothing permanent, no admin needed, gone when the window
# closes. The child scripts below are ALSO launched with -ExecutionPolicy
# Bypass, because a machine-wide group policy can override the process scope
# and the failure mode is identical and just as confusing.
try { Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force -ErrorAction Stop } catch { }

function Say($t, $c = 'Gray') { Write-Host $t -ForegroundColor $c }
function Native {
    param([scriptblock]$B)
    $p = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $o = & $B 2>&1 } catch { $o = $null } finally { $ErrorActionPreference = $p }
    return $o
}


$Self = 'https://raw.githubusercontent.com/kyaraslav-cell/fwapp/claude/repository-edit-push-ggr229/scripts/bootstrap.ps1'
function Again {
    Say ''
    Say '  When it comes back, paste this again (same line, every time):' 'Cyan'
    Say ''
    Say "    irm $Self | iex" 'White'
    Say ''
}

Say ''
Say '  Fishlog' 'Cyan'
Say '  A clean Windows machine needs up to two restarts: one for WSL2,' 'DarkGray'
Say '  one for Docker. Paste the same line after each - it resumes.' 'DarkGray'
Say ''

# --------------------------------------------------------------------- 0. wsl
# Docker Desktop on Windows runs its engine inside WSL2. On a clean machine WSL
# is absent, and Docker installs happily and then refuses to start with
# "WSL is not installed" - which is a dead end unless you know to go and fix a
# prerequisite Docker never mentioned before you installed it. So check first.
#
# `wsl --install` needs Administrator and a reboot. Nothing else here does,
# which is why this is the only part that can stop and ask.
function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

$wslOk = $false
if (Get-Command wsl -ErrorAction SilentlyContinue) {
    # The wsl.exe stub ships with Windows even when the feature is off, so its
    # mere presence proves nothing - it has to be asked whether it works.
    $null = Native { wsl --status }
    if ($LASTEXITCODE -eq 0) { $wslOk = $true }
}

if (-not $wslOk) {
    Say '  Docker needs WSL2, and it is not installed here.' 'Yellow'
    if (Test-Admin) {
        Say '  Installing WSL2...' 'Yellow'
        # --no-distribution keeps it to the engine Docker actually needs, with
        # no Ubuntu image nobody asked for. Older Windows builds reject the
        # flag, so fall back to the plain form.
        $null = Native { wsl --install --no-distribution }
        if ($LASTEXITCODE -ne 0) { $null = Native { wsl --install } }
        Say ''
        Say '  WSL2 installed.  ->  RESTART WINDOWS NOW.' 'Cyan'
        Again
        exit 0
    } else {
        Say ''
        Say '  This one step needs Administrator.' 'Cyan'
        Say ''
        Say '    1. Right-click Start  ->  Terminal (Admin)' 'Cyan'
        Say '    2. Paste:   wsl --install --no-distribution' 'White'
        Say '    3. Restart Windows.' 'Cyan'
        Say '    4. Then, in that same Admin window, paste:' 'Cyan'
        Say ''
        Say "       irm $Self | iex" 'White'
        Say ''
        Say '  Running the whole thing from an Admin window is simplest -' 'DarkGray'
        Say '  then it can install WSL itself and you never see this message.' 'DarkGray'
        Say ''
        exit 1
    }
}

# ------------------------------------------------------------------ 1. docker
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Say '  Installing Docker Desktop (a few minutes)...' 'Yellow'
    $null = Native { winget install --id Docker.DockerDesktop -e --accept-source-agreements --accept-package-agreements --silent }
    Say ''
    Say '  Docker Desktop installed.  ->  RESTART WINDOWS NOW.' 'Cyan'
    Again
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
if (-not $engine) {
    Say '  Docker did not start.' 'Red'
    Say '  Open Docker Desktop and read its error. If it says WSL is missing,' 'Yellow'
    Say '  run this in an ADMIN PowerShell, restart, and paste the line again:' 'Yellow'
    Say '    wsl --install --no-distribution' 'Yellow'
    exit 1
}
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
$installPs1 = Join-Path $Dest 'scripts\install.ps1'
$argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $installPs1)
if ($Bundle) { $argList += @('-Bundle', $Bundle) }
if ($Force)  { $argList += '-Force' }
& powershell $argList

# ------------------------------------------------------------------ 5. check
Say ''
Say '  checking...' 'Cyan'
& powershell @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $Dest 'scripts\check.ps1'))

Say ''
Say '  ------------------------------------------------------------' 'DarkGray'
Say '  Done. If the check above says PASS, the app is live.' 'Green'
Say ''
Say '  Two things left, both on the OLD machine / in a browser:' 'Cyan'
Say '    - stop the old copy:   docker compose stop fishlog' 'Cyan'
Say '      (two copies running = two notebooks drifting apart, no sync)' 'DarkGray'
Say '    - Google sign-in only: add the URL printed above in the Google' 'Cyan'
Say '      console under Credentials -> Authorised redirect URIs.' 'Cyan'
Say '      Email and password sign-in already works without this.' 'DarkGray'
Say ''
