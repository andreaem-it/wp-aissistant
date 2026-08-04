import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { WpAissistantClient } from "../src/index.js";
import { WpAissistantChatElement } from "../src/widget.js";

const root = fileURLToPath(new URL("..", import.meta.url));
const manifest = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
const types = readFileSync(new URL("../src/index.d.ts", import.meta.url), "utf8");

/** Il tarball deve contenere il codice e nulla di più: niente test, niente file di lavoro. */
const PUBLISHED_FILES = [
  "LICENSE",
  "README.md",
  "package.json",
  "src/index.d.ts",
  "src/index.js",
  "src/widget.d.ts",
  "src/widget.js",
];

test("il pacchetto è pubblicabile su npm", () => {
  assert.equal(manifest.private, undefined, "private impedisce npm publish");
  assert.equal(manifest.name, "@wp-aissistant/browser");
  assert.match(manifest.version, /^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/);
  assert.ok(manifest.description && manifest.license && manifest.homepage);
  assert.equal(manifest.publishConfig.access, "public", "un pacchetto scoped resta privato senza access public");
  assert.equal(manifest.publishConfig.provenance, true);
  assert.equal(manifest.repository.directory, "sdk/browser", "npm deve puntare alla sottocartella del monorepo");
  assert.equal(manifest.type, "module");
  assert.equal(manifest.sideEffects, false);
  assert.ok(manifest.engines.node);
});

test("ogni entry point dichiarato esiste davvero", () => {
  const entries = [manifest.main, manifest.module, manifest.types, manifest.unpkg, manifest.jsdelivr];
  for (const value of Object.values(manifest.exports)) {
    if (typeof value === "string") entries.push(value);
    else entries.push(...Object.values(value));
  }
  for (const entry of entries) {
    assert.ok(entry, "entry point vuoto nel manifest");
    assert.ok(existsSync(join(root, entry)), `manca ${entry}`);
  }
  assert.equal(manifest.exports["."].types, manifest.types, "types e exports devono coincidere");
});

test("il tarball contiene esattamente i file previsti", () => {
  const output = execFileSync("npm", ["pack", "--dry-run", "--json"], { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
  const packed = JSON.parse(output)[0].files.map((file) => file.path).sort();
  assert.deepEqual(packed, PUBLISHED_FILES);
});

/** Guardia contro la deriva: un metodo aggiunto al client senza dichiararlo lascerebbe chi
 * integra in TypeScript con un errore di compilazione al posto di una funzione nuova. */
function declarations(source) {
  return (prototype) => {
    for (const name of Object.getOwnPropertyNames(prototype).filter((key) => key !== "constructor")) {
      assert.match(source, new RegExp(`\\b${name}\\s*[(:<]`), `${name} non è dichiarato nei tipi`);
    }
  };
}

test("i tipi restano allineati alle API pubbliche", () => {
  declarations(types)(WpAissistantClient.prototype);
  const widgetTypes = readFileSync(new URL("../src/widget.d.ts", import.meta.url), "utf8");
  declarations(widgetTypes)(WpAissistantChatElement.prototype);
});
