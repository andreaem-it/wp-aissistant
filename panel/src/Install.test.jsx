// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api.js";
import Install from "./Install.jsx";

const VOCABULARY = {
  appearance: {
    theme: { values: ["light", "dark", "auto"], default: "light" },
    position: { values: ["right", "left"], default: "right" },
  },
  flags: { showAvatar: true },
  defaultColor: "#635bff",
  textLimits: { title: 80, welcome: 500 },
};

const CONFIG = {
  config: {
    appearance: { theme: "light", position: "right", showAvatar: true, color: "#635bff" },
    texts: { title: "", welcome: "" },
  },
  vocabulary: VOCABULARY,
  configured: false,
  updated_at: null,
};

function stub({ origins = [{ id: 1, kind: "live", origin: "https://esempio.it", host: "esempio.it" }] } = {}) {
  vi.spyOn(api, "widgetConfig").mockResolvedValue(structuredClone(CONFIG));
  vi.spyOn(api, "me").mockResolvedValue({ api_key: "chiave-pubblica", client_name: "Acme" });
  vi.spyOn(api, "origins").mockResolvedValue({ origins, observed: [], slots: {} });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("la schermata di installazione", () => {
  it("propone le due strade come scelta esplicita", async () => {
    stub();
    render(<Install />);

    const choices = await screen.findAllByRole("radio");
    expect(choices.map((c) => c.textContent)).toEqual([
      expect.stringContaining("Plugin WordPress"),
      expect.stringContaining("Integrazione JavaScript"),
    ]);
    expect(choices[0].getAttribute("aria-checked")).toBe("true");
  });

  it("parte da WordPress e mostra la chiave da incollare", async () => {
    stub();
    render(<Install />);

    const field = await screen.findByLabelText("Chiave pubblica");
    expect(field.value).toBe("chiave-pubblica");
  });

  it("avverte quando non c'è un dominio di produzione", async () => {
    // Senza, il widget non parte da nessuna parte: dirlo qui evita che lo scopra dal silenzio.
    stub({ origins: [] });
    render(<Install />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/non parte da nessuna parte/);
  });

  it("mostra lo snippet con chiave e dominio quando si sceglie JavaScript", async () => {
    stub();
    render(<Install />);
    fireEvent.click((await screen.findAllByRole("radio"))[1]);

    const snippet = await screen.findByLabelText("Snippet");
    expect(snippet.value).toContain('apiKey: "chiave-pubblica"');
    expect(snippet.value).toContain('site: "https://esempio.it"');
    expect(snippet.value).toContain("/widget/");
  });

  it("i controlli dell'aspetto vengono dal vocabolario del backend", async () => {
    // Non da una lista riscritta nel frontend: sarebbe la terza copia della stessa cosa, e
    // divergerebbe al primo valore aggiunto al widget.
    stub();
    render(<Install />);
    fireEvent.click((await screen.findAllByRole("radio"))[1]);

    const theme = await screen.findByLabelText("Tema");
    expect([...theme.options].map((o) => o.value)).toEqual(["light", "dark", "auto"]);
  });

  it("cambiare un'opzione la fa comparire nello snippet", async () => {
    stub();
    render(<Install />);
    fireEvent.click((await screen.findAllByRole("radio"))[1]);
    fireEvent.change(await screen.findByLabelText("Tema"), { target: { value: "dark" } });

    await waitFor(() => {
      expect(screen.getByLabelText("Snippet").value).toContain('theme: "dark"');
    });
  });

  it("l'anteprima monta il widget vero e non chiama il backend", async () => {
    // Un'anteprima che apre conversazioni sporcherebbe l'inbox e le statistiche del cliente a
    // ogni sguardo alla pagina.
    const calls = [];
    globalThis.fetch = async (url) => {
      calls.push(String(url));
      return { ok: true, status: 200, clone() { return this; }, json: async () => ({}), body: null };
    };
    stub();
    render(<Install />);
    fireEvent.click((await screen.findAllByRole("radio"))[1]);

    await waitFor(() => {
      expect(document.getElementById("wpai-root")).toBeTruthy();
    });
    expect(document.getElementById("wpai-input").disabled).toBe(true);
    expect(calls.filter((u) => u.includes("/chat"))).toEqual([]);
  });

  it("non fallisce in silenzio se il caricamento va male", async () => {
    vi.spyOn(api, "widgetConfig").mockRejectedValue(Object.assign(new Error("500"), { status: 500 }));
    vi.spyOn(api, "me").mockResolvedValue({});
    vi.spyOn(api, "origins").mockResolvedValue({ origins: [] });
    render(<Install />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/Non è stato possibile caricare/);
  });

  it("mostra il motivo del backend quando il salvataggio è rifiutato", async () => {
    stub();
    vi.spyOn(api, "saveWidgetConfig").mockRejectedValue(Object.assign(new Error("400"), {
      status: 400,
      detail: "«arcobaleno» non è un valore ammesso per theme",
    }));
    render(<Install />);
    fireEvent.click((await screen.findAllByRole("radio"))[1]);
    fireEvent.click(await screen.findByRole("button", { name: "Salva" }));

    await waitFor(() => {
      expect(screen.getByText(/non è un valore ammesso/)).toBeTruthy();
    });
  });
});
