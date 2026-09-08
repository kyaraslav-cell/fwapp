# Fishlog health check. Answers one question: is the whole chain alive, and is
# the container actually running the code in this working tree?
#
#   powershell -ExecutionPolicy Bypass -File scripts\check.ps1
#
# The second half of that question is the one that matters here, and it is
# borrowed from a bug LeadFind paid for: n8n reported three workflows as
# "published and in sync" while the scheduler quietly executed code from days
# earlier, and every check said green.
#
# Fishlog has the same failure in a different costume. The image holds a FROZEN
# COPY of app/ and config/ - there is no bind mount - so editing a file changes
# nothing the public URL serves, and neither `docker compose restart` nor a bare
# `docker compose up -d` picks it up. Standing rule 20 exists because of that.
# So this script does not ask whether the container is running. It asks whether
# the container is running THIS code, by hashing both sides.

$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Section($t) {
    Write-Host ""
    Write-Host "== $t " -NoNewline -ForegroundColor Cyan
    Write-Host ("=" * [Math]::Max(2, 58 - $t.Length)) -ForegroundColor DarkCyan
}
function Ok($t)   { Write-Host "  [ok]   $t" -ForegroundColor Green }
function Bad($t)  { Write-Host "  [FAIL] $t" -ForegroundColor Red; $script:fails++ }
function Warn($t) { Write-Host "  [warn] $t" -ForegroundColor Yellow }
function Note($t) { Write-Host "  [--]   $t" -ForegroundColor DarkGray }

$script:fails = 0

# PowerShell 5.1 wraps a native command's stderr in an ErrorRecord. `docker`
# writes to stderr whenever the daemon is down - exactly the case being tested -
# so every docker call here is guarded.
function Native {
    param([scriptblock]$Block)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $out = & $Block 2>$null } catch { $out = $null } finally { $ErrorActionPreference = $prev }
    return $out
}

# ------------------------------------------------------------------- docker
Section "Docker"
$ver = Native { docker info --format '{{.ServerVersion}}' }
if ($ver) {
    Ok "engine up ($ver)"
} else {
    Bad "engine not responding - start Docker Desktop and re-run"
    Write-Host ""
    Write-Host "  Nothing below can be checked without it." -ForegroundColor DarkGray
    exit 1
}

$psLines = Native { docker compose ps --format "{{.Service}}|{{.Status}}" }
if (-not $psLines) {
    Bad "no compose services - run: docker compose up -d"
} else {
    foreach ($line in $psLines) {
        $svc, $status = $line -split '\|', 2
        if ($status -like "Up*") { Ok "$svc - $status" } else { Bad "$svc - $status" }
    }
}

$cid = (Native { docker compose ps -q fishlog }) | Select-Object -First 1
if (-not $cid) { Bad "fishlog container not found"; }

# --------------------------------------------------------------------- app
Section "Application"
$local = 'http://127.0.0.1:8000'
try {
    $h = Invoke-RestMethod "$local/health" -TimeoutSec 10
    if ($h.status -eq 'ok') { Ok "/health ok - newest observation $([math]::Round($h.age_hours,1)) h old" }
    else { Bad "/health says '$($h.status)': $($h.detail)" }
    if ($h.unresolved_gaps -gt 0) { Warn "$($h.unresolved_gaps) unresolved weather gaps" }
    # A stale feed is the quiet failure: the app serves fine and every score it
    # shows is yesterday's. Law 4 forbids inventing the missing hours, so the
    # only honest signal is the age.
    if ($h.age_hours -gt 6) { Warn "weather feed is $([math]::Round($h.age_hours,1)) h behind - the scheduler may be stuck" }
} catch {
    Bad "$local/health not reachable"
}

foreach ($path in @('/', '/auth/login', '/history')) {
    try {
        $r = Invoke-WebRequest ($local + $path) -UseBasicParsing -TimeoutSec 10 -MaximumRedirection 0 -ErrorAction Stop
        Ok ("{0,-14} {1}" -f $path, $r.StatusCode)
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        # A redirect off / to the login page is correct when signed out.
        if ($code -ge 300 -and $code -lt 400) { Ok ("{0,-14} {1} (redirect)" -f $path, $code) }
        else { Bad ("{0,-14} {1}" -f $path, $(if ($code) { $code } else { 'no response' })) }
    }
}

# ------------------------------------------------------- the drift check
# The one that earns this script's existence.
Section "Is the container running THIS code?"
if ($cid) {
    function TreeHash($files) {
        $sb = New-Object System.Text.StringBuilder
        foreach ($f in ($files | Sort-Object)) { [void]$sb.AppendLine($f) }
        $md5 = [System.Security.Cryptography.MD5]::Create()
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($sb.ToString())
        ([BitConverter]::ToString($md5.ComputeHash($bytes)) -replace '-', '').Substring(0, 12)
    }

    # Same recipe on both sides: relative path + sha256 of contents, sorted.
    $inside = Native {
        docker exec $cid sh -c "cd /srv/fishlog && find app config -type f ! -name '*.pyc' ! -path '*__pycache__*' -exec sha256sum {} \; | sed 's#  #|#' | sort"
    }

    if (-not $inside) {
        Bad "could not read app/ and config/ out of the container"
    } else {
        $insideList = @()
        foreach ($l in $inside) {
            if ($l -match '^([0-9a-f]{64})\|(.+)$') { $insideList += ($matches[2] + ' ' + $matches[1]) }
        }

        $outsideList = @()
        foreach ($d in @('app', 'config')) {
            Get-ChildItem -Path (Join-Path $root $d) -Recurse -File |
                Where-Object { $_.Extension -ne '.pyc' -and $_.FullName -notmatch '__pycache__' } |
                ForEach-Object {
                    $rel = $_.FullName.Substring($root.Length + 1).Replace('\', '/')
                    $sha = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
                    $outsideList += ($rel + ' ' + $sha)
                }
        }

        $a = TreeHash $insideList
        $b = TreeHash $outsideList

        if ($a -eq $b) {
            Ok "container matches the working tree ($($insideList.Count) files, $a)"
        } else {
            Bad "container is serving DIFFERENT code from the working tree"
            Write-Host "         image $a  vs  tree $b" -ForegroundColor DarkGray

            # Name the files, because "something differs" sends you looking in
            # the wrong place. This is the whole point of hashing per file.
            $inMap = @{}; foreach ($e in $insideList)  { $p, $s = $e -split ' ', 2; $inMap[$p]  = $s }
            $outMap = @{}; foreach ($e in $outsideList) { $p, $s = $e -split ' ', 2; $outMap[$p] = $s }
            $shown = 0
            foreach ($p in ($outMap.Keys + $inMap.Keys | Sort-Object -Unique)) {
                if ($shown -ge 12) { Write-Host "         ..." -ForegroundColor DarkGray; break }
                if (-not $inMap.ContainsKey($p))       { Write-Host "         + $p (only in tree)"      -ForegroundColor DarkGray; $shown++ }
                elseif (-not $outMap.ContainsKey($p))  { Write-Host "         - $p (only in image)"     -ForegroundColor DarkGray; $shown++ }
                elseif ($inMap[$p] -ne $outMap[$p])    { Write-Host "         ~ $p" -ForegroundColor DarkGray; $shown++ }
            }
            Write-Host ""
            Write-Host "         Fix: docker compose up -d --build" -ForegroundColor Yellow
            Write-Host "         A plain restart or a bare 'up -d' will NOT pick it up." -ForegroundColor DarkGray
        }
    }
}

# ------------------------------------------------------------------- data
Section "Notebook"
if ($cid) {
    # Piped through stdin, not passed as -c. Nesting a Python string that
    # contains single quotes inside a PowerShell string inside `docker exec`
    # loses a quote layer somewhere every time; a here-string on stdin has no
    # quoting to lose. The first version of this failed for exactly that reason
    # and reported the database unreadable when it was fine.
    $probe = @'
import sqlite3, os
db = os.environ.get('FISHLOG_DB_PATH', '/data/fishlog.db')
c = sqlite3.connect('file:' + db + '?mode=ro', uri=True)
names = [r[0] for r in c.execute("select name from sqlite_master where type='table'")]
def n(t):
    try: return c.execute('select count(*) from "%s"' % t).fetchone()[0]
    except Exception: return None
want = ['user', 'lake', 'catch', 'prediction', 'weather_hourly', 'angler_lake']
want += [t for t in names if 'session' in t and 'auth' not in t]
for t in want:
    v = n(t)
    if v is not None: print('%s|%s' % (t, v))
'@
    $counts = Native { $probe | docker exec -i $cid python - }

    if ($counts) {
        foreach ($line in $counts) {
            $t, $v = $line -split '\|', 2
            Ok ("{0,-18} {1}" -f $t, $v)
        }
    } else {
        Bad "could not read the notebook database"
    }

    # The volume is the only thing here that cannot be rebuilt from git.
    $vol = Native { docker volume ls --filter name=fishlog-data --format '{{.Name}}' }
    if ($vol) { Ok "volume present: $($vol -join ', ')" } else { Bad "fishlog-data volume missing - the notebook is not persisted" }
}

# ---------------------------------------------------------------- secrets
Section "Configuration"
$envFile = Join-Path $root '.env'
if (-not (Test-Path $envFile)) {
    Warn ".env not present - optional features are off, the app still runs"
} else {
    function EnvVal($k) {
        $l = Get-Content $envFile -ErrorAction SilentlyContinue |
             Where-Object { $_ -match "^\s*$k\s*=" } | Select-Object -First 1
        if ($l) { ($l -split '=', 2)[1].Trim() } else { $null }
    }
    # Optional by design: the app must run without any of them (docker-compose
    # uses `:-` defaults for exactly this reason). So a missing one is a note,
    # never a failure.
    foreach ($k in @('FISHLOG_GEMINI_API_KEY', 'FISHLOG_GOOGLE_CLIENT_ID', 'KIE_AI_API_KEY')) {
        if (EnvVal $k) { Ok "$k set" } else { Note "$k not set - that feature is off" }
    }
    $tp = EnvVal 'FISHLOG_TRUST_PROXY'
    if ($tp -eq '1') { Ok "FISHLOG_TRUST_PROXY=1 - correct behind Tailscale or Caddy" }
    else { Note "FISHLOG_TRUST_PROXY not 1 - correct ONLY if nothing sits in front of this app" }
}

# --------------------------------------------------------------- public URL
Section "Public URL"
$tsExe = @(
    'tailscale',
    "$env:ProgramFiles\Tailscale\tailscale.exe"
) | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Select-Object -First 1

if (-not $tsExe) {
    Note "tailscale not found - local only"
} else {
    $st = Native { & $tsExe status }
    if ($st -match 'Funnel on') { Ok "Tailscale funnel is on" } else { Warn "Tailscale funnel does not look enabled" }
    $host_ = ($st | Select-String -Pattern '^\S+\s+(\S+)\s' | Select-Object -First 1).Matches.Groups[1].Value
    if ($host_) {
        $url = "https://$host_.tailf99616.ts.net/health"
        try {
            $ph = Invoke-RestMethod $url -TimeoutSec 20
            if ($ph.status -eq 'ok') { Ok "public /health ok" } else { Bad "public /health says '$($ph.status)'" }
        } catch { Warn "public URL not reachable from here ($url)" }
    }
}

# ------------------------------------------------------------------ verdict
Write-Host ""
if ($script:fails -eq 0) {
    Write-Host "  PASS - nothing failed." -ForegroundColor Green
} else {
    Write-Host "  FAIL - $($script:fails) check(s) failed." -ForegroundColor Red
}
Write-Host ""
Write-Host "  This checks the DEPLOYMENT, not the code. For the code: pytest." -ForegroundColor DarkGray
Write-Host ""
exit $script:fails
