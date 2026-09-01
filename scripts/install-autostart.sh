#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")"/.. && pwd)"
TARGET_DIR="$HOME/.config/autostart"
mkdir -p "$TARGET_DIR"
sed "s|__EXEC__|$HERE/run.sh|" "$HERE/scripts/xeneon-edge.desktop.template" \
  > "$TARGET_DIR/xeneon-edge.desktop"
echo "Installed: $TARGET_DIR/xeneon-edge.desktop"
