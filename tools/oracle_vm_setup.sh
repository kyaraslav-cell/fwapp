#!/usr/bin/env bash
# Bootstraps a fresh Ubuntu VM (written for Oracle Cloud Always Free, but
# generic to any Ubuntu box) to run Fishlog: installs Docker, clones/updates
# the repo, brings up the compose stack, and installs Tailscale so
# `tailscale funnel 8000` can put it on a stable HTTPS URL with no domain and
# no certificate to renew. See docs/16-DEPLOY-ORACLE.md for the steps this
# script fits into, and read it before piping it into bash on a real machine.
set -euo pipefail

# Optional: restore a notebook packed by scripts/pack.ps1 on another machine.
#   ./oracle_vm_setup.sh --bundle /home/ubuntu/fishlog-bundle-....zip
# Without it the app starts with an empty notebook, which is correct for a
# first install and wrong for a migration - so the flag is explicit either way.
BUNDLE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --bundle) BUNDLE="${2:-}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

REPO_URL="${FISHLOG_REPO_URL:-https://github.com/kyaraslav-cell/fwapp.git}"
REPO_DIR="${FISHLOG_REPO_DIR:-$HOME/fwapp}"
BRANCH="${FISHLOG_BRANCH:-claude/repository-edit-push-ggr229}"

echo "== docker =="
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    echo "-> added $USER to the docker group; log out and back in for it to"
    echo "   take effect without sudo. This script still uses sudo below so"
    echo "   it works in the same session."
fi

echo "== repo =="
if [ -d "$REPO_DIR/.git" ]; then
    git -C "$REPO_DIR" fetch origin "$BRANCH"
    git -C "$REPO_DIR" checkout "$BRANCH"
    git -C "$REPO_DIR" pull --ff-only origin "$BRANCH"
else
    git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"

if [ ! -f .env ]; then
    cp .env.example .env
    echo "-> $REPO_DIR/.env created from the example. Edit it to add"
    echo "   FISHLOG_GEMINI_API_KEY / Google sign-in keys if you have them --"
    echo "   both are optional and the app reports them as off without one."
fi

# Funnel (like Caddy) sets X-Forwarded-For. Without this, every request
# counts as one address and the per-IP rate limit locks everyone out at once.
if grep -q '^FISHLOG_TRUST_PROXY=' .env; then
    sed -i 's/^FISHLOG_TRUST_PROXY=.*/FISHLOG_TRUST_PROXY=1/' .env
else
    echo 'FISHLOG_TRUST_PROXY=1' >> .env
fi

echo "== app =="
sudo docker compose up -d --build

# --------------------------------------------------------------- notebook
if [ -n "$BUNDLE" ]; then
    echo "== restoring the notebook =="
    [ -f "$BUNDLE" ] || { echo "bundle not found: $BUNDLE" >&2; exit 1; }
    command -v unzip >/dev/null 2>&1 || sudo apt-get install -y -qq unzip
    TMP="$(mktemp -d)"
    unzip -q -o "$BUNDLE" -d "$TMP"

    # Stop first: copying a database file under a live SQLite connection gives
    # you a file that opens and is then subtly wrong.
    sudo docker compose stop fishlog
    # A helper container is the only way to write into the named volume while
    # the app that owns it is down.
    sudo docker run --rm -v fwapp_fishlog-data:/data -v "$TMP:/b" alpine sh -c         'rm -f /data/fishlog.db /data/fishlog.db-wal /data/fishlog.db-shm;          cp /b/fishlog.db /data/fishlog.db;          mkdir -p /data/media; cp -r /b/media/. /data/media/ 2>/dev/null || true'
    sudo docker compose start fishlog

    # The bundle carries the source machine's .env, including a Google redirect
    # URI that names a host this box is not. Keep the keys, drop the host.
    if [ -f "$TMP/.env" ]; then
        cp "$TMP/.env" .env
        sed -i 's/^FISHLOG_TRUST_PROXY=.*/FISHLOG_TRUST_PROXY=1/' .env
        grep -q '^FISHLOG_TRUST_PROXY=' .env || echo 'FISHLOG_TRUST_PROXY=1' >> .env
        echo "-> restored .env. FISHLOG_GOOGLE_REDIRECT_URI still names the OLD"
        echo "   machine; fix it after the funnel prints this box's URL, and add"
        echo "   the new URI in the Google console or sign-in fails silently."
    fi
    rm -rf "$TMP"
    sudo docker compose up -d
    echo "-> notebook restored"
fi

# -------------------------------------------------------------- heartbeat
# The whole point of moving off the laptop is that nobody is watching the box.
# So the box reports on itself: a timer reads /health and pings an external
# dead-man's switch only while the app is genuinely healthy. If the VM dies,
# the pings stop and the monitor alerts on the silence - which is the one
# failure an agent running ON the box could never report itself.
echo "== heartbeat =="
chmod +x "$REPO_DIR/tools/heartbeat.sh"

sudo tee /etc/systemd/system/fishlog-heartbeat.service >/dev/null <<UNIT
[Unit]
Description=Fishlog health heartbeat
After=network-online.target docker.service

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$REPO_DIR
ExecStart=$REPO_DIR/tools/heartbeat.sh
UNIT

sudo tee /etc/systemd/system/fishlog-heartbeat.timer >/dev/null <<'UNIT'
[Unit]
Description=Run the Fishlog heartbeat every 10 minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec=10min
# The monitor's grace period has to be longer than this, or a slow tick reads
# as an outage.
AccuracySec=30s

[Install]
WantedBy=timers.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now fishlog-heartbeat.timer
echo "-> heartbeat timer installed (every 10 min)"
echo "   Set FISHLOG_HEARTBEAT_URL in $REPO_DIR/.env to a healthchecks.io ping"
echo "   URL. Until then the heartbeat exits quietly and nothing is watched."

echo "== tailscale =="
if ! command -v tailscale >/dev/null 2>&1; then
    curl -fsSL https://tailscale.com/install.sh | sudo sh
fi

cat <<'EOF'

Setup done. Two manual steps left, because both need human approval:

  1. sudo tailscale up
       -> opens a login link; approve this device in the Tailscale admin
          console.
  2. sudo tailscale funnel 8000
       -> prints the public HTTPS URL for the app.

Then verify:
  curl -s https://<the-funnel-url>/health

And to make it unattended - the point of putting it here rather than on a
laptop - give the box somewhere to report to:

  3. Create a free check at https://healthchecks.io (period 10 min, grace 20).
  4. Put its ping URL in .env:
       echo 'FISHLOG_HEARTBEAT_URL=https://hc-ping.com/<uuid>' >> ~/fwapp/.env
  5. Prove it, rather than assuming:
       ~/fwapp/tools/heartbeat.sh          # should print: ok age=..h gaps=..
       systemctl list-timers fishlog-heartbeat.timer

  From then on: the app answers and is fresh -> a ping every 10 minutes;
  the app is down or its weather feed is stale -> a failure ping immediately;
  the whole VM is gone -> no ping, and the monitor alerts on the silence.
EOF
