# Dead-man's switch for an unattended Fishlog on Windows.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\heartbeat.ps1 -Install -PingUrl https://hc-ping.com/<uuid>
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\heartbeat.ps1            # run one check now
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\heartbeat.ps1 -Status
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\heartbeat.ps1 -Uninstall
#
# The Windows half of tools/heartbeat.sh, which is systemd-only and therefore
# useless on annapc. Same contract, same exit codes, same three failures.
#
# It reads the app's own /health and pings an external monitor ONLY when the app
# is genuinely healthy. Outbound rather than an uptime service polling the URL,
# because one mechanism then covers three distinct failures:
#
#   machine dead / no network   -> no ping,  the monitor alerts on the silence
#   container down or erroring  -> /fail     alerts immediately, with a reason
#   up but the weather feed is  -> /fail     the QUIET failure - the app serves
#   stale                                    perfectly and every score is old
#
# That third one is why this is not just a request to /health. Law 4 forbids
# inventing the missing hours, so a stale feed stays visibly stale forever and
# nothing else would ever complain about it.
#
# With FISHLOG_HEARTBEAT_URL unset the script exits quietly and changes nothing,
# so it is safe to install first and configure later.

param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$Status,
    [string]$PingUrl,
    [int]$EveryMinutes = 10,
    [switch]$Quiet,
    [switch]$Elevated
)

$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent
$TaskName = 'Fishlog heartbeat'

# PowerShell 5.1 negotiates TLS 1.0 by default and hc-ping.com refuses it. The
# failure surfaces as "the underlying connection was closed", which reads like a
# network fault rather than a protocol one.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

# ------------------------------------------------------------------ logging
# A scheduled task's console output goes nowhere. Without a file on disk the
# only evidence of a run is a ping that did or did not arrive, which cannot be
# read after the fact - and the run that matters is the one nobody watched.
$logDir = Join-Path $root 'logs'
$logFile = Join-Path $logDir 'heartbeat.log'

function Write-Log {
    param([string]$Text, [string]$Colour = 'Gray')
    $line = "{0}  {1}" -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $Text
    if (-not $Quiet) { Write-Host $line -ForegroundColor $Colour }
    try {
        if (-not (Test-Path $logDir)) { $null = New-Item -ItemType Directory -Path $logDir -Force }
        Add-Content -Path $logFile -Value $line -Encoding UTF8
        # Trimmed on the way in. A check running every 10 minutes writes ~52k
        # lines a year, and a log nobody prunes is a log somebody deletes.
        $lines = @(Get-Content $logFile -ErrorAction Stop)
        if ($lines.Count -gt 2000) {
            [IO.File]::WriteAllLines($logFile, $lines[-1000..-1], (New-Object Text.UTF8Encoding($false)))
        }
    } catch { }
}

# ------------------------------------------------------------- .env reading
# Mirrors app/core/env.py: a variable already set in the shell always wins over
# the file, so `$env:FISHLOG_MAX_AGE_HOURS = 0` proves the stale path by hand.
function Get-Setting {
    param([string]$Name, [string]$Default = '')
    $shell = [Environment]::GetEnvironmentVariable($Name)
    if ($shell) { return $shell }
    $envFile = Join-Path $root '.env'
    if (Test-Path $envFile) {
        foreach ($line in (Get-Content $envFile)) {
            $t = $line.Trim()
            if ($t.StartsWith('#') -or -not $t.Contains('=')) { continue }
            $k, $v = $t -split '=', 2
            if ($k.Trim() -eq $Name) { return $v.Trim().Trim('"').Trim("'") }
        }
    }
    return $Default
}

function Set-EnvSetting {
    param([string]$Name, [string]$Value)
    $envFile = Join-Path $root '.env'
    $lines = @()
    if (Test-Path $envFile) { $lines = @(Get-Content $envFile) }
    $done = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $t = $lines[$i].Trim()
        if ($t.StartsWith('#')) { continue }
        if ($t -match "^\s*$([regex]::Escape($Name))\s*=") {
            $lines[$i] = "$Name=$Value"
            $done = $true
        }
    }
    if (-not $done) { $lines += "$Name=$Value" }
    # No BOM. Python's .env reader treats a leading BOM as part of the first
    # key name, so that variable silently stops existing.
    [IO.File]::WriteAllLines($envFile, $lines, (New-Object Text.UTF8Encoding($false)))
}

# ---------------------------------------------------------------- the check
function Send-Fail {
    param([string]$Ping, [string]$Reason)
    # The reason travels in the POST body, so the alert email says what broke
    # rather than only that something did.
    Write-Log "UNHEALTHY: $Reason" 'Red'
    try { $null = Invoke-WebRequest -Uri "$Ping/fail" -Method POST -Body $Reason -UseBasicParsing -TimeoutSec 15 } catch { }
    return 1
}

function Invoke-Heartbeat {
    $health = Get-Setting 'FISHLOG_HEALTH_URL' 'http://127.0.0.1:8000/health'
    # Anything older than this counts as stale. The scheduler ingests hourly, so
    # three hours is two missed runs - late enough to be real, early enough to
    # matter before a fishing trip.
    $maxAge = [double](Get-Setting 'FISHLOG_MAX_AGE_HOURS' '3')
    $ping = (Get-Setting 'FISHLOG_HEARTBEAT_URL').TrimEnd('/')

    if (-not $ping) {
        Write-Log 'FISHLOG_HEARTBEAT_URL not set - nothing to report to. Exiting quietly.' 'DarkGray'
        return 0
    }

    $body = $null
    try {
        $body = (Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 15).Content
    } catch {
        return (Send-Fail $ping ("no response from {0} ({1})" -f $health, $_.Exception.Message))
    }
    if (-not $body) { return (Send-Fail $ping "empty response from $health") }

    $j = $null
    try { $j = $body | ConvertFrom-Json } catch { }
    if (-not $j) { return (Send-Fail $ping "unreadable /health response: $body") }

    if ($j.status -ne 'ok') { return (Send-Fail $ping ("status={0} detail={1}" -f $j.status, $j.detail)) }

    if ($null -ne $j.age_hours -and [double]$j.age_hours -gt $maxAge) {
        return (Send-Fail $ping ("weather feed {0}h behind (limit {1}h) - the scheduler is probably stuck" -f $j.age_hours, $maxAge))
    }

    # Unresolved gaps are reported but do NOT fail the check. A gap is a record
    # that an hour was missed, and it stays on the books until somebody
    # backfills it - so failing on one would mean alerting forever about a past
    # incident, which is how a reader learns to ignore the alert.
    $note = "ok age={0}h gaps={1}" -f $j.age_hours, $j.unresolved_gaps
    Write-Log $note 'Green'
    try {
        $null = Invoke-WebRequest -Uri $ping -Method POST -Body $note -UseBasicParsing -TimeoutSec 15
    } catch {
        # A monitoring outage is not an application outage. Reporting it as one
        # is how a check gets muted.
        Write-Log "warning: could not reach the monitor at $ping" 'Yellow'
    }
    return 0
}

# ------------------------------------------------------------------ install
function Test-Elevated {
    return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Registering a scheduled task is an administrator action on a default Windows
# install - it is denied even for a task in your own folder, and the refusal
# arrives as HRESULT 0x80070005, which reads like a broken script. Rather than
# ask the owner to find an admin PowerShell (and paste a third line), the
# installer re-launches itself through UAC and waits for the result. A consent
# prompt for something that installs a background task is honest.
function Invoke-Elevated {
    Write-Host ''
    Write-Host '  Installing a scheduled task needs administrator - approve the prompt.' -ForegroundColor Cyan

    $argList = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', ('"{0}"' -f $PSCommandPath),
        '-Install', '-Elevated',
        '-EveryMinutes', $EveryMinutes
    )
    # The ping URL travels through the environment, not the command line: an
    # elevated process's arguments are readable by anything on the box, and the
    # uuid in that URL is the credential.
    if ($PingUrl) { Set-EnvSetting 'FISHLOG_HEARTBEAT_URL' $PingUrl }

    try {
        $p = Start-Process -FilePath 'powershell.exe' -ArgumentList $argList -Verb RunAs -Wait -PassThru -ErrorAction Stop
        return $p.ExitCode
    } catch {
        Write-Host ''
        Write-Host "  Elevation was declined or unavailable ($($_.Exception.Message))." -ForegroundColor Yellow
        Write-Host '  Open PowerShell as administrator and run:' -ForegroundColor Yellow
        Write-Host ("    powershell -NoProfile -ExecutionPolicy Bypass -File `"{0}`" -Install" -f $PSCommandPath) -ForegroundColor DarkGray
        return 1
    }
}

# A ping URL that is still the example is the one failure this whole mechanism
# cannot survive, because it looks installed: the task registers, fires on time,
# reads health correctly, and reports result 0 forever while every ping goes
# nowhere. That is exactly what happened - the placeholder <uuid> was installed
# verbatim and the log filled with "could not reach the monitor" for a day.
#
# So the URL is checked before it is written, and then actually USED once. An
# install that cannot prove a ping landed has not finished.
function Test-PingUrl {
    param([string]$Url)

    if ($Url -notmatch '^https?://') {
        return 'not a URL - it must start with https://'
    }
    # healthchecks.io ping URLs end in a uuid. Anything with angle brackets or
    # the word UUID in it is the example, pasted unedited.
    if ($Url -match '[<>]' -or $Url -match '(?i)your[-_]?uuid' -or $Url -match '(?i)/<?uuid>?/?$') {
        return 'that is the placeholder from the example, not a real check URL'
    }
    if ($Url -match '(?i)hc-ping\.com' -and
        $Url -notmatch '(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}') {
        return 'an hc-ping.com URL must end with the check uuid'
    }
    return $null
}

function Install-Task {
    if ($PingUrl) {
        $bad = Test-PingUrl $PingUrl
        if ($bad) {
            Write-Host ''
            Write-Host "  Refusing that ping URL: $bad" -ForegroundColor Red
            Write-Host "    given: $PingUrl" -ForegroundColor DarkGray
            Write-Host ''
            Write-Host '  Create a check at https://healthchecks.io (period 10 min, grace 20 min)' -ForegroundColor Cyan
            Write-Host '  and copy ITS url, which looks like:' -ForegroundColor Cyan
            Write-Host '    https://hc-ping.com/a1b2c3d4-5566-7788-99aa-bbccddeeff00' -ForegroundColor White
            Write-Host ''
            Write-Host '  Nothing was changed.' -ForegroundColor DarkGray
            Write-Host ''
            return 2
        }
        Set-EnvSetting 'FISHLOG_HEARTBEAT_URL' $PingUrl
        Write-Log 'wrote FISHLOG_HEARTBEAT_URL to .env' 'Green'

        # Use it once, now, and say whether it landed. A monitor that has never
        # received a ping cannot tell silence from an outage.
        try {
            $r = Invoke-WebRequest -Uri $PingUrl -Method Post -Body 'install' -TimeoutSec 20 -UseBasicParsing
            if ($r.StatusCode -eq 200) {
                Write-Log 'test ping accepted - the check should now show "up"' 'Green'
            } else {
                Write-Log ("test ping returned HTTP {0} - the check may not exist" -f $r.StatusCode) 'Yellow'
            }
        } catch {
            Write-Host ''
            Write-Host '  The test ping did NOT reach the monitor.' -ForegroundColor Red
            Write-Host ("    $($_.Exception.Message)") -ForegroundColor DarkGray
            Write-Host '  The task is still being installed, but nothing will arrive until' -ForegroundColor Yellow
            Write-Host '  this is fixed. Check the uuid, and that this machine can reach' -ForegroundColor Yellow
            Write-Host '  hc-ping.com.' -ForegroundColor Yellow
            Write-Host ''
        }
    }
    if (-not (Get-Setting 'FISHLOG_HEARTBEAT_URL')) {
        Write-Host ''
        Write-Host '  No ping URL yet.' -ForegroundColor Yellow
        Write-Host '  Create a free check at https://healthchecks.io (period 10 min, grace 20 min),' -ForegroundColor DarkGray
        Write-Host '  then re-run with -PingUrl https://hc-ping.com/<uuid>' -ForegroundColor DarkGray
        Write-Host '  Installing anyway - the task exits quietly until it is set.' -ForegroundColor DarkGray
    }

    $me = [Security.Principal.WindowsIdentity]::GetCurrent().Name

    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $root `
        -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -Quiet' -f $PSCommandPath)

    # Two triggers on purpose. The repeating one is the check; the logon one
    # fires immediately after a reboot, which is exactly when the answer is
    # least certain and the next repetition may still be minutes away.
    $triggers = @(
        (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes)),
        (New-ScheduledTaskTrigger -AtLogOn)
    )

    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -Hidden

    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    $desc = 'Reads Fishlog /health every few minutes and pings an external dead-man switch while it is healthy.'

    # S4U runs with no visible session and needs no stored password, so nothing
    # flashes a console window every ten minutes, and the check keeps running
    # when nobody is signed in. Interactive is the fallback for a machine whose
    # policy refuses S4U - it still works, because this box only serves while
    # somebody is logged in anyway: Docker Desktop is a session app.
    $registered = $false
    try {
        $p = New-ScheduledTaskPrincipal -UserId $me -LogonType S4U -RunLevel Limited
        $null = Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
            -Settings $settings -Principal $p -Description $desc -ErrorAction Stop
        $registered = $true
        Write-Log "registered '$TaskName' - runs whether or not you are logged in" 'Green'
    } catch {
        Write-Log "S4U registration refused ($($_.Exception.Message)) - falling back" 'Yellow'
    }
    if (-not $registered) {
        try {
            $p = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
            $null = Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
                -Settings $settings -Principal $p -Description $desc -ErrorAction Stop
            Write-Log "registered '$TaskName' - runs while $me is logged in" 'Green'
        } catch {
            # Never let the raw CIM error be the whole answer. "Access is denied"
            # from a COM HRESULT reads like a broken script rather than a missing
            # privilege, and the reader has no idea what to do next.
            Write-Log "could not register the task: $($_.Exception.Message)" 'Red'
            Write-Host ''
            Write-Host '  Register it by hand from an ADMIN PowerShell:' -ForegroundColor Yellow
            Write-Host ("    powershell -NoProfile -ExecutionPolicy Bypass -File `"{0}`" -Install" -f $PSCommandPath) -ForegroundColor DarkGray
            return 1
        }
    }

    Write-Host ''
    Write-Host '  Proving it now:' -ForegroundColor Cyan
    $rc = Invoke-Heartbeat
    Write-Host ''
    if ($rc -eq 0) {
        Write-Host "  Installed. Checks every $EveryMinutes minutes." -ForegroundColor Green
    } else {
        Write-Host '  Installed, but the app is NOT healthy right now - see the line above.' -ForegroundColor Yellow
    }
    Write-Host "  Log: $logFile" -ForegroundColor DarkGray
    return $rc
}

function Uninstall-Task {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Log "removed '$TaskName'" 'Green'
    } else {
        Write-Log "'$TaskName' was not registered" 'DarkGray'
    }
    Write-Host '  FISHLOG_HEARTBEAT_URL is left in .env - remove it by hand if you want it gone.' -ForegroundColor DarkGray
    return 0
}

function Show-Status {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Host ''
    if (-not $task) {
        Write-Host '  Not installed.' -ForegroundColor Yellow
        Write-Host ('  Install: powershell -NoProfile -ExecutionPolicy Bypass -File "{0}" -Install -PingUrl https://hc-ping.com/<uuid>' -f $PSCommandPath) -ForegroundColor DarkGray
    } else {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-Host ("  Task      {0}  ({1}, as {2})" -f $task.State, $task.Principal.LogonType, $task.Principal.UserId) -ForegroundColor Cyan
        Write-Host ("  Last run  {0}  result {1}" -f $info.LastRunTime, $info.LastTaskResult) -ForegroundColor Gray
        Write-Host ("  Next run  {0}" -f $info.NextRunTime) -ForegroundColor Gray
    }
    $ping = Get-Setting 'FISHLOG_HEARTBEAT_URL'
    if ($ping) {
        # Never print the whole URL: the uuid in it is the credential, and
        # anyone holding it can post a fake "all is well".
        Write-Host ("  Monitor   {0}...{1}" -f $ping.Substring(0, [Math]::Min(22, $ping.Length)), $ping.Substring([Math]::Max(0, $ping.Length - 4))) -ForegroundColor Gray
    } else {
        Write-Host '  Monitor   not configured (FISHLOG_HEARTBEAT_URL unset)' -ForegroundColor Yellow
    }
    Write-Host ("  Health    {0}" -f (Get-Setting 'FISHLOG_HEALTH_URL' 'http://127.0.0.1:8000/health')) -ForegroundColor Gray
    if (Test-Path $logFile) {
        Write-Host ''
        Write-Host '  Last 10 checks:' -ForegroundColor Cyan
        Get-Content $logFile -Tail 10 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    }
    Write-Host ''
    return 0
}

if ($Install) {
    if (-not $Elevated -and -not (Test-Elevated)) {
        # The elevated window closes the moment it finishes, so whatever it
        # printed is gone. Re-report here, in the window the owner is looking
        # at, from the log the child wrote.
        $rc = Invoke-Elevated
        $null = Show-Status
        exit $rc
    }
    exit (Install-Task)
}
elseif ($Uninstall) {
    if (-not $Elevated -and -not (Test-Elevated)) {
        try {
            $p = Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -PassThru -ErrorAction Stop -ArgumentList @(
                '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $PSCommandPath), '-Uninstall', '-Elevated')
            exit $p.ExitCode
        } catch {
            Write-Host "  Elevation declined - run this from an admin PowerShell." -ForegroundColor Yellow
            exit 1
        }
    }
    exit (Uninstall-Task)
}
elseif ($Status)    { exit (Show-Status) }
else                { exit (Invoke-Heartbeat) }
