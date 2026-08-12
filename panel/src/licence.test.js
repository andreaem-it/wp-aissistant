import { describe, it, expect } from "vitest";
import {
  canAddStaging, errorMessage, formatDate, isCovered, liveAction, liveSlotsLabel, pendingObserved,
} from "./licence.js";

describe("il messaggio di errore", () => {
  it("preferisce il motivo scritto dal backend", () => {
    const error = Object.assign(new Error("POST /account/origins -> 400"), {
      status: 400,
      detail: "Il dominio di staging deve essere un sottodominio di esempio.it",
    });

    expect(errorMessage(error)).toContain("sottodominio di esempio.it");
  });

  it("non lascia trapelare l'URL della chiamata quando il backend non spiega", () => {
    const error = Object.assign(new Error("POST /account/origins -> 500"), { status: 500 });

    const message = errorMessage(error);
    expect(message).not.toContain("/account/origins");
    expect(message).toBe("Operazione non riuscita. Riprova.");
  });

  it("ignora un detail vuoto invece di mostrare una riga bianca", () => {
    const error = Object.assign(new Error("x"), { status: 400, detail: "   " });

    expect(errorMessage(error)).toBe("Operazione non riuscita. Riprova.");
  });
});

describe("gli slot di produzione", () => {
  it("dice illimitati quando il limite è zero, non 'zero disponibili'", () => {
    expect(liveSlotsLabel({ live_limit: 0, live_used: 3 })).toContain("illimitati");
  });

  it("segnala quando sono esauriti", () => {
    expect(liveSlotsLabel({ live_limit: 1, live_used: 1 })).toContain("esaurito");
  });

  it("non va sottozero se i dati sono incoerenti", () => {
    expect(liveSlotsLabel({ live_limit: 1, live_used: 5 })).toContain("esaurito");
  });
});

describe("l'azione sul dominio di produzione", () => {
  it("con uno slot libero è un'aggiunta", () => {
    expect(liveAction({ live_limit: 1, live_used: 0 })).toMatchObject({ kind: "add", replaces: false });
  });

  it("con un solo slot occupato è una sostituzione, e va detto", () => {
    // Chiamarla "aggiungi" quando toglie il widget dal sito precedente è il modo di far
    // perdere a qualcuno il proprio sito senza volerlo.
    const action = liveAction({ live_limit: 1, live_used: 1 });

    expect(action.replaces).toBe(true);
    expect(action.label).toBe("Sostituisci");
  });

  it("con più slot tutti occupati è bloccata: non si sostituisce a caso", () => {
    expect(liveAction({ live_limit: 3, live_used: 3 })).toMatchObject({ kind: "blocked" });
  });

  it("senza slot illimitati resta un'aggiunta", () => {
    expect(liveAction({ live_limit: 0, live_used: 9 })).toMatchObject({ kind: "add" });
  });
});

describe("lo slot di staging", () => {
  it("è disponibile finché non è usato", () => {
    expect(canAddStaging({ staging_used: 0, staging_limit: 1 })).toBe(true);
    expect(canAddStaging({ staging_used: 1, staging_limit: 1 })).toBe(false);
  });
});

describe("la copertura", () => {
  it("un dominio osservato non copre nulla", () => {
    expect(isCovered([{ kind: "observed", host: "a.it" }])).toBe(false);
  });

  it("un dominio live copre", () => {
    expect(isCovered([{ kind: "live", host: "a.it" }])).toBe(true);
  });

  it("anche il solo staging copre: è un dominio registrato", () => {
    expect(isCovered([{ kind: "staging", host: "dev.a.it" }])).toBe(true);
  });

  it("senza domini non copre", () => {
    expect(isCovered([])).toBe(false);
    expect(isCovered(undefined)).toBe(false);
  });
});

describe("i domini osservati da mostrare", () => {
  it("esclude quelli già registrati", () => {
    const observed = [{ host: "a.it" }, { host: "b.it" }];
    const origins = [{ host: "a.it", kind: "live" }];

    expect(pendingObserved(observed, origins).map((o) => o.host)).toEqual(["b.it"]);
  });

  it("regge liste mancanti", () => {
    expect(pendingObserved(undefined, undefined)).toEqual([]);
  });
});

describe("le date", () => {
  it("non stampa mai 'Invalid Date'", () => {
    expect(formatDate("non-una-data")).toBe("");
    expect(formatDate(null)).toBe("");
  });

  it("formatta all'italiana", () => {
    expect(formatDate("2026-08-12T10:00:00Z")).toBe("12/08/2026");
  });
});
