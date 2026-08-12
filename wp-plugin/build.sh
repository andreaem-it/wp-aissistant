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

# Il widget non vive più qui: si costruisce da sdk/widget e si copia nel pacchetto. È lo stesso
# artefatto che servirà il CDN, quindi il plugin e i siti non WordPress caricano lo stesso
# codice — un widget solo, non due che divergono alla prima correzione fatta da una parte sola.
# La convenzione «nessun bundler» resta vera dove conta: sul sito del cliente, a runtime.
WIDGET_DIR="$SCRIPT_DIR/../sdk/widget"
echo "building the widget bundle from sdk/widget"
( cd "$WIDGET_DIR" && npm run --silent build )
cp "$WIDGET_DIR/dist/wpai-widget.js" "$PLUGIN_DIR/assets/wpai-widget.js"
cp "$WIDGET_DIR/dist/wpai-widget.css" "$PLUGIN_DIR/assets/wpai-widget.css"
node "$SCRIPT_DIR/generate-widget-build.mjs" \
  "$WIDGET_DIR/dist/integrity.json" "$PLUGIN_DIR/widget-build.php"

# Il plugin punta a una versione **fissa** del CDN: se quella versione non è ancora pubblicata,
# ogni sito cade sul ripiego locale e la distribuzione dal CDN non serve a niente — in silenzio.
# Qui si avvisa e basta: costruire il plugin deve funzionare anche offline, quindi non è un
# errore. L'ordine giusto di rilascio è: prima il tag `widget-v*`, poi la release del plugin.
widget_version=$(node -p "require('$WIDGET_DIR/dist/integrity.json').version")
cdn_url="https://cdn.wpaissistant.it/widget/$widget_version/wpai-widget.js"
if command -v curl >/dev/null 2>&1; then
  status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$cdn_url" || echo "000")
  if [ "$status" = "200" ]; then
    echo "widget $widget_version pubblicato sul CDN"
  else
    echo "ATTENZIONE: il widget $widget_version non è sul CDN ($cdn_url risponde $status)."
    echo "            I siti cadranno sulla copia locale. Pubblica prima il tag widget-v$widget_version."
  fi
fi

mkdir -p "$DIST_DIR"
ZIP="$DIST_DIR/wp-aissistant-$version.zip"
rm -f "$ZIP"

( cd "$SCRIPT_DIR" && zip -rq "$ZIP" wp-aissistant -x '*.DS_Store' -x '*/.*' )

echo "built $ZIP ($(du -h "$ZIP" | cut -f1), version $version)"
