# Rules for coding agents (Claude Code, Cursor, Codex)

Read this file, `README.md`, `docs/ARCHITECTURE.md`, and `docs/CONTRACT.md` before your first change.

## Always
1. **Work on a branch** named `feat/<slug>` (or `fix/<slug>`) from the latest `develop`. Never commit to `develop`, `staging`, or `main`.
2. **Stay inside the change.** Touch only the folders the change needs. If you need something from another area, add a TODO and say so.
3. **The contract is shared.** Don't rename or remove fields, endpoints, or event types in `docs/CONTRACT.md`. To add something, edit the contract in the same PR and say so in the PR body.
4. **Request status changes only through `api/requests.py`** (`transition()`), along the legal transitions.
5. **The AI never writes ride status, ETAs, driver names, or promises.** Those come only from `api/agent/templates.py`. Every AI acknowledgment goes through `api/agent/honesty.py`.
6. **Tests first for core rules:** illegal transitions, atomic accept (two concurrent accepts → exactly one wins), honesty guard, callback idempotency.
7. Run before every commit: `cd api && uv run ruff check . && uv run ruff format --check . && uv run pytest -q` and/or `cd web && pnpm lint && pnpm typecheck`.
   Python imports are always absolute from the `api` package (`from api.requests import transition`). Run the server from the repo root: `uv run --project api uvicorn api.main:app`.
8. Small commits with conventional messages (`feat(dispatch): ...`).
9. **No secrets in code.** Read config from env vars (see `.env.example`).
10. **Simulated data is labeled.** Anything from `api/sim/` shows a "simulated" badge in the UI.

## UI rules (web/)
- Map-first. Red = fire or a person who needs help, nothing else. One primary action per screen.
- Components: shadcn/ui + Tailwind. Map: MapLibre GL + deck.gl layers. No new UI kits.
- Live data comes from `/live` (WebSocket) through `web/lib/live.ts`. Don't poll unless the socket is down.
- Every state change is visible: animated counters, a pulse on changed rows, toasts for safety alerts. No layout jumps.
- Driver app: tap targets ≥ 48 px, works one-handed, readable in sunlight (high contrast).

## Never
- Copy code from other projects without a compatible license.
- Add a dependency without a one-line reason in the PR body.
- Force-push, rewrite history, or delete someone else's branch.
- Call another service's internal functions across folders. Go through the API or the database.
