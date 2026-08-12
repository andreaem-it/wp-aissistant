/**
 * Build del bundle.
 *
 * Produce un IIFE senza dipendenze, non un modulo: il widget viene incluso con un `<script>` in
 * pagine che non hanno un bundler, ed è il caso che deve funzionare senza chiedere niente a
 * nessuno. La convenzione «nessun bundler» del plugin resta vera dov'è importante — a runtime,
 * sul sito del cliente — e cade solo qui, in fase di build, dove abbiamo Node.
 */
import { build } from "esbuild";
import { copyFile, mkdir, writeFile } from "node:fs/promises";

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

const size = Object.values(result.metafile.outputs)[0].bytes;
console.log(`dist/wpai-widget.js — ${(size / 1024).toFixed(1)} kB`);
