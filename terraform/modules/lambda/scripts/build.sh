#!/usr/bin/env bash
set -euo pipefail

BUILD_DIR="$1"
REPO_ROOT="$2"
REQUIREMENTS_FILE="$3"
shift 3
SOURCE_PATHS=("$@")

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

for p in "${SOURCE_PATHS[@]}"; do
  dest_parent="$BUILD_DIR/$(dirname "$p")"
  mkdir -p "$dest_parent"
  cp -R "$REPO_ROOT/$p" "$dest_parent/"
done

if [ -n "$REQUIREMENTS_FILE" ] && [ "$REQUIREMENTS_FILE" != "null" ]; then
  pip install --quiet --no-cache-dir --target "$BUILD_DIR" -r "$REPO_ROOT/$REQUIREMENTS_FILE"
fi

find "$BUILD_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
