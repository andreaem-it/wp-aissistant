/**
 * L'indirizzo del backend: una proprietà dell'artefatto, non una scelta di chi lo installa.
 *
 * Era un'opzione dello snippet, in chiaro nella pagina di ogni cliente. Due cose sbagliate in
 * una:
 *
 * - **Chi copia lo snippet poteva ripuntare il widget dove voleva.** Non è un buco di sicurezza
 *   — la `api_key` è pubblica e il backend autorizza sull'`Origin` — ma è un'opzione che non
 *   significa niente per chi la legge e che possiamo solo sbagliare a documentare.
 * - **Non potevamo cambiare indirizzo.** Un URL copiato dentro migliaia di pagine è un indirizzo
 *   congelato: spostare il backend avrebbe richiesto di chiedere a ogni cliente di ricopiare lo
 *   snippet, cioè non sarebbe stato possibile. Compilato qui, cambia con una versione nuova del
 *   bundle, che è il meccanismo che abbiamo già.
 *
 * Il valore si può cambiare **in fase di build** (`WPAI_BACKEND_URL=… npm run build`), che è
 * come lo cambiamo noi per lo sviluppo. A runtime no: vedi `DEV` più sotto.
 */

// I due valori arrivano dalla build (esbuild `define`). Il `typeof` regge entrambi i mondi: nel
// bundle è già stato sostituito con una costante, mentre chi importa i **sorgenti** — il
// pannello con Vite, i test con Node — non ha nessuna define e cade sul ramo di sviluppo.
/* global __WPAI_BACKEND_URL__, __WPAI_DEV__ */

/** L'indirizzo di produzione. Sostituito dalla build quando `WPAI_BACKEND_URL` è impostata. */
export const BACKEND_URL = typeof __WPAI_BACKEND_URL__ !== "undefined"
  ? __WPAI_BACKEND_URL__
  : "https://backend.wpaissistant.it";

/**
 * Se questo bundle accetta un `backendUrl` dalla configurazione.
 *
 * Falso nell'artefatto pubblicato, vero nelle build di sviluppo e quando il widget è importato
 * dai sorgenti — cioè dal pannello e dai test, che devono poter parlare con un backend locale.
 * È un interruttore di build e non un'opzione: chi installa il widget non lo può toccare, che è
 * esattamente la proprietà richiesta.
 */
export const DEV = typeof __WPAI_DEV__ !== "undefined" ? __WPAI_DEV__ : true;

/** L'indirizzo da usare davvero, data la configurazione ricevuta. */
export function backendUrl(config) {
  const asked = config && config.backendUrl ? String(config.backendUrl) : "";
  return DEV && asked ? asked.replace(/\/$/, "") : BACKEND_URL;
}
