import { describe, it, expect } from "vitest";
import { buildSnippet, changed, literal, siteFor } from "./snippet.js";

const defaults = {
  appearance: {
    theme: { values: ["light", "dark"], default: "light" },
    position: { values: ["right", "left"], default: "right" },
  },
  flags: { showAvatar: true },
  defaultColor: "#635bff",
};

const base = {
  apiKey: "chiave",
  backendUrl: "https://backend.esempio",
  site: "https://esempio.it",
  cdnUrl: "https://cdn.wpaissistant.it",
  version: "0.1.0",
  defaults,
};

describe("i valori nello snippet", () => {
  it("mette le virgolette e non lascia uscire dalla stringa", () => {
    expect(literal('ciao "mondo"')).toBe('"ciao \\"mondo\\""');
    expect(literal(true)).toBe("true");
    expect(literal(undefined)).toBe('""');
  });

  it("spezza `</script>`, che chiuderebbe il blocco dello snippet", () => {
    // Il parser HTML chiude al primo </script> che incontra, senza guardare se sta dentro una
    // stringa JavaScript: lo snippet incollato dal cliente si spaccherebbe in due.
    const escaped = literal("Assistenza </script><img src=x onerror=alert(1)>");

    expect(escaped).not.toContain("</script>");
    expect(escaped).toContain("<\\/script>");
  });

  it("lo snippet completo non contiene mai una chiusura di script", () => {
    const snippet = buildSnippet({ ...base, texts: { title: "</script><b>x</b>" } });
    const opens = (snippet.match(/<script/g) || []).length;
    const closes = (snippet.match(/<\/script>/g) || []).length;

    expect(closes).toBe(opens);
  });
});

describe("cosa finisce nello snippet", () => {
  it("solo ciò che differisce dal default", () => {
    const result = changed({ theme: "dark", position: "right" }, { theme: "light", position: "right" });

    expect(result).toEqual({ theme: "dark" });
  });

  it("i valori vuoti non entrano", () => {
    expect(changed({ title: "", welcome: "Ciao" }, {})).toEqual({ welcome: "Ciao" });
  });

  it("un booleano cambiato entra anche se è falso", () => {
    // `false` è un valore scelto: trattarlo come vuoto lo perderebbe, e l'avatar tornerebbe.
    expect(changed({ showAvatar: false }, { showAvatar: true })).toEqual({ showAvatar: false });
  });
});

describe("lo snippet", () => {
  it("porta sempre chiave, backend e dominio", () => {
    const snippet = buildSnippet(base);

    expect(snippet).toContain('apiKey: "chiave"');
    expect(snippet).toContain('backendUrl: "https://backend.esempio"');
    expect(snippet).toContain('site: "https://esempio.it"');
  });

  it("punta alla versione fissa del CDN, non a un alias", () => {
    // La versione fissa è il default: un rilascio sbagliato su un alias mobile romperebbe tutti
    // i siti insieme, e il cliente non potrebbe farci niente.
    const snippet = buildSnippet(base);

    expect(snippet).toContain("https://cdn.wpaissistant.it/widget/0.1.0/wpai-widget.js");
    expect(snippet).toContain("https://cdn.wpaissistant.it/widget/0.1.0/wpai-widget.css");
    expect(snippet).not.toContain("/widget/v1/");
  });

  it("non elenca ventiquattro valori identici ai default", () => {
    const snippet = buildSnippet({ ...base, appearance: { theme: "light", position: "right" } });

    expect(snippet).not.toContain("appearance");
  });

  it("elenca solo le opzioni cambiate", () => {
    const snippet = buildSnippet({ ...base, appearance: { theme: "dark", position: "right" } });

    expect(snippet).toContain('theme: "dark"');
    expect(snippet).not.toContain("position:");
  });

  it("include i testi scritti dal cliente", () => {
    const snippet = buildSnippet({ ...base, texts: { title: "Assistenza", welcome: "" } });

    expect(snippet).toContain('title: "Assistenza"');
    expect(snippet).not.toContain("welcome:");
  });

  it("non si rompe se il CDN ha la barra finale", () => {
    const snippet = buildSnippet({ ...base, cdnUrl: "https://cdn.wpaissistant.it/" });

    expect(snippet).toContain("https://cdn.wpaissistant.it/widget/0.1.0/wpai-widget.js");
    expect(snippet).not.toContain("it//widget");
  });
});

describe("il dominio da usare", () => {
  it("è quello live registrato", () => {
    expect(siteFor([
      { kind: "staging", origin: "https://staging.esempio.it" },
      { kind: "live", origin: "https://esempio.it" },
    ])).toBe("https://esempio.it");
  });

  it("è vuoto quando non ce n'è uno, invece di essere inventato", () => {
    // Lo snippet con `site` vuoto non parte e lo dice in console; uno con un dominio sbagliato
    // parte e riceve un 403 che il cliente non sa spiegarsi.
    expect(siteFor([{ kind: "observed", origin: "https://visto.it" }])).toBe("");
    expect(siteFor([])).toBe("");
    expect(siteFor(undefined)).toBe("");
  });
});
