/**
 * Scrive versione e impronte SRI dell'artefatto del widget in un file PHP.
 *
 * Generate, non scritte a mano: un'impronta copiata che non corrisponde al file fa rifiutare lo
 * script al browser, e il sintomo è un widget che sparisce senza un errore che spieghi perché.
 * Qui le due cose vengono per costruzione dallo stesso artefatto appena costruito.
 *
 * Uso: node generate-widget-build.mjs <integrity.json> <destinazione.php>
 */
import { readFile, writeFile } from "node:fs/promises";

const [source, target] = process.argv.slice(2);
if (!source || !target) {
  console.error("uso: generate-widget-build.mjs <integrity.json> <destinazione.php>");
  process.exit(1);
}

const data = JSON.parse(await readFile(source, "utf8"));
const quote = (value) => "'" + String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'") + "'";

await writeFile(target, [
  "<?php",
  "// Generato da wp-plugin/build.sh a partire da sdk/widget. Non modificare a mano.",
  "",
  "return [",
  `    'version' => ${quote(data.version)},`,
  `    'js' => ${quote(data.files["wpai-widget.js"])},`,
  `    'css' => ${quote(data.files["wpai-widget.css"])},`,
  "];",
  "",
].join("\n"));
