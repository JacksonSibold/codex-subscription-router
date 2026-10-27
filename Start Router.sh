#!/usr/bin/env sh
set -eu

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RELAY_DIR="$DIR/router"
if [ -f "$DIR/model-router/router.py" ]; then
  RELAY_DIR="$DIR/model-router"
else
  CODEX_ROUTER_DEV=1
  CODEX_HOME="$DIR/.dev-codex"
  CODEX_ROUTER_SETTINGS="$DIR/.dev-codex/router-settings.json"
  CODEX_ROUTER_USAGE_DB="$DIR/.dev-codex/router-usage.sqlite"
  export CODEX_ROUTER_DEV CODEX_HOME CODEX_ROUTER_SETTINGS CODEX_ROUTER_USAGE_DB
fi
if [ -n "${PYTHON:-}" ]; then
  PYTHON_BIN="$PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
else
  PYTHON_BIN=python
fi
exec "$PYTHON_BIN" "$RELAY_DIR/router.py"
