import test from "node:test";
import assert from "node:assert";

import * as RULES from "../src/rules.js";

// A fixed instant, so "adesso" means the same thing on every machine and in CI.
// 2026-03-04 is a Wednesday; 14:30 UTC is 15:30 in Rome (winter time).
const WED_1430_UTC = new Date("2026-03-04T14:30:00Z");
const WEEKDAYS = [1, 2, 3, 4, 5];

test("supporto disattivato: sempre raggiungibile", () => {
  assert.equal(RULES.supportAvailable({ enabled: false }, WED_1430_UTC), true);
  assert.equal(RULES.supportAvailable(undefined, WED_1430_UTC), true);
});

test("dentro e fuori l'orario di lavoro", () => {
  const support = {
    enabled: true, timezone: "Europe/Rome", start: "09:00", end: "18:00", days: WEEKDAYS,
  };
  assert.equal(RULES.supportAvailable(support, WED_1430_UTC), true);
  // 21:30 a Roma: chiuso
  assert.equal(RULES.supportAvailable(support, new Date("2026-03-04T20:30:00Z")), false);
});

test("un giorno non lavorativo è chiuso anche in orario", () => {
  const support = {
    enabled: true, timezone: "Europe/Rome", start: "09:00", end: "18:00", days: WEEKDAYS,
  };
  // 2026-03-08 è una domenica
  assert.equal(RULES.supportAvailable(support, new Date("2026-03-08T14:30:00Z")), false);
});

test("il fuso conta: stesso istante, esiti diversi", () => {
  const base = { enabled: true, start: "09:00", end: "18:00", days: WEEKDAYS };
  const instant = new Date("2026-03-04T20:30:00Z"); // 21:30 Roma, 15:30 New York
  assert.equal(RULES.supportAvailable({ ...base, timezone: "Europe/Rome" }, instant), false);
  assert.equal(RULES.supportAvailable({ ...base, timezone: "America/New_York" }, instant), true);
});

test("l'ora legale non sposta l'orario dichiarato", () => {
  const support = {
    enabled: true, timezone: "Europe/Rome", start: "09:00", end: "18:00", days: WEEKDAYS,
  };
  // 08:30 UTC = 09:30 a Roma d'inverno e 10:30 d'estate: aperto in entrambi i casi,
  // perché l'orario è espresso nel fuso del tenant, non in UTC
  assert.equal(RULES.supportAvailable(support, new Date("2026-01-07T08:30:00Z")), true);
  assert.equal(RULES.supportAvailable(support, new Date("2026-07-08T08:30:00Z")), true);
  // 07:30 UTC è 08:30 d'inverno (chiuso) ma 09:30 d'estate (aperto)
  assert.equal(RULES.supportAvailable(support, new Date("2026-01-07T07:30:00Z")), false);
  assert.equal(RULES.supportAvailable(support, new Date("2026-07-08T07:30:00Z")), true);
});

test("orario a cavallo della mezzanotte appartiene al giorno in cui inizia", () => {
  // turno notturno del mercoledì: 22:00 -> 02:00
  const support = {
    enabled: true, timezone: "Europe/Rome", start: "22:00", end: "02:00", days: [3],
  };
  // mercoledì 23:00 Roma: aperto
  assert.equal(RULES.supportAvailable(support, new Date("2026-03-04T22:00:00Z")), true);
  // giovedì 01:00 Roma: ancora il turno del mercoledì
  assert.equal(RULES.supportAvailable(support, new Date("2026-03-05T00:00:00Z")), true);
  // giovedì 03:00 Roma: finito
  assert.equal(RULES.supportAvailable(support, new Date("2026-03-05T02:00:00Z")), false);
});

test("una configurazione illeggibile non nasconde l'operatore", () => {
  const support = { enabled: true, timezone: "Non/Esiste", start: "09:00", end: "18:00", days: WEEKDAYS };
  assert.equal(RULES.supportAvailable(support, WED_1430_UTC), true);
});

// ---- Messaggi proattivi ------------------------------------------------------------------

test("il pattern URL restringe le pagine", () => {
  const rule = { url_pattern: "/checkout" };
  assert.equal(RULES.proactiveMatches(rule, "https://sito.it/checkout/step-2", 0), true);
  assert.equal(RULES.proactiveMatches(rule, "https://sito.it/blog", 0), false);
  // senza pattern la regola vale ovunque
  assert.equal(RULES.proactiveMatches({}, "https://sito.it/blog", 0), true);
});

test("il trigger carrello richiede un carrello non vuoto", () => {
  const rule = { trigger_type: "cart" };
  assert.equal(RULES.proactiveMatches(rule, "https://sito.it", 2), true);
  assert.equal(RULES.proactiveMatches(rule, "https://sito.it", 0), false);
});

test("l'opt-out del visitatore batte qualsiasi frequenza", () => {
  for (const frequency of ["always", "once_per_session", "once_per_day"]) {
    assert.equal(RULES.proactiveAllowed({ frequency }, { optedOut: true }), false);
  }
});

test("once_per_session guarda la sessione, once_per_day le 24 ore", () => {
  const now = Date.now();
  assert.equal(RULES.proactiveAllowed({ frequency: "once_per_session" }, { seenThisSession: true, now }), false);
  assert.equal(RULES.proactiveAllowed({ frequency: "once_per_session" }, { seenThisSession: false, now }), true);

  const yesterday = now - RULES.DAY_MS - 1000;
  assert.equal(RULES.proactiveAllowed({ frequency: "once_per_day" }, { lastShownAt: yesterday, now }), true);
  assert.equal(RULES.proactiveAllowed({ frequency: "once_per_day" }, { lastShownAt: now - 1000, now }), false);
  // mai mostrata: si può mostrare
  assert.equal(RULES.proactiveAllowed({ frequency: "once_per_day" }, { now }), true);
});

test("always ignora quanto è già stata vista", () => {
  const now = Date.now();
  assert.equal(
    RULES.proactiveAllowed({ frequency: "always" }, { seenThisSession: true, lastShownAt: now, now }),
    true,
  );
});

test("senza messaggio B non c'è esperimento", () => {
  assert.equal(RULES.proactiveVariant({ id: 1 }, undefined, 0.9), "a");
});

test("l'assegnazione della variante è stabile", () => {
  const rule = { id: 1, message_b: "ciao" };
  // già assegnata: il sorteggio non viene nemmeno consultato
  assert.equal(RULES.proactiveVariant(rule, "b", 0.1), "b");
  assert.equal(RULES.proactiveVariant(rule, "a", 0.9), "a");
});

test("la prima assegnazione divide a metà", () => {
  const rule = { id: 1, message_b: "ciao" };
  assert.equal(RULES.proactiveVariant(rule, undefined, 0.49), "a");
  assert.equal(RULES.proactiveVariant(rule, undefined, 0.5), "b");
  // un valore memorizzato non valido viene riassegnato invece di essere restituito
  assert.equal(RULES.proactiveVariant(rule, "z", 0.9), "b");
});
