#!/usr/bin/env bash
# Orchestration entry point for CI / automation: restore then verify the vendored
# tickflow-stock-panel checkout so it matches the hash locked in vendor/VERSION.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"

bash "$ROOT/scripts/restore-vendor.sh"
bash "$ROOT/scripts/check-vendor.sh"
