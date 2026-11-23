# infra/ — Render + Vercel

| File | What |
|---|---|
| `render/api.Dockerfile` | The API image Render builds (`render.yaml` at the repo root) |
| `docker-compose.local.yml` | Local MongoDB as a single-node replica set (change streams for `/live` need one) |

## Go-live checklist

Do these in order. Each line says how you know it worked.

1. **Atlas**: one M0 cluster → Database Access: a user → Network Access: `0.0.0.0/0` → Connect → copy the
   `mongodb+srv://...` URI. The databases (`rideout_dev`, `rideout_staging`, `rideout_prod`) are created on first
   write; `ENV` picks which one.
2. **Render**: Dashboard → New → Blueprint → this repo. It creates `rideout-api` and `rideout-voice` from
   `render.yaml`. Paste the Atlas password and any optional keys (Gemini, Anthropic, ElevenLabs, FIRMS) when Render
   asks. `curl https://<api>.onrender.com/health` shows `"ok":true` and the sha.
3. **Vercel**: Add project → this repo → Root Directory `web`. Production branch `main`.
   Env var `NEXT_PUBLIC_API_URL` = the Render API URL.
4. **Check everything**: `uv run --project api python scripts/smoke.py` against the deployed API.

Free Render services sleep after ~15 min idle and wake on the next request.
