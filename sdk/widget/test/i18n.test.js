/**
 * Test del catalogo testi del widget (node --test, senza DOM né dipendenze).
 *
 * Finora la CI verificava solo la sintassi del JavaScript del plugin: qui c'è la prima logica
 * del widget abbastanza pura da poter essere verificata davvero.
 */
import test from "node:test";
import assert from "node:assert";

import * as i18n from "../src/i18n.js";

test("normalize accetta le varianti di locale e rifiuta le lingue non supportate", () => {
  assert.strictEqual(i18n.normalize("it-IT"), "it");
  assert.strictEqual(i18n.normalize("EN_us"), "en");
  assert.strictEqual(i18n.normalize("  de  "), "de");
  assert.strictEqual(i18n.normalize("ja-JP"), null);
  assert.strictEqual(i18n.normalize(""), null);
  assert.strictEqual(i18n.normalize(undefined), null);
});

test("resolve preferisce il sito, poi il browser, poi il default", () => {
  assert.strictEqual(i18n.resolve("fr-FR", "en-US"), "fr");
  assert.strictEqual(i18n.resolve(null, "es-ES"), "es");
  assert.strictEqual(i18n.resolve("ja-JP", "pt-PT"), "pt");
  assert.strictEqual(i18n.resolve(null, null), "it");
});

test("t traduce e sostituisce i segnaposto", () => {
  assert.strictEqual(i18n.t("chat.send", "en"), "Send");
  assert.strictEqual(i18n.t("rating.stars", "en", { n: 4 }), "4 out of 5");
  assert.strictEqual(i18n.t("cart.added_message", "it", { product: "Scarpe" }), "Scarpe è stato aggiunto al carrello.");
});

test("t non mostra mai una chiave grezza al visitatore", () => {
  // lingua non supportata: ripiega sul default, non sulla chiave
  assert.strictEqual(i18n.t("chat.send", "ja"), i18n.t("chat.send", "it"));
  assert.strictEqual(i18n.t("chat.send", undefined), i18n.t("chat.send", "it"));
});

test("una chiave inesistente resta riconoscibile invece di diventare stringa vuota", () => {
  assert.strictEqual(i18n.t("chiave.inesistente", "it"), "chiave.inesistente");
});

test("ogni stringa esiste in tutte le lingue supportate", () => {
  const mancanti = [];
  for (const [key, entry] of Object.entries(i18n.STRINGS)) {
    for (const lang of i18n.SUPPORTED) {
      if (!entry[lang]) mancanti.push(`${key}/${lang}`);
    }
  }
  assert.deepStrictEqual(mancanti, []);
});

test("i segnaposto sono coerenti fra le traduzioni della stessa chiave", () => {
  const incoerenti = [];
  for (const [key, entry] of Object.entries(i18n.STRINGS)) {
    const atteso = (entry.it.match(/\{\w+\}/g) || []).sort().join(",");
    for (const lang of i18n.SUPPORTED) {
      const trovato = (entry[lang].match(/\{\w+\}/g) || []).sort().join(",");
      if (trovato !== atteso) incoerenti.push(`${key}/${lang}: ${trovato} invece di ${atteso}`);
    }
  }
  assert.deepStrictEqual(incoerenti, []);
});

test("il testo di licenza non spiega al visitatore un problema che non è suo", () => {
  // Il motivo vero — dominio non registrato — va a chi installa, in console. In chat resta un
  // testo neutro: il visitatore non può correggere nulla, e citargli la licenza è sia inutile
  // sia una fuga di dettagli interni verso il browser di un estraneo.
  for (const lang of ["it", "en", "es", "fr", "de", "pt"]) {
    const text = i18n.t("chat.unavailable", lang).toLowerCase();
    assert.ok(text.length > 0, `manca chat.unavailable in ${lang}`);
    for (const leak of ["licen", "dominio", "domain", "origin", "403", "api"]) {
      assert.ok(!text.includes(leak), `chat.unavailable (${lang}) rivela "${leak}": ${text}`);
    }
  }
});

test("il testo di licenza non invita a riprovare: riprovare non cambia nulla", () => {
  const retryWords = { it: "riprova", en: "try again", es: "inténtalo", fr: "réessaye", de: "versuche", pt: "tenta novamente" };
  for (const [lang, word] of Object.entries(retryWords)) {
    const text = i18n.t("chat.unavailable", lang).toLowerCase();
    assert.ok(!text.includes(word), `chat.unavailable (${lang}) invita a riprovare: ${text}`);
    // controprova: è il testo di errore generico a doverlo fare, e continua a farlo
    assert.ok(i18n.t("chat.error", lang).toLowerCase().includes(word),
      `chat.error (${lang}) dovrebbe invitare a riprovare`);
  }
});
