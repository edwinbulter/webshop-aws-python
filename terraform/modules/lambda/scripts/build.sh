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
  # --python-platform pins wheel selection to Lambda's actual runtime
  # (x86_64, glibc-based Amazon Linux), not whatever OS runs this script. A
  # no-op today since flask/mangum/asgiref/boto3/botocore are all pure-Python,
  # but silently wrong the day a compiled dependency is added without it.
  uv pip install --quiet --python 3.13 --python-platform x86_64-manylinux2014 \
    --target "$BUILD_DIR" -r "$LOCKED_REQUIREMENTS"
  rm -f "$LOCKED_REQUIREMENTS"
fi

find "$BUILD_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
