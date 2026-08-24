# 16 — Deploying on Oracle Cloud Always Free

This is the fallback path from `docs/10 §9`: used only if no machine the owner
already has can stay powered on. The primary plan — `docker compose up -d` on
owned hardware plus `tailscale funnel` — is cheaper in effort and identical in
architecture. This doc just runs that same recipe on a free-forever cloud VM
instead of a laptop, because Oracle's Always Free tier includes a real,
persistent block volume, which is the one constraint that disqualifies every
other free host (`docs/10 §9`).

**Deviation from `docs/10 §9`, and why:** that section says "plus Caddy for
HTTPS." This doc uses Tailscale Funnel instead, on both the VM and the app's
own dependency list. Caddy needs a domain name pointed at the VM and a
certificate to keep renewed; Funnel needs neither — it reuses the exact
mechanism already chosen for the primary plan, so the two deployment paths
stay identical except for who owns the box. A Caddy+domain appendix is at the
bottom for anyone who already owns a domain and prefers it.

**What this session could not do:** create the Oracle account, click through
the console to launch the VM, or approve the Tailscale device — all of that
needs a human, a browser, and (for Oracle) a card for identity verification
(the Always Free shapes are never billed). Nothing here was provisioned from
the build sandbox; this is the runbook for doing it, written so the console
steps are the only ones left.

---

## Before starting

- An Oracle Cloud account on the Always Free tier — signup at
  oracle.com/cloud/free. Card verification is required by Oracle even though
  the free shapes are never charged.
- An SSH key pair (`ssh-keygen -t ed25519` if you don't have one) — paste the
  public key into the console when the instance is created.
- A Tailscale account (free for personal use) — tailscale.com.

## 1. Launch the instance

Console → **Compute → Instances → Create instance**.

- **Image:** Ubuntu 24.04 (Canonical's minimal or standard image both work).
- **Shape:** `VM.Standard.A1.Flex` (Ampere ARM), the Always Free shape. Set
  **2 OCPU / 12 GB** — the current Always Free allocation (`docs/10 §9` notes
  it was halved from 4/24 in 2026); this app needs far less than either.
- **Add SSH key:** paste the public key from above.
- **Networking:** the default VCN and subnet are fine.

**If it refuses with "out of capacity":** this is the known, documented
failure mode for the ARM Always Free shape, not a mistake — retry, try a
different availability domain in the same region, or try at a different time
of day. It is unrelated to anything below.

## 2. Firewall: open only SSH

Console → the instance's **VCN → Security Lists → Default Security List →
Add Ingress Rule**: TCP, port 22, source `0.0.0.0/0` (or narrower, if the
owner's IP is stable). **Do not open 80, 443 or 8000** — Tailscale Funnel
reaches the app over the tailnet and its own relay, not through the VM's
public security list, so the smallest possible attack surface is the
default: SSH only.

Ubuntu's own `iptables`/`ufw` on the image may also block traffic
independently of the OCI security list — if `ssh` itself doesn't connect,
check both layers.

## 3. Bootstrap the VM

SSH in (`ssh ubuntu@<public-ip>`), then run the setup script committed at
`tools/oracle_vm_setup.sh`:

```bash
curl -fsSL https://raw.githubusercontent.com/kyaraslav-cell/fwapp/claude/repository-edit-push-ggr229/tools/oracle_vm_setup.sh | bash
```

It installs Docker, clones the repo, copies `.env.example` to `.env`, sets
`FISHLOG_TRUST_PROXY=1` (required — Funnel sets `X-Forwarded-For`, and without
this every request counts as one address and the per-IP rate limit locks
everyone out together, `docs/10 §2` rule and `docs/adr/0004`'s addendum),
brings the app up with `docker compose up -d --build`, and installs
Tailscale.

If you'd rather read it before running it — it's a plain bash script, no
surprises, and lives in the repo rather than being piped from anywhere else.

## 4. Put it on a stable HTTPS URL

```bash
sudo tailscale up          # prints a login link — open it, approve the device
sudo tailscale funnel 8000
```

Funnel prints the public URL — something like
`https://<machine>.<tailnet>.ts.net`. That's the app, on a real certificate,
reachable from any phone, without a domain purchase or a cert to renew.
Funnel needs to be enabled once for the tailnet in the Tailscale admin
console under **DNS → HTTPS Certificates**, if it isn't already.

## 5. Verify

```bash
curl -s https://<machine>.<tailnet>.ts.net/health
```

should report the age of the last weather ingest, not just "ok" — that's the
healthcheck `docs/10 §9` requires, and it's the first thing to check after
any redeploy. Then, from the same box:

```bash
cd ~/fwapp && .venv/bin/python tools/preflight.py   # after `make install` in a venv
```

confirms Nominatim, Overpass and Open-Meteo are actually reachable from this
machine — the build sandbox has never been able to reach them (`docs/10 §6`),
so this is the first real signal.

## Costs and limits

| Item | Always Free limit | This app's usage |
|---|---|---|
| Compute | 4 OCPU / 24 GB ARM total, account lifetime | 2 OCPU / 12 GB, one instance |
| Block storage | 200 GB total | a few hundred MB for the SQLite file and image |
| Egress | 10 TB/month | negligible — a handful of JSON responses per session |

No cost as long as the instance stays inside the Always Free shape. Oracle
does reserve the right to reclaim an idle account; logging in periodically
avoids that.

## What still differs from the "own machine" path

Nothing architectural — same image, same compose file, same Funnel command.
The only operational differences: patching the VM is now the owner's job
(Oracle doesn't do it for you), and the machine is a cloud VM rather than
hardware in the house, so "unplug it by accident" stops being a failure mode
and "Oracle reclaims an idle Always Free account" becomes one instead.

---

## Appendix: Caddy instead of Funnel, if a domain is already owned

Only worth it if a domain is already pointed at this VM's public IP. Open 80
and 443 in the security list instead of relying on Funnel, install Caddy
(`apt install caddy` on Ubuntu 24.04 — it's in the default repos), and:

```
# /etc/caddy/Caddyfile
fishlog.example.com {
    reverse_proxy localhost:8000
}
```

`systemctl reload caddy`. Caddy issues and renews the certificate itself via
Let's Encrypt. `FISHLOG_TRUST_PROXY=1` is still required. This path adds a
new dependency (Caddy) and a recurring one (the domain's renewal) that Funnel
avoids entirely, which is why it's the appendix and not the main path.
