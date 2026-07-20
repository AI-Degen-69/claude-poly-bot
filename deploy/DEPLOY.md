# 24/7 Deploy — paper simulation on Railway + Turso

Runs the bonereaper-calibrated paper bot and its dashboard in one container, so
data collection continues with your PC off, and you can check it from anywhere.

---

## What's already built (nothing left for me to do)

| File | Purpose |
|---|---|
| `Dockerfile` | 2-stage: builds the Vite UI, then the Python runtime |
| `.dockerignore` | keeps `.env`, `trades.db`, and **`ui/node_modules`** out of the image |
| `railway.toml` | Dockerfile builder + `/api/health` healthcheck |
| `deploy/run_service.py` | preflight → supervises bot → serves dashboard on `$PORT` |
| `deploy/.env.deploy.example` | every variable to paste into Railway |
| `bot/store.py` | Turso (libSQL) when `TURSO_URL` set, else local SQLite |
| `server/dashboard.py` | reads through `store`, serves `ui/dist` at `/` |

**Verified locally:** libsql round-trips and accepts `auth_token`; a `libsql://`
URL reaches the Hrana layer; preflight passes clean and exits 1 on a bad config;
`npm run build` (which runs `tsc -b`) succeeds.

**Not verified:** the Docker image has never been built — Docker Desktop was not
running on the dev machine. Railway's first build is therefore the real test.

---

## Two things that will silently ruin the run

**1. Region.** Binance 451s US IPs. The spot gate *is* the strategy, so in a US
region the feed dies, the gate fails closed, and you collect **zero fills while
the healthcheck stays green**. Set the Railway service region to
**europe-west (Amsterdam)** or any non-US region.

**2. Storage.** Without `TURSO_URL` (or a mounted volume at `POLYBOT_DB`) the
container writes to its own filesystem and **every redeploy wipes your data.**

`deploy/run_service.py` preflights both and exits non-zero rather than running
blind. Check the deploy logs for `[preflight] all checks passed`.

---

## Your steps

### 1. Turso database
1. Sign up at <https://turso.tech> (free tier is plenty — we write ~30k rows/day).
2. Create a database, any name (e.g. `polybot`).
3. Grab two values:
   - **URL** — looks like `libsql://polybot-<org>.turso.io`
   - **Token** — a read/write token
   Via the web UI ("Connect"), or CLI: `turso db show polybot --url` and
   `turso db tokens create polybot`.

### 2. Push this repo to GitHub
The repo already points at `AI-Degen-69/poly-trading-bot`. I can commit and push
on request, or you can.

### 3. Railway
1. Sign up at <https://railway.app>, **New Project → Deploy from GitHub repo**.
2. Pick the repo. It auto-detects `railway.toml` and builds the Dockerfile.
3. **Settings → Region → europe-west.** Do this before the first deploy.
4. **Variables** → paste everything from `deploy/.env.deploy.example`, filling in
   only `TURSO_URL` and `TURSO_TOKEN`. **Leave the wallet fields as the fake
   placeholders.** Paper mode never builds a CLOB client
   (`bot/main.py`: `build_client(cfg) if live else None`), so a real key would
   add risk for zero benefit.
5. **Settings → Networking → Generate Domain** for a public URL.

### 4. Verify
- Deploy logs show `[preflight] all checks passed` and `[bot] starting (paper/sim)`
- `https://<your-app>.up.railway.app/api/health` → `{"ok":true,...}`
- Open the domain root → the dashboard
- After ~10 min the decision log should be moving

---

## Access & security

The dashboard has **no authentication**. A Railway public domain is world-readable
by anyone with the link. It exposes only simulated trading data and no secrets,
but if you'd rather it stay private, either skip the public domain and use the
Railway CLI (`railway link` then port-forward), or put Cloudflare Access in front.

---

## Operating notes

- **Cost:** Railway ~$5/mo (free tier retired). Turso free tier is sufficient.
- **Storage:** `decisions` grows ~30k rows/day; `run_service.py` prunes rows
  older than 30 days daily. `orders` and `resolutions` are kept forever — PnL is
  reconstructed from those two.
- **Two writers double-count.** If Railway is collecting, stop the local bot
  (`bash scripts/stop_live.sh`) or point them at different databases.
- **Turso write latency** is the main unknown at 4 writes/sec. If the poll loop
  lags, switch to a Railway volume: set `POLYBOT_DB=/data/trades.db`, mount a
  volume at `/data`, and drop `TURSO_URL`. Same image, one variable different.
- **Never set `--live` on the hosted box.** `bot/config.py` has `sim_only=True`
  and `bot/main.py` refuses to arm while it's set; preflight fails too.
