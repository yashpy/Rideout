#!/usr/bin/env bash
# One-time Vultr VM setup (Ubuntu 24.04). Run from your laptop:
#
#   scp infra/bootstrap-vm.sh secrets.env root@<VM_IP>:/tmp/
#   ssh root@<VM_IP> 'bash /tmp/bootstrap-vm.sh <domain> /tmp/secrets.env'
#
# secrets.env = .env.example filled in (MONGODB_URI, GEMINI_API_KEY, ... ; ENV is set by compose).
# It is copied to dev.env / staging.env / prod.env. Each env uses its own database (rideout_<env>)
# from the same MONGODB_URI. Edit a file afterwards if one env needs different keys.
set -euo pipefail

DOMAIN="${1:?usage: bootstrap-vm.sh <domain> <secrets.env>}"
SECRETS="${2:?usage: bootstrap-vm.sh <domain> <secrets.env>}"
[ -f "$SECRETS" ] || { echo "no such file: $SECRETS" >&2; exit 1; }

command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh

if command -v ufw >/dev/null; then
  ufw allow OpenSSH >/dev/null
  ufw allow 80/tcp >/dev/null
  ufw allow 443 >/dev/null
  ufw --force enable >/dev/null
fi

mkdir -p /opt/rideout
cd /opt/rideout

cat > .env <<EOF
DOMAIN=${DOMAIN}
API_IMAGE=ghcr.io/yashpy/rideout-api
EOF

for e in dev staging prod; do
  grep -v '^ENV=' "$SECRETS" | grep -v '^NEXT_PUBLIC_' > "$e.env"
  # Public URL per env (the voice agent calls back here).
  case "$e" in prod) host="api.${DOMAIN}" ;; *) host="api-${e}.${DOMAIN}" ;; esac
  sed -i '/^PUBLIC_API_URL=/d' "$e.env"
  echo "PUBLIC_API_URL=https://${host}" >> "$e.env"
  chmod 600 "$e.env"
done
rm -f "$SECRETS"

echo
echo "VM ready. /opt/rideout has .env + dev/staging/prod.env."
echo "Next: DNS A records api-dev / api-staging / api → $(curl -fsS https://api.ipify.org 2>/dev/null || echo '<this VM IP>')"
echo "Then push to develop (or run the deploy workflow) and check https://api-dev.${DOMAIN}/health"
