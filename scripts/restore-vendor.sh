#!/usr/bin/env bash
# Restore the vendored tickflow-stock-panel checkout to the commit hash locked in vendor/VERSION.
# Idempotent: if the checkout already exists it only fetches and checks out the locked hash.
# Run this once after a fresh clone of this repository.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
VENDOR_DIR="$ROOT/vendor/tickflow-stock-panel"
VERSION_FILE="$ROOT/vendor/VERSION"
REPO_URL="https://github.com/shy3130/tickflow-stock-panel.git"

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
  if [[ -d "$VENDOR_DIR" && -n "$(ls -A "$VENDOR_DIR" 2>/dev/null)" ]]; then
    echo "error: $VENDOR_DIR exists but is not a git repository" >&2
    echo "remove or clear the directory and re-run scripts/restore-vendor.sh" >&2
    exit 1
  fi
  echo "Cloning tickflow-stock-panel into $VENDOR_DIR ..."
  git clone "$REPO_URL" "$VENDOR_DIR"
fi

echo "Fetching and checking out tickflow-stock-panel @ $LOCKED_HASH ..."
git -C "$VENDOR_DIR" fetch --quiet origin
git -C "$VENDOR_DIR" checkout "$LOCKED_HASH"

echo "vendor restored to $LOCKED_HASH"
