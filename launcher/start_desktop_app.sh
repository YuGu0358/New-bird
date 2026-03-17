#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

cd "$BACKEND_DIR"

if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi

.venv/bin/pip install -r requirements-desktop.txt >/dev/null

cd "$FRONTEND_DIR"

if [ ! -f "node_modules/vite/bin/vite.js" ]; then
  npm install >/dev/null
fi

npm run build >/dev/null

cd "$BACKEND_DIR"
exec .venv/bin/python desktop_app.py
