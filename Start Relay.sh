#!/usr/bin/env sh
set -eu

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -x "$DIR/Relay/Relay" ]; then
  exec "$DIR/Relay/Relay"
fi
if [ -f "$DIR/router/manager.py" ] && [ -x "$DIR/desktop/dist/Relay/Relay" ]; then
  exec "$DIR/desktop/dist/Relay/Relay" --dev
fi
if [ -x "$DIR/Relay.app/Contents/MacOS/Relay" ]; then
  exec "$DIR/Relay.app/Contents/MacOS/Relay"
fi
if [ -x "$DIR/model-router/desktop/Relay" ]; then
  exec "$DIR/model-router/desktop/Relay"
fi
if [ -x "$DIR/model-router/desktop/Relay.app/Contents/MacOS/Relay" ]; then
  exec "$DIR/model-router/desktop/Relay.app/Contents/MacOS/Relay"
fi

RELAY_DIR="$DIR/router"
if [ -f "$DIR/model-router/manager.py" ]; then
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
exec "$PYTHON_BIN" "$RELAY_DIR/manager.py" --open
