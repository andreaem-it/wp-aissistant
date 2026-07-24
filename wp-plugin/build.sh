#!/usr/bin/env bash
# Packages the wp-aissistant/ plugin directory into a versioned, installable zip.
# Usage: ./build.sh   (run from wp-plugin/, or anywhere — paths are relative to this script)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$SCRIPT_DIR/wp-aissistant"
PLUGIN_FILE="$PLUGIN_DIR/wp-aissistant.php"
DIST_DIR="$SCRIPT_DIR/dist"

header_version=$(grep -m1 -oE 'Version:\s*[0-9][0-9A-Za-z.-]*' "$PLUGIN_FILE" | grep -oE '[0-9][0-9A-Za-z.-]*')
const_version=$(grep -m1 -oE "define\('WPAI_VERSION', '[^']+'\)" "$PLUGIN_FILE" | grep -oE "[0-9][0-9A-Za-z.-]*")

if [ -z "$header_version" ]; then
  echo "error: could not read Version from $PLUGIN_FILE" >&2
  exit 1
fi
if [ "$header_version" != "$const_version" ]; then
  echo "Version mismatch: docblock header says $header_version, WPAI_VERSION constant says $const_version." >&2
  echo "Update both in $PLUGIN_FILE before building." >&2
  exit 1
fi

version="$header_version"
mkdir -p "$DIST_DIR"
ZIP="$DIST_DIR/wp-aissistant-$version.zip"
rm -f "$ZIP"

( cd "$SCRIPT_DIR" && zip -rq "$ZIP" wp-aissistant -x '*.DS_Store' -x '*/.*' )

echo "built $ZIP ($(du -h "$ZIP" | cut -f1), version $version)"
