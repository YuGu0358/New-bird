#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
OUTPUT_DIR="$ROOT_DIR/output/desktop"
APP_NAME="Trading Raven Platform"

mkdir -p "$OUTPUT_DIR"

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
rm -rf build dist

.venv/bin/python -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --paths "$BACKEND_DIR" \
  --hidden-import aiosqlite \
  --collect-submodules aiosqlite \
  --add-data "$FRONTEND_DIR/dist:frontend_dist" \
  desktop_app.py

xattr -cr "dist/$APP_NAME.app"
codesign --force --deep -s - "dist/$APP_NAME.app" >/dev/null 2>&1 || true

rm -rf "$OUTPUT_DIR/$APP_NAME.app"
cp -R "dist/$APP_NAME.app" "$OUTPUT_DIR/"

echo "Desktop app built at: $OUTPUT_DIR/$APP_NAME.app"
