#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../vendor/tickflow-stock-panel"
exec ./dev.sh "$@"
