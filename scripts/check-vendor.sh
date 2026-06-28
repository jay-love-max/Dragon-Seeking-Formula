#!/usr/bin/env bash
# Verify the vendored tickflow-stock-panel checkout matches the hash locked in vendor/VERSION.
# Exits non-zero with a warning if drift is detected (run scripts/restore-vendor.sh to fix).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
VENDOR_DIR="$ROOT/vendor/tickflow-stock-panel"
VERSION_FILE="$ROOT/vendor/VERSION"

if [[ ! -f "$VERSION_FILE" ]]; then
  echo "error: $VERSION_FILE not found" >&2
  exit 1
fi

LOCKED_HASH="$(grep -Eo '^[0-9a-f]{7,40}$' "$VERSION_FILE" | head -1 | tr -d '[:space:]')"

if [[ -z "$LOCKED_HASH" ]]; then
  echo "error: no valid commit hash found in $VERSION_FILE" >&2
  exit 1
fi

if [[ ! -d "$VENDOR_DIR/.git" ]]; then
  echo "error: vendor checkout missing at $VENDOR_DIR. Run scripts/restore-vendor.sh" >&2
  exit 1
fi

CURRENT_HASH="$(git -C "$VENDOR_DIR" rev-parse HEAD)"

if [[ "$CURRENT_HASH" != "$LOCKED_HASH" ]]; then
  echo "warning: vendor HEAD ($CURRENT_HASH) != locked ($LOCKED_HASH)" >&2
  echo "run: bash scripts/restore-vendor.sh" >&2
  exit 1
fi

if [[ -n "$(git -C "$VENDOR_DIR" status --porcelain)" ]]; then
  echo "warning: vendor working tree has local changes" >&2
  echo "run: git -C $VENDOR_DIR reset --hard" >&2
  echo "run: bash scripts/restore-vendor.sh" >&2
  exit 1
fi

echo "vendor ok @ $CURRENT_HASH"
