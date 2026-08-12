// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api.js";
import Sites from "./Sites.jsx";

function payload(overrides = {}) {
  return {
    origins: [{
      id: 1, origin: "https://acme.it", host: "acme.it", kind: "live", source: "plugin",
      first_seen_at: "2026-08-01T10:00:00Z", last_seen_at: "2026-08-11T10:00:00Z",
      confirmed_at: "2026-08-01T10:00:00Z",
    }],
    observed: [],
    slots: { live_used: 1, live_limit: 1, live_available: 0, staging_used: 0, staging_limit: 1 },
    staging_labels: ["dev", "staging"],
    ...overrides,
  };
}

afterEach(() => {
  // Il cleanup automatico c'è solo con `globals: true`: senza, il DOM di un test resta montato
  // nel successivo e le query trovano due pulsanti dove ne dovrebbe esserci uno.
  cleanup();
  vi.restoreAllMocks();
});

describe("la schermata dei siti", () => {
  it("mostra il dominio registrato e da dove viene", async () => {
    vi.spyOn(api, "origins").mockResolvedValue(payload());

    render(<Sites />);

    expect(await screen.findByText("acme.it")).toBeTruthy();
    expect(screen.getByText(/Verificato dal plugin WordPress/)).toBeTruthy();
  });

  it("avverte quando non c'è nessun dominio: è il caso in cui il widget non parte", async () => {
    vi.spyOn(api, "origins").mockResolvedValue(payload({
      origins: [],
      slots: { live_used: 0, live_limit: 1, live_available: 1, staging_used: 0, staging_limit: 1 },
    }));

    render(<Sites />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/il widget\s+non parte/i);
  });

  it("con lo slot pieno il pulsante dice 'Sostituisci', non 'Aggiungi'", async () => {
    vi.spyOn(api, "origins").mockResolvedValue(payload());

    render(<Sites />);

    expect(await screen.findByRole("button", { name: /Sostituisci/ })).toBeTruthy();
  });

  it("mostra il motivo del backend quando la registrazione è rifiutata", async () => {
    vi.spyOn(api, "origins").mockResolvedValue(payload({
      origins: [],
      slots: { live_used: 0, live_limit: 1, live_available: 1, staging_used: 0, staging_limit: 1 },
    }));
    vi.spyOn(api, "addOrigin").mockRejectedValue(Object.assign(new Error("400"), {
      status: 400,
      detail: "Il dominio di staging deve essere un sottodominio di acme.it",
    }));

    render(<Sites />);
    const input = await screen.findByLabelText("Dominio da registrare");
    fireEvent.change(input, { target: { value: "https://demo.altrosito.it" } });
    fireEvent.click(screen.getByRole("button", { name: "Aggiungi" }));

    await waitFor(() => {
      expect(screen.getByText(/sottodominio di acme.it/)).toBeTruthy();
    });
  });

  it("elenca i domini visti in uso e non ancora registrati", async () => {
    vi.spyOn(api, "origins").mockResolvedValue(payload({
      observed: [{
        id: 9, origin: "https://nuovo.it", host: "nuovo.it", kind: "observed", source: "traffic",
        first_seen_at: "2026-08-10T10:00:00Z", last_seen_at: "2026-08-11T09:00:00Z",
        confirmed_at: null,
      }],
    }));

    render(<Sites />);

    expect(await screen.findByText("nuovo.it")).toBeTruthy();
  });

  it("non fallisce in silenzio se il caricamento va male", async () => {
    vi.spyOn(api, "origins").mockRejectedValue(Object.assign(new Error("500"), { status: 500 }));

    render(<Sites />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/Non è stato possibile caricare/);
    expect(screen.getByRole("button", { name: "Riprova" })).toBeTruthy();
  });
});
