#!/usr/bin/env bash
set -euo pipefail

BUILD_DIR="$1"
REPO_ROOT="$2"
INSTALL_DEPENDENCIES="$3"
shift 3
SOURCE_PATHS=("$@")

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

for p in "${SOURCE_PATHS[@]}"; do
  dest_parent="$BUILD_DIR/$(dirname "$p")"
  mkdir -p "$dest_parent"
  cp -R "$REPO_ROOT/$p" "$dest_parent/"
done

if [ "$INSTALL_DEPENDENCIES" = "true" ]; then
  LOCKED_REQUIREMENTS="${BUILD_DIR}.requirements.txt"
  uv export --quiet --project "$REPO_ROOT" --frozen --no-dev --no-emit-project --no-hashes \
    --format requirements.txt -o "$LOCKED_REQUIREMENTS"
  uv pip install --quiet --python 3.13 --target "$BUILD_DIR" -r "$LOCKED_REQUIREMENTS"
  rm -f "$LOCKED_REQUIREMENTS"
fi

find "$BUILD_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
