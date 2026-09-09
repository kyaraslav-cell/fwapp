# Full-chain diagnosis: test every link, and leave evidence for the next fall.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\doctor.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\doctor.ps1 -Ping
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\doctor.ps1 -Quiet   # for a scheduled run
#
# `check.ps1` answers "did the deploy land". This answers "why did it fall over,
# and which link is about to". Three differences, each one a fault that already
# happened here:
#
#   1. It reads the environment INSIDE the container, not `.env` on the host.
#      Those are different things - `.env` is not copied into the image - and
#      believing the host copy is how the heartbeat sat unset for a day while
#      every check reported it configured.
#
#   2. It TESTS paths rather than reading state. Egress to the monitor is tried
#      from inside the container, not inferred from a variable being present.
#
#   3. It collects post-mortem evidence: restart count, OOM kills, the exit
#      code of the previous run, errors since the container started, and when
#      Windows last rebooted unexpectedly. An app that fell and recovered
#      leaves nothing behind otherwise, which is why "it fell again" has been
#      unanswerable every time.
#
# Every run appends a verdict line to logs\doctor-history.txt and writes the
# full report to logs\doctor-<timestamp>.txt, so a pattern across falls is
# readable instead of remembered.
#
# Nothing here writes to the notebook, restarts anything, or pings the real
# monitor unless -Ping is given.

param(
    [switch]$Ping,
    [switch]$Quiet,
    [string]$RepoDir
)

$ErrorActionPreference = 'Continue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

# ------------------------------------------------------------------ plumbing
$script:fails = 0
$script:warns = 0
$script:lines = New-Object System.Collections.ArrayList

function Emit($text, $colour) {
    $null = $script:lines.Add($text)
    if (-not $Quiet) { Write-Host $text -ForegroundColor $colour }
}
function Section($t) {
    Emit "" 'Gray'
    Emit ("== $t " + ("=" * [Math]::Max(2, 58 - $t.Length))) 'Cyan'
}
function Ok($t)   { Emit "  [ok]   $t" 'Green' }
function Bad($t)  { Emit "  [FAIL] $t" 'Red';    $script:fails++ }
function Warn($t) { Emit "  [warn] $t" 'Yellow'; $script:warns++ }
function Note($t) { Emit "  [--]   $t" 'DarkGray' }

# PowerShell 5.1 turns a native command's stderr into an ErrorRecord, and
# docker writes there whenever the daemon is down - precisely the case being
# tested. Every docker call goes through this.
function Native {
    param([scriptblock]$B)
    $p = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $o = & $B 2>$null } catch { $o = $null } finally { $ErrorActionPreference = $p }
    return $o
}

# `docker logs` must NOT go through Native. Python's logging writes to stderr,
# so almost every line the app emits arrives on that stream - and Native
# discards it. The first version of this script reported "no heartbeat line in
# the log" and "no ingest activity" against a container that was logging both,
# which is the exact false alarm this script exists to stop.
#
# The redirection is done by cmd, not PowerShell: `2>&1` on a native command in
# 5.1 wraps each stderr line in an ErrorRecord and can set $? to false on a
# perfectly successful call.
function DockerLogs {
    param([string]$Container, [int]$Tail = 3000)
    try { return @(cmd /c "docker logs --tail $Tail $Container 2>&1") } catch { return @() }
}

if (-not $RepoDir) {
    $RepoDir = @(
        (Split-Path $PSScriptRoot -Parent),
        'C:\Users\admin\fwapp',
        (Join-Path $env:USERPROFILE 'fwapp')
    ) | Where-Object { $_ -and (Test-Path (Join-Path $_ 'docker-compose.yml')) } | Select-Object -First 1
}
if (-not $RepoDir) {
    Write-Host "  no checkout found - pass -RepoDir C:\path\to\fwapp" -ForegroundColor Red
    exit 1
}
$RepoDir = (Resolve-Path $RepoDir).Path
Set-Location $RepoDir

Emit "Fishlog doctor - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  on $env:COMPUTERNAME" 'White'
Emit "  repo: $RepoDir" 'DarkGray'

# ------------------------------------------------------------- 1. the machine
# First, because everything below is a consequence when this is the answer.
Section "The machine"
try {
    $os = Get-CimInstance Win32_OperatingSystem
    $up = (Get-Date) - $os.LastBootUpTime
    $bootMsg = "up {0:N1} h (booted {1:yyyy-MM-dd HH:mm})" -f $up.TotalHours, $os.LastBootUpTime
    if ($up.TotalHours -lt 1) { Warn "$bootMsg - a recent reboot explains an outage all by itself" }
    else { Ok $bootMsg }
} catch { Note "could not read boot time" }

try {
    # 6008 = the previous shutdown was unexpected. 41 = the kernel did not shut
    # down cleanly. Either one, timed near a fall, IS the answer.
    $ev = Get-WinEvent -FilterHashtable @{LogName='System'; Id=@(41,6008); StartTime=(Get-Date).AddDays(-7)} -ErrorAction Stop |
          Select-Object -First 5
    if ($ev) {
        Warn "$($ev.Count) unexpected shutdown/power event(s) in the last 7 days:"
        foreach ($e in $ev) { Note ("  {0:yyyy-MM-dd HH:mm}  id {1}" -f $e.TimeCreated, $e.Id) }
    } else { Ok "no unexpected shutdowns in the last 7 days" }
} catch { Note "could not read the System event log (needs admin on some machines)" }

try {
    $drive = Get-PSDrive -Name ($RepoDir.Substring(0,1)) -ErrorAction Stop
    $freeGb = [Math]::Round($drive.Free / 1GB, 1)
    # SQLite cannot write on a full disk, and the failure is ugly and late.
    if ($freeGb -lt 2)      { Bad  "only $freeGb GB free - SQLite writes will start failing" }
    elseif ($freeGb -lt 10) { Warn "$freeGb GB free - getting tight" }
    else                    { Ok   "$freeGb GB free" }
} catch { Note "could not read free space" }

# ------------------------------------------------------------- 2. docker
Section "Docker"
$ver = (Native { docker info --format '{{.ServerVersion}}' }) | Select-Object -First 1
if (-not $ver) {
    Bad "engine not responding - Docker Desktop is not running"
    Note "everything below depends on it; start Docker Desktop and run this again"
    Note "if this follows a reboot, check: scripts\reboot-readiness.ps1"
} else {
    Ok "engine up ($ver)"
}

$cid = $null
if ($ver) {
    $cid = (Native { docker compose ps -q fishlog }) | Where-Object { $_ -match '^[0-9a-f]{12,}$' } | Select-Object -First 1
    if (-not $cid) {
        Bad "the fishlog container does not exist - run: docker compose up -d --build"
    } else {
        $insp = (Native { docker inspect -f '{{.State.Status}}|{{.State.StartedAt}}|{{.RestartCount}}|{{.State.OOMKilled}}|{{.State.ExitCode}}|{{.HostConfig.RestartPolicy.Name}}' $cid }) | Select-Object -First 1
        $st, $started, $restarts, $oom, $exitCode, $policy = $insp -split '\|', 6

        if ($st -eq 'running') { Ok "container running" } else { Bad "container is '$st'" }

        try {
            $age = (Get-Date) - [DateTime]::Parse($started)
            $script:containerAgeMin = $age.TotalMinutes
            # THE post-mortem line. A container that "is running" but started
            # ten minutes ago fell over ten minutes ago.
            if ($age.TotalHours -lt 1) {
                Warn ("started only {0:N0} min ago - it restarted recently, which is the fall you are asking about" -f $age.TotalMinutes)
            } else {
                Ok ("running for {0:N1} h" -f $age.TotalHours)
            }
        } catch { Note "could not parse the start time" }

        if ([int]$restarts -gt 0) { Warn "docker has restarted it $restarts time(s) - a crash loop leaves this above zero" }
        else { Ok "restart count 0" }

        if ($oom -eq 'true') { Bad "LAST RUN WAS OOM-KILLED - the container ran out of memory" }
        if ($exitCode -and $exitCode -ne '0') { Warn "last exit code $exitCode" }

        if ($policy -eq 'unless-stopped' -or $policy -eq 'always') { Ok "restart policy: $policy" }
        else { Bad "restart policy is '$policy' - it will not come back on its own" }
    }
}

# --------------------------------------------------- 3. inside the container
# The section check.ps1 does not have, and the reason this script exists.
Section "Environment INSIDE the container"
if (-not $cid) { Note "skipped - no container" }
else {
    $envOut = Native { docker exec $cid printenv }
    if (-not $envOut) {
        Bad "could not read the container's environment"
    } else {
        $inside = @{}
        foreach ($l in $envOut) { $k, $v = $l -split '=', 2; if ($k) { $inside[$k] = $v } }

        # Read from .env on the host, then assert each one actually arrived.
        # A variable set in .env and absent from docker-compose.yml's
        # environment block never reaches the process, and every host-side
        # check calls it configured. That is the whole 2026-09-09 fault.
        $envFile = Join-Path $RepoDir '.env'
        $onHost = @{}
        if (Test-Path $envFile) {
            foreach ($l in (Get-Content $envFile)) {
                $t = $l.Trim()
                if ($t.StartsWith('#') -or -not $t.Contains('=')) { continue }
                $k, $v = $t -split '=', 2
                $v = $v.Trim().Trim('"').Trim("'")
                if ($v) { $onHost[$k.Trim()] = $v }
            }
        }

        # Build-time and host-only settings that correctly never travel. Kept
        # in step with tests/test_compose_passes_env.py's EXEMPT, which is the
        # authority; this list only stops the report crying wolf about them.
        $hostOnly = @{
            'KIE_AI_API_KEY'          = 'build-time only - the app never calls kie.ai at runtime'
            'FISHLOG_HEARTBEAT_URL'   = 'read by scripts\heartbeat.ps1 on the host, not by the app'
            'FISHLOG_FRAME_ANCESTORS' = 'dev-container preview panes only, never on a deployment'
        }

        if ($onHost.Count -eq 0) { Note "nothing set in .env - all optional features are off" }
        foreach ($k in ($onHost.Keys | Sort-Object)) {
            if ($inside.ContainsKey($k) -and $inside[$k]) {
                Ok "$k reaches the container"
            } elseif ($hostOnly.ContainsKey($k)) {
                Note "$k stays on the host - $($hostOnly[$k])"
            } else {
                Bad "$k is in .env but NOT inside the container"
                Note "  add it to docker-compose.yml's environment block, then: docker compose up -d --build"
            }
        }
    }
}

# ------------------------------------------------------------- 4. the app
Section "The app answers"
if (-not $cid) { Note "skipped - no container" }
else {
    try {
        $h = Invoke-RestMethod "http://127.0.0.1:8000/health" -TimeoutSec 15
        if ($h.status -eq 'ok') { Ok "local /health ok - newest observation $($h.age_hours) h old" }
        elseif ($h.status -eq 'stale') { Bad "local /health says STALE - $($h.detail). The app serves, the weather is old." }
        else { Bad "local /health says '$($h.status)' - $($h.detail)" }

        if ($h.unresolved_gaps -gt 0) {
            Warn "$($h.unresolved_gaps) unresolved ingest gap(s) - close the covered ones: tools\resolve_gaps.py"
        } else { Ok "no unresolved ingest gaps" }
    } catch {
        Bad "the app does not answer on 127.0.0.1:8000 ($($_.Exception.Message))"
    }
}

# ------------------------------------------------- 5. is anything watching?
Section "Monitoring"
$monUrl = $null
if ($cid -and $inside) { $monUrl = $inside['FISHLOG_HEALTHCHECK_URL'] }

if (-not $cid) {
    # Not a failure of its own - it is the container's absence, already
    # reported above. Cascaded FAILs train the reader to skim past the one
    # line that matters.
    Note "skipped - no container"
} elseif (-not $monUrl) {
    Bad "FISHLOG_HEALTHCHECK_URL is not set inside the container - NOTHING is watching this app"
    Note "  that is why a fall goes unnoticed until you look. Set it in .env AND"
    Note "  make sure docker-compose.yml passes it through."
} else {
    Ok "monitor configured (…$($monUrl.Substring([Math]::Max(0, $monUrl.Length - 6))))"

    # Test egress from INSIDE the container - the only place it matters - by
    # reaching the ping host's root rather than the check's own URL. Touching
    # the real check would mark it "up" and could mask a genuine outage for
    # the grace period; this proves DNS, TLS and egress without lying to it.
    $probe = @'
import os, sys, urllib.parse, httpx
u = os.environ.get("FISHLOG_HEALTHCHECK_URL", "")
host = urllib.parse.urlsplit(u)
root = host.scheme + "://" + host.netloc + "/"
try:
    r = httpx.get(root, timeout=10.0)
    print("REACHABLE %s %s" % (host.netloc, r.status_code))
except Exception as e:
    print("UNREACHABLE %s %s" % (host.netloc, type(e).__name__))
'@
    $res = (Native { $probe | docker exec -i $cid python - }) | Select-Object -First 1
    if ($res -like 'REACHABLE*') { Ok "the container can reach the monitor ($res)" }
    elseif ($res -like 'UNREACHABLE*') { Bad "the container CANNOT reach the monitor ($res)" }
    else { Warn "could not test egress from the container" }

    # Did the app itself say it was reporting, at startup?
    $logs = DockerLogs $cid 2000
    $hb = $logs | Select-String -Pattern 'heartbeat:' | Select-Object -Last 3
    if ($hb) { foreach ($l in $hb) { Note ("  " + $l.Line.Trim()) } }
    else { Warn "no heartbeat line in the log - the scheduler may not have started" }

    if ($Ping) {
        # Opt-in, because it marks the check "up" for real.
        #
        # Sent from INSIDE the container, through the same httpx the app uses.
        # The first version sent it from the host, which tests a different
        # network path entirely: the host can reach a monitor the container
        # cannot, and the reverse. A test that does not travel the real path
        # proves nothing about the thing that actually pings.
        # NOT $ping: `[switch]$Ping` in the param block is a TYPE-CONSTRAINED
        # variable and PowerShell is case-insensitive, so assigning this
        # here-string to $ping silently coerced it to a SwitchParameter and
        # piped nothing into python. The probe then "failed" with an empty
        # error message while working perfectly by hand.
        $pingProbe = @'
import os, httpx
u = os.environ.get("FISHLOG_HEALTHCHECK_URL", "")
try:
    r = httpx.post(u, content=b"doctor test ping", timeout=15.0)
    print("SENT %s" % r.status_code)
except Exception as e:
    print("REFUSED %s: %s" % (type(e).__name__, e))
'@
        $res = (Native { $pingProbe | docker exec -i $cid python - }) | Select-Object -First 1
        if ($res -like 'SENT*') { Ok "test ping accepted by the monitor ($res) - sent from inside the container" }
        else { Bad "test ping failed from inside the container: $res" }
    } else {
        Note "not pinging the real check (pass -Ping to send one deliberately)"
    }
}

# ------------------------------------------------------- 6. the scheduler
Section "Background jobs"
if (-not $cid) { Note "skipped - no container" }
else {
    $logs = DockerLogs $cid 3000
    $ingest = $logs | Select-String -Pattern 'ingest|openmeteo|weather' | Select-Object -Last 2
    if ($ingest) {
        foreach ($l in $ingest) { Note ("  " + $l.Line.Trim()) }
    } elseif ($script:containerAgeMin -lt 65) {
        # Ingest is hourly, at minute 5. A container younger than one full hour
        # may legitimately not have run it yet, and warning here would fire on
        # every restart - training the reader to ignore the one that matters.
        Note "no ingest yet - the container is too young for the hourly job to have run"
    } else {
        Warn "no ingest activity in the recent log - APScheduler may be dead while uvicorn serves on"
    }

    # The quiet killer: uvicorn keeps answering, the scheduler thread is gone,
    # and every page renders last week's weather. /health catches it eventually
    # via age_hours; this catches it in the log first.
    $tracebacks = $logs | Select-String -Pattern 'Traceback|CRITICAL|Unhandled' | Select-Object -Last 5
    if ($tracebacks) {
        Warn "$($tracebacks.Count) error(s) in the recent log:"
        foreach ($l in $tracebacks) { Note ("  " + $l.Line.Trim()) }
    } else { Ok "no tracebacks in the recent log" }
}

# ---------------------------------------------------------- 7. code drift
Section "Is the container running THIS code?"
if (-not $cid) { Note "skipped - no container" }
else {
    $local = (Native { git -C $RepoDir rev-parse --short HEAD }) | Select-Object -First 1
    $behind = (Native { git -C $RepoDir rev-list --count "HEAD..@{u}" }) | Select-Object -First 1
    if ($local) { Note "working tree at $local" }
    if ($behind -and [int]$behind -gt 0) {
        Warn "the checkout is $behind commit(s) behind the branch - run scripts\update.ps1"
    }

    # Per-file sha256 on both sides, globally sorted, exactly as check.ps1 does
    # it. Lifted rather than reinvented: the first version here hashed a single
    # stream, walking the container with os.walk (which sorts only within a
    # directory) against a globally sorted host list. Those two orderings
    # disagree on identical code, so it would have reported drift forever - and
    # an alarm that is always on is one nobody reads.
    function TreeHash($files) {
        $sb = New-Object System.Text.StringBuilder
        foreach ($f in ($files | Sort-Object)) { [void]$sb.AppendLine($f) }
        $md5 = [System.Security.Cryptography.MD5]::Create()
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($sb.ToString())
        ([BitConverter]::ToString($md5.ComputeHash($bytes)) -replace '-', '').Substring(0, 12)
    }

    $insideRaw = Native {
        docker exec $cid sh -c "cd /srv/fishlog && find app config -type f ! -name '*.pyc' ! -path '*__pycache__*' -exec sha256sum {} \; | sed 's#  #|#' | sort"
    }

    if (-not $insideRaw) {
        Warn "could not read app/ and config/ out of the container"
    } else {
        $insideList = @()
        foreach ($l in $insideRaw) {
            if ($l -match '^([0-9a-f]{64})\|(.+)$') { $insideList += ($matches[2] + ' ' + $matches[1]) }
        }
        $outsideList = @()
        foreach ($d in @('app', 'config')) {
            $dir = Join-Path $RepoDir $d
            if (-not (Test-Path $dir)) { continue }
            Get-ChildItem -Path $dir -Recurse -File |
                Where-Object { $_.Extension -ne '.pyc' -and $_.FullName -notmatch '__pycache__' } |
                ForEach-Object {
                    $rel = $_.FullName.Substring($RepoDir.Length + 1).Replace('\', '/')
                    $outsideList += ($rel + ' ' + (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower())
                }
        }

        $a = TreeHash $insideList
        $b = TreeHash $outsideList
        if ($a -eq $b) {
            Ok "container matches the working tree ($($insideList.Count) files, $a)"
        } else {
            Bad "DRIFT - the container is serving different code from the working tree"
            Note "  image $a vs tree $b"
            $inMap = @{}; foreach ($e in $insideList)  { $p, $s = $e -split ' ', 2; $inMap[$p]  = $s }
            $outMap = @{}; foreach ($e in $outsideList) { $p, $s = $e -split ' ', 2; $outMap[$p] = $s }
            $shown = 0
            foreach ($p in (($outMap.Keys + $inMap.Keys) | Sort-Object -Unique)) {
                if ($shown -ge 8) { Note "  ..."; break }
                if (-not $inMap.ContainsKey($p))      { Note "  + $p (only in tree)";  $shown++ }
                elseif (-not $outMap.ContainsKey($p)) { Note "  - $p (only in image)"; $shown++ }
                elseif ($inMap[$p] -ne $outMap[$p])   { Note "  ~ $p";                 $shown++ }
            }
            Note "  Fix: docker compose up -d --build (a restart will NOT pick it up)"
        }
    }
}

# ------------------------------------------------------------ 8. public URL
Section "Public URL"
function Find-Tailscale {
    $cmd = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($c in @(
        "$env:ProgramFiles\Tailscale\tailscale.exe",
        "${env:ProgramFiles(x86)}\Tailscale\tailscale.exe",
        "$env:ProgramFiles\Tailscale IPN\tailscale.exe",
        "$env:LOCALAPPDATA\Tailscale\tailscale.exe")) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    return $null
}
$tsExe = Find-Tailscale
if (-not $tsExe) {
    Note "tailscale not found - local only"
} else {
    $fs = Native { & $tsExe funnel status }
    if ($fs -match 'https://') {
        $pub = ($fs | Select-String -Pattern 'https://\S+' | Select-Object -First 1).Matches.Value.TrimEnd('/')
        Ok "funnel on: $pub"
        try {
            $r = Invoke-RestMethod "$pub/health" -TimeoutSec 25
            if ($r.status -eq 'ok') { Ok "reachable from the internet, /health ok" }
            else { Bad "public /health says '$($r.status)'" }
        } catch { Bad "the public URL does not answer ($($_.Exception.Message))" }
    } else {
        Bad "no funnel - the app is not on a public URL"
        Note "  turn it on with: tailscale funnel --bg 8000"
    }
}

# ------------------------------------------------------------- 9. verdict
Section "Verdict"
if ($script:fails -eq 0 -and $script:warns -eq 0) {
    Emit "  HEALTHY - every link tested and passing." 'Green'
} elseif ($script:fails -eq 0) {
    Emit "  OK with $($script:warns) warning(s) - read them, nothing is broken yet." 'Yellow'
} else {
    Emit "  $($script:fails) FAILURE(S), $($script:warns) warning(s)." 'Red'
    Emit "" 'Gray'
    Emit "  Read the first [FAIL] above, not the last: they cascade." 'DarkGray'
    Emit "  Docker down -> everything fails. Container missing -> everything below it fails." 'DarkGray'
}

# Evidence, because a fall that recovered leaves nothing otherwise.
$logDir = Join-Path $RepoDir 'logs'
try {
    if (-not (Test-Path $logDir)) { $null = New-Item -ItemType Directory -Path $logDir -Force }
    $stamp = Get-Date -Format 'yyyy-MM-dd-HHmmss'
    $report = Join-Path $logDir "doctor-$stamp.txt"
    [IO.File]::WriteAllLines($report, $script:lines, (New-Object Text.UTF8Encoding($false)))

    $verdict = "{0}  fails={1} warns={2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $script:fails, $script:warns
    Add-Content -Path (Join-Path $logDir 'doctor-history.txt') -Value $verdict -Encoding UTF8

    Emit "" 'Gray'
    Emit "  Report: $report" 'DarkGray'
    Emit "  History: logs\doctor-history.txt - one line per run, so a pattern is readable." 'DarkGray'

    # Keep the last 30 reports. A directory nobody prunes is one nobody opens.
    Get-ChildItem $logDir -Filter 'doctor-*.txt' -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne 'doctor-history.txt' } |
        Sort-Object LastWriteTime -Descending | Select-Object -Skip 30 |
        Remove-Item -Force -ErrorAction SilentlyContinue
} catch {
    Emit "  (could not write the report: $($_.Exception.Message))" 'DarkGray'
}

Emit "" 'Gray'
exit $script:fails
