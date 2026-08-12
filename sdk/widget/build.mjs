/**
 * Build del bundle.
 *
 * Produce un IIFE senza dipendenze, non un modulo: il widget viene incluso con un `<script>` in
 * pagine che non hanno un bundler, ed è il caso che deve funzionare senza chiedere niente a
 * nessuno. La convenzione «nessun bundler» del plugin resta vera dov'è importante — a runtime,
 * sul sito del cliente — e cade solo qui, in fase di build, dove abbiamo Node.
 */
import { build } from "esbuild";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";

// La versione dell'artefatto è quella del pacchetto: è ciò che finisce nel percorso immutabile
// del CDN, e deve essere una sola cosa in un posto solo.
const { version } = JSON.parse(await readFile(new URL("./package.json", import.meta.url), "utf8"));

await mkdir(new URL("./dist/", import.meta.url), { recursive: true });

const result = await build({
  entryPoints: ["src/index.js"],
  bundle: true,
  format: "iife",
  target: ["es2020"],
  minify: true,
  sourcemap: false,
  outfile: "dist/wpai-widget.js",
  legalComments: "none",
  metafile: true,
});

await copyFile("src/styles.css", "dist/wpai-widget.css");

// Il vocabolario, in una forma che sappiano leggere anche Python e PHP.
//
// È l'unico modo onesto di avere una lista sola quando i produttori di opzioni parlano tre
// linguaggi: il backend valida contro questo file, il pannello ci costruisce i menu a tendina, e
// un test confronta ciò che è versionato con ciò che il generatore produce adesso. Riscrivere la
// lista a mano nel backend sarebbe il debito 5 dell'handoff daccapo — con il sintomo peggiore,
// perché un'opzione che il pannello offre e il widget ignora non produce nessun errore.
const { APPEARANCE, CLASS_PREFIX, WITHOUT_ROOT_CLASS, FLAGS, DEFAULT_COLOR } = await import("./src/schema.js");
const schema = {
  _comment: "Generato da sdk/widget/build.mjs a partire da src/schema.js. Non modificare a mano.",
  appearance: APPEARANCE,
  classPrefix: CLASS_PREFIX,
  withoutRootClass: Object.keys(WITHOUT_ROOT_CLASS),
  flags: FLAGS,
  defaultColor: DEFAULT_COLOR,
};
await writeFile("schema.json", JSON.stringify(schema, null, 2) + "\n");

// L'SRI, calcolata qui perché deve descrivere **questo** artefatto e non uno ricostruito dopo.
//
// Il plugin carica una versione fissa con `integrity`: se il file sul CDN cambiasse — per un
// errore di pubblicazione o per una manomissione — il browser rifiuterebbe di eseguirlo invece
// di eseguire qualcosa che non abbiamo scritto noi. Il plugin già pretende SRI da una dipendenza
// di terzi (Font Awesome da cdnjs): il nostro script non può avere uno standard più basso.
const digests = {};
for (const file of ["wpai-widget.js", "wpai-widget.css"]) {
  const bytes = await readFile(`dist/${file}`);
  digests[file] = "sha384-" + createHash("sha384").update(bytes).digest("base64");
}
await writeFile("dist/integrity.json", JSON.stringify({ version, files: digests }, null, 2) + "\n");

const size = Object.values(result.metafile.outputs)[0].bytes;
console.log(`dist/wpai-widget.js — ${(size / 1024).toFixed(1)} kB — versione ${version}`);
for (const [file, digest] of Object.entries(digests)) console.log(`  ${file}  ${digest}`);
