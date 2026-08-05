// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { applyTheme, normalize, readTheme, resolveTheme, writeTheme } from "./theme.js";

function fakeStorage(initial = {}) {
  const data = { ...initial };
  return {
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
    data,
  };
}

const throwingStorage = {
  getItem() { throw new Error("denied"); },
  setItem() { throw new Error("denied"); },
};

describe("normalize", () => {
  it("accepts the known themes", () => {
    expect(normalize("light")).toBe("light");
    expect(normalize("dark")).toBe("dark");
    expect(normalize("auto")).toBe("auto");
  });

  it("falls back to auto for anything else", () => {
    // a stale or tampered value must not leave the panel in an unpainted state
    expect(normalize("solarized")).toBe("auto");
    expect(normalize(null)).toBe("auto");
    expect(normalize(undefined)).toBe("auto");
  });
});

describe("readTheme / writeTheme", () => {
  it("round-trips a stored preference", () => {
    const storage = fakeStorage();
    writeTheme("dark", storage);
    expect(readTheme(storage)).toBe("dark");
  });

  it("defaults to auto when nothing is stored", () => {
    expect(readTheme(fakeStorage())).toBe("auto");
  });

  it("survives a storage that throws", () => {
    // private browsing can deny localStorage; the panel must still render
    expect(readTheme(throwingStorage)).toBe("auto");
    expect(() => writeTheme("dark", throwingStorage)).not.toThrow();
    expect(writeTheme("dark", throwingStorage)).toBe("dark");
  });
});

describe("resolveTheme", () => {
  it("takes an explicit choice literally, whatever the system says", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  it("follows the system only on auto", () => {
    expect(resolveTheme("auto", true)).toBe("dark");
    expect(resolveTheme("auto", false)).toBe("light");
  });

  it("never returns auto", () => {
    expect(["light", "dark"]).toContain(resolveTheme("auto", true));
    expect(["light", "dark"]).toContain(resolveTheme("bogus", false));
  });
});

describe("applyTheme", () => {
  it("stamps the resolved theme and the raw preference", () => {
    const root = document.createElement("html");

    expect(applyTheme("auto", { root, prefersDark: true })).toBe("dark");
    // the stylesheet reads the resolved value; the toggle reads the preference
    expect(root.getAttribute("data-theme")).toBe("dark");
    expect(root.getAttribute("data-theme-preference")).toBe("auto");
  });

  it("keeps an explicit preference visible after resolution", () => {
    const root = document.createElement("html");

    applyTheme("light", { root, prefersDark: true });

    expect(root.getAttribute("data-theme")).toBe("light");
    expect(root.getAttribute("data-theme-preference")).toBe("light");
  });
});
