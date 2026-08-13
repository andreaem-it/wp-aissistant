// @vitest-environment jsdom
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api.js";

/**
 * L'assistente dentro il pannello.
 *
 * Non è una suite di UI — il markup lo disegna il widget, che ha già la sua. Qui si presidia il
 * contratto fra pannello e widget: che il token venga chiesto, riusato finché è fresco, e che un
 * backend che non lo emette non tolga l'assistenza a chi la sta usando.
 */

// La chiave arriva da `import.meta.env` al momento dell'import del modulo, quindi va messa prima.
vi.stubEnv("VITE_ASSISTANT_API_KEY", "chiave-pubblica-nostra");

const mounted = [];
vi.mock("@wp-aissistant/widget/widget", () => ({
  mount: (config) => {
    mounted.push(config);
    return { destroy: () => {} };
  },
}));
vi.mock("@wp-aissistant/widget/styles.css", () => ({}));

const { default: Assistant } = await import("./Assistant.jsx");

afterEach(() => {
  cleanup();
  mounted.length = 0;
  vi.restoreAllMocks();
});

describe("l'assistente nel pannello", () => {
  it("monta il widget vero con la nostra chiave pubblica", async () => {
    render(<Assistant email="op@acme.it" />);

    await waitFor(() => expect(mounted).toHaveLength(1));
    expect(mounted[0].apiKey).toBe("chiave-pubblica-nostra");
  });

  it("compila l'email dell'operatore per l'escalation", async () => {
    // Chi scrive è già loggato: richiedergli l'email per essere richiamato è una domanda di cui
    // conosciamo già la risposta.
    render(<Assistant email="op@acme.it" />);

    await waitFor(() => expect(mounted).toHaveLength(1));
    expect(mounted[0].contactEmail).toBe("op@acme.it");
  });

  it("manda il token di contesto come header sulle chiamate di chat", async () => {
    vi.spyOn(api, "assistantToken").mockResolvedValue({ token: "tok-1", expires_in: 300 });
    render(<Assistant email="op@acme.it" />);
    await waitFor(() => expect(mounted).toHaveLength(1));

    const headers = await mounted[0].host.chatHeaders();

    expect(headers["X-Panel-Assistant-Token"]).toBe("tok-1");
  });

  it("riusa il token finché è fresco invece di chiederne uno a ogni messaggio", async () => {
    const spy = vi.spyOn(api, "assistantToken")
      .mockResolvedValue({ token: "tok-1", expires_in: 300 });
    render(<Assistant email="op@acme.it" />);
    await waitFor(() => expect(mounted).toHaveLength(1));

    await mounted[0].host.chatHeaders();
    await mounted[0].host.chatHeaders();

    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("non tiene in cache un token più corto del margine di sicurezza", async () => {
    // Il margine esiste perché un token che scade mentre la richiesta è in volo arriva scaduto.
    // Ma se la durata scendesse sotto il margine, tenerlo comunque per un minimo fisso
    // significherebbe conservare un token già morto: esattamente il difetto da cui il margine
    // protegge. Sotto la soglia si preferisce una richiesta per messaggio.
    const spy = vi.spyOn(api, "assistantToken")
      .mockResolvedValue({ token: "tok-1", expires_in: 20 });
    render(<Assistant email="op@acme.it" />);
    await waitFor(() => expect(mounted).toHaveLength(1));

    await mounted[0].host.chatHeaders();
    await mounted[0].host.chatHeaders();

    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("senza token il widget scrive lo stesso, solo senza contesto", async () => {
    // 503 = funzione spenta lato server. Chi sta chiedendo aiuto per un altro problema non deve
    // vedersi negare la chat per un'informazione accessoria.
    const errore = new Error("non configurato");
    errore.status = 503;
    vi.spyOn(api, "assistantToken").mockRejectedValue(errore);
    render(<Assistant email="op@acme.it" />);
    await waitFor(() => expect(mounted).toHaveLength(1));

    await expect(mounted[0].host.chatHeaders()).resolves.toEqual({});
  });
});
