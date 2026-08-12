/**
 * Build del bundle.
 *
 * Produce un IIFE senza dipendenze, non un modulo: il widget viene incluso con un `<script>` in
 * pagine che non hanno un bundler, ed è il caso che deve funzionare senza chiedere niente a
 * nessuno. La convenzione «nessun bundler» del plugin resta vera dov'è importante — a runtime,
 * sul sito del cliente — e cade solo qui, in fase di build, dove abbiamo Node.
 */
import { build } from "esbuild";
import { copyFile, mkdir } from "node:fs/promises";

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

const size = Object.values(result.metafile.outputs)[0].bytes;
console.log(`dist/wpai-widget.js — ${(size / 1024).toFixed(1)} kB`);
