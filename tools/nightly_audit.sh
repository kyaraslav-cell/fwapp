#!/usr/bin/env bash
# Cron entry for the nightly site audit, on the machine actually running the
# app - not Claude Code Remote, which can't reach this host or its real
# network (unpkg.com, the real database) at all. See docs/09-BACKLOG.md §20
# and .claude/skills/site-audit/SKILL.md for why and how this fits together.
#
# --public-only: only the read-only checks (dead controls, console/network
# errors, accessibility, visual diffs) run here, against the real running
# container over localhost - never the registration/session/catch flow,
# which would write a fake angler's fake catch into the real notebook every
# night forever (CLAUDE.md law 3). That flow stays in tools/site_audit.py's
# on-demand smoke-test mode against a throwaway database.
#
# Reports only when there's something to report: a clean night writes and
# commits nothing, so the repo's history only ever shows nights that found
# something. Setup (once):
#   .venv/bin/pip install -r requirements-dev.txt
#   .venv/bin/playwright install chromium
#   chmod +x tools/nightly_audit.sh
# Crontab line (adjust the path and time):
#   0 2 * * * /path/to/fwapp/tools/nightly_audit.sh >> /var/log/fishlog-audit.log 2>&1

set -euo pipefail
cd "$(dirname "$0")/.."

# A venv's own layout differs by OS - .venv/bin on Linux/macOS (where this was
# first written and run, a cloud sandbox), .venv/Scripts on Windows (where the
# owner's actual deployment host turned out to be). Detected rather than
# assumed, so this script keeps working when it's copied between the two.
if [ -x ".venv/Scripts/python.exe" ]; then
  VENV_PY=".venv/Scripts/python.exe"
else
  VENV_PY=".venv/bin/python"
fi

BASE_URL="${FISHLOG_AUDIT_BASE_URL:-http://127.0.0.1:8000}"
BRANCH="${FISHLOG_AUDIT_BRANCH:-claude/repository-edit-push-ggr229}"
DATE="$(date -u +%Y-%m-%d)"
REPORT="reports/site_audit/${DATE}.md"

# Never discard uncommitted work - if this checkout is also used for
# interactive dev and something's sitting there unstaged, stop rather than
# silently reset --hard over it at 2am.
if [ -n "$(git status --porcelain)" ]; then
  echo "$(date -u +%FT%TZ) uncommitted changes present - not resetting, skipping this run" >&2
  exit 1
fi

git fetch origin "$BRANCH"
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"

mkdir -p reports/site_audit

set +e
"$VENV_PY" tools/site_audit.py --base-url "$BASE_URL" --public-only --out "$REPORT"
STATUS=$?
set -e

if [ "$STATUS" -eq 0 ]; then
  echo "$(date -u +%FT%TZ) clean, nothing to report"
  rm -f "$REPORT"
  exit 0
fi

echo "$(date -u +%FT%TZ) findings - committing $REPORT"
git add "$REPORT"
git commit -m "Nightly site audit: findings for ${DATE}

Automated - tools/nightly_audit.sh run by cron on this machine, not a
Claude session. Read the report and triage per
.claude/skills/site-audit/SKILL.md: real bug vs. intentional vs. unclear,
judged against CLAUDE.md and the docs, not taste."

# A push can race a session working on the same branch - one retry after
# resyncing covers the ordinary case without looping forever on a real
# conflict, which needs a human anyway.
if ! git push origin "$BRANCH"; then
  git fetch origin "$BRANCH"
  git rebase "origin/$BRANCH"
  git push origin "$BRANCH"
fi
