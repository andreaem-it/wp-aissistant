/**
 * Panel colour theme: the same three states the chat widget already offers — chiaro, scuro,
 * automatico — so the product behaves consistently wherever a theme can be chosen.
 *
 * The preference is a browser setting, not account data: it belongs to the device you are
 * looking at, and storing it server-side would fight anyone using two screens.
 */
export const THEMES = ["light", "dark", "auto"];
const STORAGE_KEY = "wpai_panel_theme";
const DEFAULT = "auto";

/** A stored value is only trusted if it is one we know; anything else falls back to auto. */
export function normalize(value) {
  return THEMES.includes(value) ? value : DEFAULT;
}

export function readTheme(storage = globalThis.localStorage) {
  try {
    return normalize(storage?.getItem(STORAGE_KEY));
  } catch {
    // private browsing can make localStorage throw on access, which must not break the panel
    return DEFAULT;
  }
}

export function writeTheme(theme, storage = globalThis.localStorage) {
  const clean = normalize(theme);
  try {
    storage?.setItem(STORAGE_KEY, clean);
  } catch {
    // the theme still applies for this session even when it cannot be remembered
  }
  return clean;
}

/**
 * The theme actually painted: "auto" resolves against the OS preference, everything else is
 * taken literally. Returns "light" or "dark" only — never "auto".
 */
export function resolveTheme(theme, prefersDark = false) {
  const clean = normalize(theme);
  if (clean !== "auto") return clean;
  return prefersDark ? "dark" : "light";
}

/**
 * Stamp the resolved theme on <html>, which is what the CSS keys off. `data-theme` carries the
 * resolved value so the stylesheet never has to re-implement the auto rule.
 */
export function applyTheme(theme, { root = document.documentElement, prefersDark } = {}) {
  const media = typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;
  const dark = prefersDark ?? media?.matches ?? false;
  const resolved = resolveTheme(theme, dark);
  root.setAttribute("data-theme", resolved);
  root.setAttribute("data-theme-preference", normalize(theme));
  return resolved;
}
