#!/usr/bin/env bash
# MySpotify - Standalone Edition launcher (macOS / Linux / Git Bash).
# Starts the local backend and opens your browser. No domain, tunnel, or login required.
set -euo pipefail

cd "$(dirname "$0")/backend"

# Resolve the venv interpreter (Scripts on Windows/Git Bash, bin elsewhere).
if [ -x "../.venv/Scripts/python.exe" ]; then
    PY="../.venv/Scripts/python.exe"
elif [ -x "../.venv/bin/python" ]; then
    PY="../.venv/bin/python"
else
    echo "Could not find the virtual environment under ../.venv"
    echo "Create it and install deps: python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt"
    exit 1
fi

exec "$PY" -m app.desktop
