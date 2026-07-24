#!/usr/bin/env bash
# Packages the wp-aissistant/ plugin directory into a versioned, installable zip.
# Usage: ./build.sh   (run from wp-plugin/, or anywhere — paths are relative to this script)
set -euo pipefail

cd "$(dirname "$0")"
PLUGIN_FILE="wp-aissistant/wp-aissistant.php"

header_version=$(grep -m1 -oE 'Version:\s*[0-9][0-9A-Za-z.-]*' "$PLUGIN_FILE" | grep -oE '[0-9][0-9A-Za-z.-]*')
const_version=$(grep -m1 -oE "define\('WPAI_VERSION', '[^']+'\)" "$PLUGIN_FILE" | grep -oE "[0-9][0-9A-Za-z.-]*")

if [ "$header_version" != "$const_version" ]; then
  echo "Version mismatch: docblock header says $header_version, WPAI_VERSION constant says $const_version." >&2
  echo "Update both in $PLUGIN_FILE before building." >&2
  exit 1
fi

version="$header_version"
out_dir="dist"
out_zip="$out_dir/wp-aissistant-${version}.zip"

mkdir -p "$out_dir"
rm -f "$out_zip"
zip -rq "$out_zip" wp-aissistant -x '*.DS_Store'

echo "Built $out_zip (version $version)"
