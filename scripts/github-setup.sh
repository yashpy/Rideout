#!/usr/bin/env bash
# One-shot GitHub setup. Run once, from the repo root, after the first push of `main`:
#   gh auth login && ./scripts/github-setup.sh
# Creates develop + staging, branch protection (PR + green CI), environments and labels.
# Safe to re-run: existing items are skipped.
set -euo pipefail

REPO="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
MAIN_SHA="$(gh api "repos/$REPO/git/ref/heads/main" -q .object.sha)"
echo "repo: $REPO  main: ${MAIN_SHA:0:7}"

for b in develop staging; do
  gh api "repos/$REPO/git/refs" -f ref="refs/heads/$b" -f sha="$MAIN_SHA" >/dev/null 2>&1 \
    && echo "created $b" || echo "$b exists"
done
gh api -X PATCH "repos/$REPO" -f default_branch=develop -F delete_branch_on_merge=true \
  -F allow_squash_merge=true -F allow_merge_commit=true -F allow_rebase_merge=false >/dev/null
echo "default branch → develop; squash for features, merge commits for releases"

protect() {  # branch, required approvals
  if gh api -X PUT "repos/$REPO/branches/$1/protection" --input - >/dev/null 2>&1 <<JSON
{
  "required_status_checks": {"strict": false, "contexts": ["api", "web"]},
  "enforce_admins": false,
  "required_pull_request_reviews": {"required_approving_review_count": $2},
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
  then echo "protected $1 (PR + CI, $2 approval(s))"
  else echo "WARN: could not protect $1 (private repos on GitHub Free can't use branch protection;"
       echo "      make the repo public or upgrade, then re-run). Continuing."
  fi
}
protect develop 0
protect staging 0
protect main 1

for e in dev staging production; do
  if gh api -X PUT "repos/$REPO/environments/$e" >/dev/null 2>&1; then echo "environment $e"
  else echo "WARN: could not create environment $e (needs a public repo or a paid plan). Continuing."; fi
done

label() { gh label create "$1" --color "$2" --description "$3" -R "$REPO" 2>/dev/null || true; }
label contract d93f0b "Changes docs/CONTRACT.md"
label blocker  b60205 "Breaks a core flow"
echo "done"
