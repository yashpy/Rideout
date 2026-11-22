# infra/ — VM + Caddy + three API environments

## Go-live checklist

Do these in order. Each line says how you know it worked.

1. **Atlas**: one M0 cluster → Database Access: a user → Network Access: `0.0.0.0/0` → Connect → copy the
   `mongodb+srv://...` URI. The three databases (`rideout_dev`, `rideout_staging`, `rideout_prod`) are created
   on first write; `ENV` picks which one.
2. **secrets.env** on your laptop: copy `.env.example`, fill in `MONGODB_URI`, `INTERNAL_TOKEN` (`openssl rand -hex 24`)
   and whatever keys you have (Gemini, Anthropic, ElevenLabs, FIRMS, TinyFish). Never commit it.
3. **VM** (Vultr or any host): Ubuntu 24.04, 2 vCPU / 4 GB, your SSH key. Then:
   ```bash
   scp infra/bootstrap-vm.sh secrets.env root@<VM_IP>:/tmp/
   ssh root@<VM_IP> 'bash /tmp/bootstrap-vm.sh <domain> /tmp/secrets.env'
   ```
   Installs Docker, opens 22/80/443, writes `/opt/rideout/.env` and `dev|staging|prod.env` (mode 600).
4. **DNS** (registrar or Cloudflare, proxy **off**): A records `api-dev`, `api-staging`, `api` → VM IP.
   `dig +short api-dev.<domain>` returns the IP. (Without a domain, `<ip>.sslip.io` names work.)
5. **GitHub secrets**: make a deploy key just for CI: `ssh-keygen -t ed25519 -f rideout_deploy -N ''`, append
   `rideout_deploy.pub` to the VM's `~/.ssh/authorized_keys`. Repo → Settings → Secrets → Actions →
   **repository** secrets `VULTR_HOST` (IP), `VULTR_USER` (`root`), `VULTR_SSH_KEY` (contents of `rideout_deploy`).
   Repository secrets reach all three Environments, so you add them once. Then delete the local private key copy.
6. **First deploy**: Actions → **deploy** → Run workflow → `dev` (or push to `develop`). Green run, then
   `curl https://api-dev.<domain>/health` shows `"env":"dev"` and the sha. Repeat for `staging` and `prod`.
7. **Vercel**: Add project → this repo → Root Directory `web`. Production branch `main`.
   Env var `NEXT_PUBLIC_API_URL`: Production = `https://api.<domain>`; Preview for branch `develop` =
   `https://api-dev.<domain>`; Preview for branch `staging` = `https://api-staging.<domain>`.
   Optional domains: `app.<domain>` → production, `dev.<domain>` → branch `develop`, `staging.<domain>` → branch
   `staging` (CNAME each to `cname.vercel-dns.com`).
8. **Check everything**: `uv run --project api python scripts/smoke.py --domain <domain>` → all three envs green.
9. **Release**: PR `develop → staging` and merge it, then PR `staging → main` (`scripts/release.sh` does both).

## What bootstrap-vm.sh does (by hand, if you prefer)

```bash
curl -fsSL https://get.docker.com | sh
sudo mkdir -p /opt/rideout && sudo chown $USER /opt/rideout
cd /opt/rideout
cat > .env <<'X'
DOMAIN=<your-domain>
API_IMAGE=ghcr.io/<owner>/rideout-api
X
# one secrets file per env, copied from .env.example (ENV is set by compose)
nano dev.env staging.env prod.env
```

## GitHub Environments (`dev`, `staging`, `production`)

The deploy job runs in the Environment for its branch. `VULTR_HOST`, `VULTR_USER`, `VULTR_SSH_KEY` can live
in each Environment or once as repository secrets (simplest, one VM). The deploy job logs the VM into GHCR
with the workflow's token, so the image can stay private.

## MongoDB on the VM (dev and staging)

Atlas M0 caps us at about 100 operations a second and every call crosses the internet, so a 6,000-home
seed and census crawled. The compose file now runs `mongo` (MongoDB 7, single-node replica set, private,
0.5 GB cache) next to the APIs. An env uses it only when its env file says so.

Switch from your phone: GitHub → Actions → **vm-mongo** → Run workflow → env `dev`, database `vm`
(`atlas` switches back; it also seeds the default world). Or by hand, on the VM:
```bash
cd /opt/rideout
docker compose up -d --wait mongo                      # first start also runs rs.initiate
sed -i 's|^MONGODB_URI=.*|MONGODB_URI=mongodb://mongo:27017/?replicaSet=rs0|' dev.env staging.env
docker compose up -d api-dev api-staging               # restart with the new URI
curl https://api-dev.<domain>/health                   # ok:true
```
Then open the console and press **Seed** (the new database starts empty). Undo = put the Atlas URI back in
the env file and `docker compose up -d api-dev`.

- No published port: nothing outside the VM can reach it. To look inside:
  `docker compose exec mongo mongosh rideout_dev`.
- Data lives in the `mongo_data` volume and survives redeploys. It is not backed up; the data is simulated.
- prod.env keeps its Atlas URI until the team decides (Atlas is what the MongoDB prize asks about).

## Deploy / rollback

Merging to `develop` / `staging` / `main` deploys `api-dev` / `api-staging` / `api-prod`.
Rollback: Actions → **deploy** → Run workflow → pick env + an older image tag (a git sha).

Check: `curl https://api-dev.<domain>/health` → `{"ok":true,"env":"dev","gitSha":"..."}`
