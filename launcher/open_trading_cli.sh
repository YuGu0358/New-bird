#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
HARNESS_DIR="$ROOT_DIR/agent-harness"
VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"
VENV_PIP="$BACKEND_DIR/.venv/bin/pip"
CLI_BIN="$BACKEND_DIR/.venv/bin/cli-anything-trading-platform"

cd "$BACKEND_DIR"

if [ ! -x "$VENV_PYTHON" ]; then
  python3 -m venv .venv
fi

if [ ! -f ".venv/.deps-ready" ] || [ "requirements.txt" -nt ".venv/.deps-ready" ]; then
  "$VENV_PIP" install -r requirements.txt >/dev/null
  touch .venv/.deps-ready
fi

if [ ! -x "$CLI_BIN" ] || [ "$HARNESS_DIR/setup.py" -nt "$CLI_BIN" ]; then
  cd "$HARNESS_DIR"
  "$VENV_PIP" install . >/dev/null
  cd "$BACKEND_DIR"
fi

exec "$CLI_BIN" "$@"
