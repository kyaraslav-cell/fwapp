#!/usr/bin/env sh
# Dead-man's switch for an unattended Fishlog.
#
# Runs on the box every few minutes (systemd timer, installed by
# tools/oracle_vm_setup.sh). It reads the app's own /health and pings an
# external monitor ONLY when the app is genuinely healthy.
#
# Why outbound rather than an uptime service polling the URL: an inbound check
# proves the funnel answers, nothing more. This proves the app answers, that
# its answer is "ok", and that the weather feed is not stale - and if the whole
# machine is dead, no ping arrives at all and the monitor alerts on the
# silence. One mechanism, three distinct failures:
#
#   VM dead / no network        -> no ping,          monitor alerts on silence
#   container down or erroring  -> /fail             monitor alerts immediately
#   up but weather feed stale   -> /fail             the QUIET failure - the app
#                                                    serves perfectly and every
#                                                    score it shows is old
#
# That third one is the reason this is not just `curl -f /health`. Law 4 forbids
# inventing the missing hours, so a stale feed stays visibly stale forever and
# nothing else would ever complain about it.
#
# Set FISHLOG_HEARTBEAT_URL in .env to a healthchecks.io (or equivalent) ping
# URL. With it unset the script exits quietly, so it is safe to install first
# and configure later.

set -eu

APP_URL="${FISHLOG_HEALTH_URL:-http://127.0.0.1:8000/health}"
# Anything older than this counts as stale. The scheduler ingests hourly, so
# three hours is two missed runs - late enough to be real, early enough to
# matter before a fishing trip.
MAX_AGE_HOURS="${FISHLOG_MAX_AGE_HOURS:-3}"

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$REPO_DIR/.env" ] && . "$REPO_DIR/.env" 2>/dev/null || true

PING="${FISHLOG_HEARTBEAT_URL:-}"
if [ -z "$PING" ]; then
    echo "FISHLOG_HEARTBEAT_URL not set - nothing to report to. Exiting quietly."
    exit 0
fi

# --fail so an HTTP error is an error, not a body to parse.
BODY="$(curl -fsS --max-time 15 "$APP_URL" 2>/dev/null || true)"

fail() {
    # The reason travels in the POST body, so the alert email says what broke
    # rather than only that something did.
    echo "UNHEALTHY: $1"
    curl -fsS -m 15 --data-raw "$1" "${PING}/fail" >/dev/null 2>&1 || true
    exit 1
}

[ -n "$BODY" ] || fail "no response from $APP_URL"

# Small, flat JSON - parsed with sed rather than adding a jq dependency to a box
# whose whole point is being lightweight and unattended.
STATUS="$(printf '%s' "$BODY"  | sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
AGE="$(printf '%s' "$BODY"     | sed -n 's/.*"age_hours"[[:space:]]*:[[:space:]]*\([0-9.]*\).*/\1/p')"
GAPS="$(printf '%s' "$BODY"    | sed -n 's/.*"unresolved_gaps"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p')"

[ "$STATUS" = "ok" ] || fail "status=$STATUS body=$BODY"

if [ -n "$AGE" ]; then
    # POSIX sh has no floats. awk is on every Ubuntu image.
    STALE="$(awk -v a="$AGE" -v m="$MAX_AGE_HOURS" 'BEGIN { print (a > m) ? 1 : 0 }')"
    [ "$STALE" = "0" ] || fail "weather feed ${AGE}h behind (limit ${MAX_AGE_HOURS}h) - the scheduler is probably stuck"
fi

# Unresolved gaps are reported but do NOT fail the check. A gap is a record that
# an hour was missed, and it stays on the books until somebody backfills it -
# so treating it as an outage would mean alerting forever about one past
# incident, which trains the reader to ignore the alert.
NOTE="ok age=${AGE:-?}h gaps=${GAPS:-?}"
echo "$NOTE"
curl -fsS -m 15 --data-raw "$NOTE" "$PING" >/dev/null 2>&1 || {
    echo "warning: could not reach the monitor at $PING"
    exit 0
}
