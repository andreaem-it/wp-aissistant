/**
 * Il vocabolario delle opzioni.
 *
 * Ciò che questi test difendono non è la correttezza di una lista, è che la lista esista **una
 * volta sola**. Finché il PHP la genera da qui, un'opzione aggiunta al widget e dimenticata nel
 * plugin non è possibile; senza, il sintomo sarebbe un'opzione che il pannello offre e il widget
 * ignora, senza errori da nessuna parte — il debito 5 dell'handoff, in un'altra forma.
 */
import test from "node:test";
import assert from "node:assert";

import * as schema from "../src/schema.js";

test("un valore fuori vocabolario ricade sul default, non passa", () => {
  assert.equal(schema.option("theme", "arcobaleno"), "light");
  assert.equal(schema.option("position", "sopra"), "right");
  assert.equal(schema.option("launcherIcon", "<script>"), "comment-dots");
});

test("un valore ammesso resta quello scelto", () => {
  assert.equal(schema.option("theme", "dark"), "dark");
  assert.equal(schema.option("windowSize", "large"), "large");
});

test("un'opzione che non esiste non inventa un valore", () => {
  assert.equal(schema.option("inesistente", "x"), undefined);
});

test("il colore accetta solo esadecimali a sei cifre", () => {
  assert.equal(schema.color("#00ff88"), "#00ff88");
  assert.equal(schema.color("#0f8"), schema.DEFAULT_COLOR);
  assert.equal(schema.color("red"), schema.DEFAULT_COLOR);
  // niente che possa uscire dal valore di una proprietà CSS
  assert.equal(schema.color("#000; background: url(x)"), schema.DEFAULT_COLOR);
  assert.equal(schema.color(undefined), schema.DEFAULT_COLOR);
});

test("i booleani distinguono 'non impostato' da 'falso'", () => {
  // `undefined` significa "usa il default", e il default di showAvatar è vero: trattarlo come
  // falso nasconderebbe l'avatar a chi non ha mai toccato l'impostazione.
  assert.equal(schema.flag("showAvatar", undefined), true);
  assert.equal(schema.flag("showAvatar", false), false);
  assert.equal(schema.flag("showStatus", 0), false);
});

test("appearance restituisce sempre l'oggetto completo, anche da un ingresso vuoto", () => {
  const look = schema.appearance({});
  for (const name of Object.keys(schema.APPEARANCE)) {
    assert.ok(look[name] !== undefined, `manca ${name}`);
    assert.ok(schema.APPEARANCE[name].values.includes(look[name]), `${name} fuori vocabolario`);
  }
  assert.equal(look.color, schema.DEFAULT_COLOR);
  assert.equal(look.showAvatar, true);
});

test("appearance normalizza un ingresso ostile senza sollevare", () => {
  const look = schema.appearance({ theme: { toString: () => "dark" }, position: null, color: 42 });
  assert.equal(look.theme, "light");
  assert.equal(look.position, "right");
  assert.equal(look.color, schema.DEFAULT_COLOR);
});

test("le classi della radice coprono ogni opzione con un prefisso", () => {
  const classes = schema.rootClasses(schema.appearance({ theme: "dark", position: "left" }));
  assert.ok(classes.includes("wpai-left"));
  assert.ok(classes.includes("wpai-theme-dark"));
  for (const prefix of Object.values(schema.CLASS_PREFIX)) {
    assert.ok(classes.some((c) => c.startsWith(prefix)), `manca una classe ${prefix}*`);
  }
});

test("ogni opzione con un prefisso di classe esiste nel vocabolario, e viceversa", () => {
  // Un prefisso senza opzione produrrebbe `wpai-theme-undefined` sulla radice; un'opzione senza
  // prefisso sarebbe configurabile e senza alcun effetto — il modo silenzioso di sbagliare.
  for (const name of Object.keys(schema.CLASS_PREFIX)) {
    assert.ok(schema.APPEARANCE[name], `${name} ha un prefisso ma non è nel vocabolario`);
  }
  for (const name of Object.keys(schema.APPEARANCE)) {
    if (schema.WITHOUT_ROOT_CLASS[name]) continue; // dichiarata come eccezione, con il perché
    assert.ok(schema.CLASS_PREFIX[name], `${name} è nel vocabolario ma non produce una classe`);
  }
  for (const name of Object.keys(schema.WITHOUT_ROOT_CLASS)) {
    assert.ok(schema.APPEARANCE[name], `${name} è dichiarata eccezione ma non è un'opzione`);
    assert.ok(!schema.CLASS_PREFIX[name], `${name} è eccezione e ha anche un prefisso`);
  }
});

test("optionNames elenca tutto ciò che un altro produttore deve conoscere", () => {
  const names = schema.optionNames();
  assert.ok(names.includes("theme"));
  assert.ok(names.includes("showAvatar"));
  assert.ok(names.includes("color"));
  assert.equal(new Set(names).size, names.length, "nomi duplicati");
});
