#!/usr/bin/env bash
# Usage (on the VM):  ./deploy.sh <dev|staging|prod> <image-tag>
# Rollback = run it again with the previous tag (ghcr.io/<owner>/rideout-api:<sha>).
set -euo pipefail
cd "$(dirname "$0")"

ENV_NAME="${1:?env: dev|staging|prod}"
TAG="${2:?image tag}"
case "$ENV_NAME" in dev|staging|prod) ;; *) echo "bad env: $ENV_NAME" >&2; exit 1 ;; esac

VAR="$(echo "$ENV_NAME" | tr '[:lower:]' '[:upper:]')_TAG"
# compose loads every service, so every env file must exist even if empty
touch .env dev.env staging.env prod.env
if grep -q "^${VAR}=" .env; then sed -i "s|^${VAR}=.*|${VAR}=${TAG}|" .env; else echo "${VAR}=${TAG}" >> .env; fi

docker compose pull "api-$ENV_NAME"
# mongo first: dev/staging may point at it (prod stays on whatever prod.env says)
docker compose up -d --wait mongo || echo "mongo not healthy yet; envs on Atlas are unaffected" >&2
docker compose up -d caddy "api-$ENV_NAME"

for _ in $(seq 1 30); do
  if docker compose exec -T "api-$ENV_NAME" python -c \
      "import urllib.request,json;print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health')))"; then
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 2
done
echo "api-$ENV_NAME did not become healthy" >&2
docker compose logs --tail 80 "api-$ENV_NAME" >&2
exit 1
