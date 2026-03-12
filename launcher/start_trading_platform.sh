#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$ROOT_DIR/logs"
PID_FILE="$RUN_DIR/backend.pid"
LOG_FILE="$LOG_DIR/backend.log"
HOST="127.0.0.1"
PORT="8000"
APP_URL="http://$HOST:$PORT"

mkdir -p "$RUN_DIR" "$LOG_DIR"

is_platform_up() {
  curl -fsS "$APP_URL/api/bot/status" >/dev/null 2>&1
}

frontend_needs_build() {
  if [ ! -f "$FRONTEND_DIR/dist/index.html" ]; then
    return 0
  fi

  if [ "$FRONTEND_DIR/package.json" -nt "$FRONTEND_DIR/dist/index.html" ]; then
    return 0
  fi

  if find "$FRONTEND_DIR/src" -type f -newer "$FRONTEND_DIR/dist/index.html" | grep -q .; then
    return 0
  fi

  return 1
}

ensure_backend_ready() {
  cd "$BACKEND_DIR"

  if [ ! -x ".venv/bin/python" ]; then
    python3 -m venv .venv
  fi

  if [ ! -f ".venv/.deps-ready" ] || [ "requirements.txt" -nt ".venv/.deps-ready" ]; then
    .venv/bin/pip install -r requirements.txt >/dev/null
    touch .venv/.deps-ready
  fi
}

ensure_frontend_ready() {
  cd "$FRONTEND_DIR"

  if [ ! -f "node_modules/vite/bin/vite.js" ]; then
    npm install >/dev/null
  fi

  if frontend_needs_build; then
    npm run build >/dev/null
  fi
}

start_backend() {
  cd "$BACKEND_DIR"
  nohup .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
}

if is_platform_up; then
  open "$APP_URL"
  echo "Trading Platform is already running."
  exit 0
fi

if [ -f "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE")"
  if kill -0 "$old_pid" >/dev/null 2>&1; then
    open "$APP_URL"
    echo "Trading Platform process already exists."
    exit 0
  fi
  rm -f "$PID_FILE"
fi

ensure_backend_ready
ensure_frontend_ready
start_backend

for _ in {1..60}; do
  if is_platform_up; then
    open "$APP_URL"
    echo "Trading Platform started."
    exit 0
  fi
  sleep 1
done

echo "Failed to start Trading Platform. Check $LOG_FILE" >&2
exit 1
