#!/usr/bin/env bash
# Install zhulong into the active Hermes profile's plugins directory.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${HERMES_HOME:-$HOME/.hermes}/plugins/zhulong"
mkdir -p "$DEST"
for f in plugin.yaml __init__.py storage.py sensor.py commands.py calibrate.py; do
  cp "$HERE/$f" "$DEST/$f"
done
echo "zhulong installed to $DEST"
echo "enable it with:  hermes plugins enable zhulong"
