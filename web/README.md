# web/ — Next.js app (Vercel)

```bash
pnpm i
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm dev   # http://localhost:3000
pnpm lint && pnpm typecheck && pnpm build
```

| Path | What |
|---|---|
| `/` | Kiosk: pick a house, enter a phone number, get called as that resident |
| `/console` | Dispatcher map, requests, plan approval, closures, alerts |
| `/driver` (PWA) | Offers, run, GPS, pickups, SOS, man-down (`app/driver/safety.ts`) |
| `/calls` | Live calls, transcripts, records |
| `/system` | Metrics, evals, simulated dispatch comparison, audit log |
| `/drill` | Labeled drill page for the zone watcher (never styled as a county site) |
| `/report` | Photo hazard reports (placeholder) |

- `lib/api.ts`: REST client for CONTRACT §2.
- `lib/live.ts`: one `/live` socket → Zustand store per collection, reconnect with backoff + REST resync.
- `lib/theme.ts` + `components/ThemeToggle.tsx`: light/dark, following the system by default.
- `app/console/MapView.tsx`: MapLibre + deck.gl map (OpenFreeMap tiles). `scripts/copy-maplibre-worker.mjs`
  copies the MapLibre worker into `public/` before dev and build.
- `components/Shell.tsx`: page shell and the `SimBadge`.

Vercel: project root = `web/`. Production branch `main`; `develop` and `staging` get branch deploys.
Set `NEXT_PUBLIC_API_URL` per environment (`https://api-dev.<domain>`, `https://api-staging.<domain>`, `https://api.<domain>`).
