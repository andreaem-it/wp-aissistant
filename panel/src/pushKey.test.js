// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { subscriptionMatchesKey } from "./Profile.jsx";

/**
 * Riconoscere una sottoscrizione fatta con una chiave VAPID precedente.
 *
 * È metà della correzione che rende sopravvivibile una rotazione delle chiavi. L'altra metà sta
 * nel backend, che ora pota le sottoscrizioni rifiutate con `403` invece di aspettare un `410`
 * che non arriva mai.
 *
 * Senza, il fallimento è muto da entrambi i lati: l'operatore preme «attiva», il pannello riusa
 * la sottoscrizione morta, l'interruttore dice «attive» perché una sottoscrizione esiste
 * davvero, e le notifiche non arrivano più. Chi aspetta una notifica che non arriva non ha modo
 * di accorgersene.
 */

// Le chiavi VAPID viaggiano in base64url senza riempimento, come le serve il backend.
const CHIAVE = "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U";
const ALTRA = "BNbxGYNMhEIi9zrneh7mqV4oUanjLUK5bSyN6dLdKgYcMB4gyNS4NmvKGyxJqYbxhpS8rlYSGWRSGxCTA_dRHVs";

function sottoscrizione(chiaveBase64) {
  const raw = atob(chiaveBase64.replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
  return { options: { applicationServerKey: bytes.buffer } };
}

describe("una sottoscrizione push e la chiave del server", () => {
  it("riconosce quella creata con la chiave corrente", () => {
    expect(subscriptionMatchesKey(sottoscrizione(CHIAVE), CHIAVE)).toBe(true);
  });

  it("riconosce quella creata prima di una rotazione", () => {
    expect(subscriptionMatchesKey(sottoscrizione(ALTRA), CHIAVE)).toBe(false);
  });

  it("non si fa ingannare da una chiave di lunghezza diversa", () => {
    const corta = { options: { applicationServerKey: new Uint8Array([1, 2, 3]).buffer } };
    expect(subscriptionMatchesKey(corta, CHIAVE)).toBe(false);
  });

  it("tiene ciò che c'è quando il browser non espone la chiave usata", () => {
    // `options.applicationServerKey` è opzionale: disiscrivere per un campo che il browser non
    // fornisce butterebbe a ogni visita sottoscrizioni perfettamente valide.
    expect(subscriptionMatchesKey({ options: {} }, CHIAVE)).toBe(true);
    expect(subscriptionMatchesKey({}, CHIAVE)).toBe(true);
    expect(subscriptionMatchesKey(null, CHIAVE)).toBe(true);
  });

  it("non decide niente se il server non ha ancora dato la sua chiave", () => {
    expect(subscriptionMatchesKey(sottoscrizione(CHIAVE), "")).toBe(true);
  });
});
