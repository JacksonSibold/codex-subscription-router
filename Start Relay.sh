#!/usr/bin/env sh
set -eu

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RELAY_DIR="$DIR/router"
if [ -f "$DIR/model-router/manager.py" ]; then
  RELAY_DIR="$DIR/model-router"
fi
if [ -n "${PYTHON:-}" ]; then
  PYTHON_BIN="$PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
else
  PYTHON_BIN=python
fi
exec "$PYTHON_BIN" "$RELAY_DIR/manager.py" --open
