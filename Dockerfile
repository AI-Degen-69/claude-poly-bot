# Railway/Fly/Render image: paper bot + dashboard in one long-lived container.
#
# Stage 1 builds the Vite UI so the container serves a static bundle instead of
# running a dev server 24/7. Stage 2 is the Python runtime.
#
# DEPLOY IN A NON-US REGION. Binance geo-blocks US IPs, and the Binance spot
# gate is the strategy -- in a US region the gate fails closed and the bot
# collects zero fills while the healthcheck stays green. deploy/run_service.py
# preflights this and exits non-zero rather than running blind.

# ---- stage 1: UI ----------------------------------------------------------
FROM node:20-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
RUN npm run build

# Inject deploy metadata into the built HTML so the dashboard footer can show
# which commit + Railway deployment is live. DEPLOY_SHA is passed via build arg
# (set from the git SHA before `railway up`); RAILWAY_DEPLOYMENT_ID is injected
# automatically by Railway during the build. If either is missing, the footer
# simply stays hidden (DeployFooter returns null).
ARG DEPLOY_SHA=unknown
RUN RLY_ID="${RAILWAY_DEPLOYMENT_ID:-unknown}" && \
    sed -i "s#</body>#<script>window.__DEPLOY__={sha:\"${DEPLOY_SHA}\",railway:\"${RLY_ID}\"};</script></body>#" dist/index.html

# ---- stage 2: runtime -----------------------------------------------------
FROM python:3.12-slim
WORKDIR /app

# gcc/libssl for web3 + clob client wheels that lack manylinux builds.
RUN apt-get update && apt-get install -y --no-install-recommends gcc libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY strategy/ /app/strategy/
COPY server/  /app/server/
COPY deploy/  /app/deploy/
COPY --from=ui /ui/dist /app/ui/dist

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8787

# Secrets are injected as env vars by the host, never baked in:
#   TURSO_URL, TURSO_TOKEN   (storage; without these data dies on redeploy)
#   PRIVATE_KEY, WALLET_ADDRESS, FUNDER_ADDRESS, CLOB_API_*
#     ^ PLACEHOLDERS ONLY. Paper mode never builds a CLOB client
#       (strategy/main.py: `build_client(cfg) if live else None`), so the real
#       funded key must never be put on this box.

EXPOSE 8787
CMD ["python", "deploy/run_service.py"]
