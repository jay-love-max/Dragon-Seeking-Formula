#!/bin/bash
set -euo pipefail

# A-share Daily Post-Market Recap & 1-to-2 Board Relay Analysis

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=== A-share Daily Recap Engine ==="
echo "Date: $(date +'%Y-%m-%d %H:%M:%S')"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3)"
    else
        PYTHON_BIN="$(command -v python)"
    fi
fi

"$PYTHON_BIN" src/recap_engine.py "$@"
echo "Done!"
