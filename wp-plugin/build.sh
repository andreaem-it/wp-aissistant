#!/usr/bin/env bash
# Builds a distributable zip of the WP AIssistant plugin.
# The version is read from the plugin header, and the archive contains the
# `wp-aissistant/` folder so it extracts straight into wp-content/plugins/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$SCRIPT_DIR/wp-aissistant"
DIST_DIR="$SCRIPT_DIR/dist"

VERSION="$(grep -m1 -E '^\s*\*\s*Version:' "$PLUGIN_DIR/wp-aissistant.php" \
  | sed -E 's/.*Version:[[:space:]]*//' | tr -d '[:space:]')"
if [ -z "$VERSION" ]; then
  echo "error: could not read Version from $PLUGIN_DIR/wp-aissistant.php" >&2
  exit 1
fi

mkdir -p "$DIST_DIR"
ZIP="$DIST_DIR/wp-aissistant-$VERSION.zip"
rm -f "$ZIP"

( cd "$SCRIPT_DIR" && zip -r -q "$ZIP" wp-aissistant \
    -x '*.DS_Store' -x '*/.*' )

echo "built $ZIP ($(du -h "$ZIP" | cut -f1))"
