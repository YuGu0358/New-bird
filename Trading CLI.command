#!/bin/zsh
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"
exec "./launcher/open_trading_cli.sh"
