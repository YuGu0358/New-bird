# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Stage 1 — build the React/Vite "Trading Raven Console" (frontend-v2/)
# ---------------------------------------------------------------------------
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend-v2
COPY frontend-v2/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend-v2 ./
RUN npm run build


# ---------------------------------------------------------------------------
# Stage 2 — Python runtime (FastAPI + factor pipeline + APScheduler)
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DATA_DIR=/app/data \
    TRADING_PLATFORM_FRONTEND_DIST=/app/frontend-v2/dist \
    FACTOR_EVOLUTION_AUTOSTART=false

# System deps for QuantLib + lightgbm
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY agent-harness /app/agent-harness
COPY --from=frontend-build /app/frontend-v2/dist /app/frontend-v2/dist

# Persistent volume mount point — Railway mounts here
RUN mkdir -p /app/data

EXPOSE 8000

# Healthcheck on /api/health (the endpoint added in DEPLOY-PREP)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3).status == 200 else 1)" || exit 1

# Single worker — APScheduler + factor loop must not be duplicated.
CMD ["sh", "-c", "cd /app/backend && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
