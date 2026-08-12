/**
 * Punto d'ingresso del bundle: `window.WPAissistant`.
 *
 * Due modi di partire, e il secondo è quello che useranno quasi tutti:
 *
 * ```html
 * <script>window.WPAissistantConfig = { apiKey: "…", backendUrl: "…", site: "https://esempio.it" };</script>
 * <script async src="…/wpai-widget.js"></script>
 * ```
 *
 * oppure, quando la configurazione arriva più tardi (un pannello che monta l'anteprima):
 *
 * ```js
 * window.WPAissistant.init({ apiKey: "…", backendUrl: "…", site: "https://esempio.it" });
 * ```
 *
 * `site` è **obbligatorio**: la licenza è legata al dominio e il backend rifiuta una chiamata
 * da un sito non registrato. Dichiararlo qui serve a fallire subito e in chiaro — "manca il
 * dominio" scritto in console — invece di un 403 remoto che al visitatore appare come un widget
 * che non c'è. Non è quel valore ad autorizzare: l'autorizzazione la fa il backend sull'header
 * Origin, che la pagina non può falsificare.
 */
import { mount } from "./widget.js";
import * as schema from "./schema.js";

let mounted = null;

function warn(message) {
  // Chi installa legge la console; il visitatore non deve vedere nulla di tutto questo.
  console.error("[WP AIssistant] " + message);
}

export function init(config) {
  const cfg = config || {};
  if (mounted) return mounted; // due <script> nella stessa pagina non devono dare due widget

  if (!cfg.apiKey) {
    warn("manca apiKey: copia la chiave dal pannello, in Impostazioni → Siti e licenza.");
    return null;
  }
  if (!cfg.backendUrl) {
    warn("manca backendUrl.");
    return null;
  }
  if (!cfg.site) {
    warn(
      "manca `site`: indica il dominio su cui gira il widget, per esempio https://esempio.it. "
      + "La licenza è legata al dominio e senza questo valore l'assistente non parte."
    );
    return null;
  }

  const host = { siteUrl: cfg.site, ...(cfg.host || {}) };
  const start = () => {
    mounted = mount({ ...cfg, host });
    return mounted;
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
    return null;
  }
  return start();
}

const api = { init, schema };

if (typeof window !== "undefined") {
  window.WPAissistant = api;
  // Boot automatico se la configurazione è già lì. L'adapter della piattaforma ospite si
  // aggancia a `window.WPAissistantConfig.host` prima di questo script, che è il motivo per cui
  // il plugin WordPress carica il proprio file adapter per primo.
  if (window.WPAissistantConfig) init(window.WPAissistantConfig);
}

export default api;
