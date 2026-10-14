#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$APP_DIR"
# Optional per-machine Linux support; excluded from Git. Fresh installations
# should install their distribution's Qt runtime libraries.
NATIVE_LIB="$APP_DIR/.native/usr/lib/x86_64-linux-gnu"
if [[ -d "$NATIVE_LIB" ]]; then
    export LD_LIBRARY_PATH="$NATIVE_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
if [[ -x "$APP_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$APP_DIR/.venv/bin/python"
elif [[ -n "${POLIMI_PYTHON:-}" ]]; then
    PYTHON_BIN="$POLIMI_PYTHON"
elif command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN="python3.12"
else
    PYTHON_BIN="python3"
fi
"$PYTHON_BIN" "$APP_DIR/setup_environment.py"
exec "$APP_DIR/.venv/bin/python" "$APP_DIR/bead_counter.py" "$@"
