#!/usr/bin/env bash
# Bootstraps a fresh Ubuntu VM (written for Oracle Cloud Always Free, but
# generic to any Ubuntu box) to run Fishlog: installs Docker, clones/updates
# the repo, brings up the compose stack, and installs Tailscale so
# `tailscale funnel 8000` can put it on a stable HTTPS URL with no domain and
# no certificate to renew. See docs/16-DEPLOY-ORACLE.md for the steps this
# script fits into, and read it before piping it into bash on a real machine.
set -euo pipefail

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
EOF
