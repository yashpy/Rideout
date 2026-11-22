#!/usr/bin/env bash
# Promote develop → staging → main and tag it. Run on your laptop with `gh auth login` done.
#
#   scripts/release.sh v1.0 <domain>
#
# Stops before prod until you type "yes" (do the two-phone smoke test on staging first).
set -euo pipefail

TAG="${1:?usage: scripts/release.sh <tag> <domain>}"
DOMAIN="${2:?usage: scripts/release.sh <tag> <domain>}"
cd "$(git rev-parse --show-toplevel)"

say() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }
die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

ci_green() {  # ci_green <branch>
  local sha concl
  sha="$(git rev-parse "origin/$1")"
  concl="$(gh run list --workflow ci --branch "$1" --commit "$sha" -L 1 --json conclusion -q '.[0].conclusion' 2>/dev/null || true)"
  [ "$concl" = "success" ] || die "ci on $1 ($(git rev-parse --short "origin/$1")) is '${concl:-not run}'. Fix it first."
}

promote() {  # promote <from> <to>
  local url
  say "PR $1 → $2"
  url="$(gh pr list --base "$2" --head "$1" --state open --json url -q '.[0].url')"
  [ -n "$url" ] || url="$(gh pr create --base "$2" --head "$1" --title "release: $TAG ($1 → $2)" \
    --body "Release $TAG. Promoted by scripts/release.sh after CI and smoke tests.")"
  echo "$url"
  sleep 10  # let CI register its checks on the PR
  gh pr checks "$url" --watch --fail-fast || die "checks failed on $url"
  # Release PRs use a merge commit (not squash) so staging/main stay 0 commits behind develop.
  # main needs 1 approval: --admin works if you're an admin,
  # otherwise ask another maintainer to approve and this keeps retrying.
  for i in $(seq 1 60); do
    if gh pr merge "$url" --merge 2>/dev/null || gh pr merge "$url" --merge --admin 2>/dev/null; then break; fi
    [ "$i" = 1 ] && echo "can't merge yet (needs an approval?). Ask a maintainer to approve: $url  (retrying for 15 min)"
    [ "$(gh pr view "$url" --json state -q .state)" = "MERGED" ] && break
    sleep 15
  done
  [ "$(gh pr view "$url" --json state -q .state)" = "MERGED" ] || die "not merged: $url"
  git fetch -q origin
}

wait_deploy() {  # wait_deploy <branch>
  local sha id
  sha="$(git rev-parse "origin/$1")"
  say "waiting for deploy of $1 @ ${sha::7}"
  for _ in $(seq 1 30); do
    id="$(gh run list --workflow deploy --branch "$1" --commit "$sha" -L 1 --json databaseId -q '.[0].databaseId')"
    [ -n "$id" ] && break
    sleep 4
  done
  if [ -z "$id" ]; then  # the merge didn't touch api/ or infra/, so deploy by hand to keep the sha in step
    echo "no deploy run for ${sha::7}; dispatching one"
    gh workflow run deploy --ref "$1" -f env="$([ "$1" = main ] && echo prod || echo "$1")"
    sleep 8
    id="$(gh run list --workflow deploy --branch "$1" -L 1 --json databaseId -q '.[0].databaseId')"
  fi
  [ -n "$id" ] || die "no deploy run for $1. Actions → deploy → Run workflow"
  gh run watch "$id" --exit-status || die "deploy failed: gh run view $id --log-failed"
}

smoke() {  # smoke <env> <branch> [--flow]
  local env="$1" branch="$2"; shift 2
  say "smoke $env"
  uv run --project api python scripts/smoke.py --domain "$DOMAIN" --only "$env" \
    --sha "$(git rev-parse --short=7 "origin/$branch")" "$@"
}

git fetch -q origin
[ -z "$(git status --porcelain)" ] || die "working tree not clean"
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null && die "tag $TAG already exists"

say "CI on develop"; ci_green develop

promote develop staging
wait_deploy staging
smoke staging staging --flow

say "Staging is up: https://staging.$DOMAIN  (api https://api-staging.$DOMAIN)"
echo "Two-phone check now: Rosa's phone rings, driver phone accepts, callback says the driver's name."
read -r -p "Promote to prod? type yes: " ans
[ "$ans" = "yes" ] || die "stopped before prod. Staging stays as is."

promote staging main
wait_deploy main
smoke prod main

say "tag $TAG"
git tag -a "$TAG" "origin/main" -m "RideOut $TAG"
git push origin "$TAG"
printf '\n\033[32m✓ %s is live: https://app.%s\033[0m\n' "$TAG" "$DOMAIN"
