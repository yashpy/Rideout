# Contributing: branches, environments, releases

Every change can be traced from an issue to a PR to a deploy.

## Branches

| Branch | Deploys to | Protection |
|---|---|---|
| `main` | **Production** | PR only, CI green, 1 approval |
| `staging` | **Staging** | PR only, CI green |
| `develop` | **Development** | PR only, CI green |
| `feat/<slug>`, `fix/<slug>` | Vercel preview URL per PR | — |

Flow: `feat/*` → PR → `develop` → (release PR) → `staging` → (release PR) → `main`.

## Commits

Conventional commits, small and frequent:
`feat(agent): status templates for reassigning` · `fix(dispatch): frozen accepted runs` · `docs(contract): add vehicle.safety event` · `test(requests): illegal transition raises`

## Pull requests

Use the PR template (`.github/pull_request_template.md`): what changed, the issue it closes, whether the contract
changed, and how it was tested.

- Contract changes (`docs/CONTRACT.md`) go in the same PR as the code and are called out in the PR body.
- Feature and fix PRs into `develop`: merge with **squash**, then delete the branch.
- Release PRs (`develop → staging`, `staging → main`): merge with **Create a merge commit**, never squash.
  Squashed releases copy the changes into new commits, so GitHub reports main as dozens of commits "behind"
  develop even when the code is identical. `scripts/release.sh` does this for you.
- Rebase on `develop` before merging if CI is stale.

## CI/CD (`.github/workflows/`)

- `ci.yml` (every PR): `api`: ruff + pytest. `web`: eslint + typecheck + build.
- Render deploys the API and the voice relay from `render.yaml`. Vercel deploys the web app by branch.
- `GET /health` returns `{env, version, gitSha}`, so you always know what's running where.
- `scripts/release.sh` opens and merges the `develop → staging` / `staging → main` release PRs.

## Environments

| | Development | Staging | Production |
|---|---|---|---|
| Atlas DB | `rideout_dev` | `rideout_staging` | `rideout_prod` |
| Simulated households | on | on | on, labeled "simulated" |
| Secrets | GitHub Environment `dev` | `staging` | `production` |

## Secrets

Never commit keys. Use `.env` locally (git-ignored), GitHub Environments in CI, and the Render dashboard for
the deployed services. If a key is ever pasted in chat or committed, rotate it.
