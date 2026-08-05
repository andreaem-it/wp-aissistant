import { useCallback, useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

import { applyTheme, readTheme, writeTheme } from "./theme.js";

const OPTIONS = [
  { value: "light", label: "Chiaro", Icon: Sun },
  { value: "dark", label: "Scuro", Icon: Moon },
  { value: "auto", label: "Automatico", Icon: Monitor },
];

/**
 * Three-state theme control, shared by the operator panel and the superadmin so the two
 * sidebars behave identically. Mirrors the chat widget's chiaro/scuro/auto choice.
 */
export default function ThemeToggle() {
  const [theme, setTheme] = useState(readTheme);

  useEffect(() => { applyTheme(theme); }, [theme]);

  // on "automatico" the OS can change under us (sunset, a system setting): follow it live
  // rather than only at page load
  useEffect(() => {
    if (theme !== "auto" || !window.matchMedia) return undefined;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const sync = () => applyTheme("auto");
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, [theme]);

  const choose = useCallback((value) => setTheme(writeTheme(value)), []);

  return (
    <div className="wpai-theme-toggle" role="radiogroup" aria-label="Tema del pannello">
      {OPTIONS.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={theme === value}
          className={"wpai-theme-option" + (theme === value ? " active" : "")}
          onClick={() => choose(value)}
          title={label}
        >
          <Icon size={14} strokeWidth={2.25} aria-hidden="true" />
          <span className="wpai-sr-only">{label}</span>
        </button>
      ))}
    </div>
  );
}
