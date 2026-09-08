# Will everything come back after a restart?
#
#   powershell -ExecutionPolicy Bypass -File scripts\reboot-readiness.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\reboot-readiness.ps1 -Fix
#
# Written because installing WSL2 forces a reboot, and a reboot on a machine
# that quietly hosts other things is only safe if those things come back by
# themselves. Answer that BEFORE restarting, not after.
#
# It is deliberately not Fishlog-specific: it reports on every container on the
# box, whatever it belongs to, plus whatever is registered to start at login.
#
# The trap it exists for: a container with restart=unless-stopped still does not
# come back if DOCKER DESKTOP itself is not set to start at login. The policy
# looks correct and nothing starts, because the thing that would honour the
# policy is not running.

param([switch]$Fix)

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
function Native {
    param([scriptblock]$B)
    $p = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $o = & $B 2>$null } catch { $o = $null } finally { $ErrorActionPreference = $p }
    return $o
}

$problems = 0

# ------------------------------------------------- 1. does Docker come back?
Section "Docker Desktop starts at login?"
$startup = [Environment]::GetFolderPath('Startup')
$lnk = Join-Path $startup 'Docker Desktop.lnk'
$exe = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"

$settings = Join-Path $env:APPDATA 'Docker\settings-store.json'
$autoStart = $null
if (Test-Path $settings) {
    try { $autoStart = (Get-Content $settings -Raw | ConvertFrom-Json).AutoStart } catch { }
}

if ($autoStart -eq $true -or (Test-Path $lnk)) {
    Ok "yes - containers with a restart policy will come back on their own"
} else {
    Bad "NO. Docker Desktop does not start at login."
    Write-Host "         Every container below stays down after a reboot, whatever" -ForegroundColor DarkGray
    Write-Host "         its restart policy says - nothing is running to honour it." -ForegroundColor DarkGray
    $problems++
    if ($Fix) {
        if (Test-Path $exe) {
            # A Startup shortcut rather than editing settings-store.json:
            # Docker rewrites that file on exit, so an edit made while it runs
            # can simply vanish. A shortcut is independent of Docker entirely.
            $sh = New-Object -ComObject WScript.Shell
            $s = $sh.CreateShortcut($lnk)
            $s.TargetPath = $exe
            $s.Save()
            Ok "fixed - added Docker Desktop to Startup"
            $problems--
        } else {
            Warn "could not find $exe - fix it in Docker Desktop: Settings > General > Start Docker Desktop when you sign in"
        }
    }
}

# ------------------------------------------------ 2. per-container policies
Section "Containers"
$rows = Native { docker ps -a --format '{{.Names}}' }
if (-not $rows) {
    Note "Docker is not responding - start it, then run this again"
} else {
    foreach ($n in $rows) {
        $pol = (Native { docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' $n }) | Select-Object -First 1
        $st  = (Native { docker inspect -f '{{.State.Status}}' $n }) | Select-Object -First 1
        if ($pol -eq 'always' -or $pol -eq 'unless-stopped') {
            if ($st -eq 'running') {
                Ok ("{0,-24} {1,-9} restart={2}" -f $n, $st, $pol)
            } else {
                # unless-stopped honours a deliberate stop, so a stopped
                # container stays stopped through a reboot. That is correct
                # behaviour and still worth saying out loud, because "it has a
                # restart policy" reads as "it will come back".
                Warn ("{0,-24} {1,-9} restart={2} - stopped now, so it will NOT come back" -f $n, $st, $pol)
            }
        } else {
            Bad ("{0,-24} {1,-9} restart={2}" -f $n, $st, $pol)
            $problems++
            if ($Fix -and $st -eq 'running') {
                $null = Native { docker update --restart unless-stopped $n }
                Ok ("fixed - {0} now restart=unless-stopped" -f $n)
                $problems--
            }
        }
    }
}

# -------------------------------------------- 3. things outside Docker
# n8n, watchers, anything installed as a native process rather than a
# container. These have no restart policy at all - if they are not registered
# to start at login or as a service, a reboot simply ends them.
Section "Outside Docker (no restart policy exists for these)"

$startupItems = @()
foreach ($d in @($startup, [Environment]::GetFolderPath('CommonStartup'))) {
    if ($d -and (Test-Path $d)) {
        $startupItems += Get-ChildItem $d -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -ne 'desktop.ini' }
    }
}
if ($startupItems) {
    foreach ($i in $startupItems) { Ok "startup: $($i.Name)" }
} else {
    Note "nothing in the Startup folders"
}

$tasks = Native { schtasks /query /fo csv /nh }
$mine = $tasks | Where-Object { $_ -match 'n8n|leadfind|fishlog|watch|shop' }
if ($mine) {
    foreach ($t in $mine) { Ok ("task: " + (($t -split '","')[0] -replace '^"', '')) }
} else {
    Note "no scheduled task matching n8n / leadfind / fishlog / watch / shop"
}

Section "Node processes running right now"
$node = Get-Process node, n8n -ErrorAction SilentlyContinue
if ($node) {
    foreach ($p in $node) { Warn ("{0} (pid {1}) - running, but nothing above would restart it" -f $p.ProcessName, $p.Id) }
    Write-Host "         If one of these is n8n or a watcher, register it before rebooting:" -ForegroundColor DarkGray
    Write-Host "         a Startup shortcut, or schtasks /create /sc onlogon" -ForegroundColor DarkGray
} else {
    Note "no node/n8n process running"
}

# ------------------------------------------------------------------ verdict
Write-Host ""
if ($problems -eq 0) {
    Write-Host "  Everything running is set to come back after a restart." -ForegroundColor Green
    Write-Host "  Anything listed as stopped or 'outside Docker' is still yours to check." -ForegroundColor DarkGray
} else {
    Write-Host "  $problems thing(s) would NOT come back after a restart." -ForegroundColor Red
    if (-not $Fix) { Write-Host "  Re-run with -Fix to repair what can be repaired automatically." -ForegroundColor Yellow }
}
Write-Host ""
exit $problems
