/**
 * Il vocabolario delle opzioni del widget: **una dichiarazione sola**.
 *
 * Finora questa lista è esistita due volte — dentro `wpai_sanitize_settings` (PHP) e sparsa nei
 * controlli `.includes(...)` che il widget faceva mentre costruiva il DOM — e la fase 3 della
 * roadmap ne aggiungerà una terza lato pannello. Tre copie scritte a mano della stessa cosa
 * sono il debito 5 dell'handoff daccapo: le intestazioni CORS annunciavano `GET, POST, OPTIONS`
 * mentre l'app instradava 36 rotte PUT/PATCH/DELETE, e il sintomo era che quelle rotte non
 * funzionavano dal browser senza un errore da nessuna parte.
 *
 * Qui la lista è dato, non codice: si può leggere per generare la whitelist PHP e i controlli
 * del configuratore, e un test confronta le copie generate con questa. Aggiungere uno stile del
 * pulsante deve restare una riga in un posto solo.
 *
 * Cosa NON sta qui: i testi del cliente (benvenuto, sottotitolo, disclosure) e le chiavi. Il
 * primo è contenuto libero, le seconde non sono aspetto.
 */

/** Opzioni di aspetto: valori ammessi e default. L'ordine è quello in cui appaiono nel pannello. */
export const APPEARANCE = {
  theme: { values: ["light", "dark", "auto"], default: "light" },
  position: { values: ["right", "left"], default: "right" },
  motion: { values: ["subtle", "playful", "none"], default: "subtle" },
  launcherStyle: { values: ["bubble", "pill", "square", "outline"], default: "bubble" },
  launcherIcon: { values: ["comment-dots", "comments", "sparkles", "headset"], default: "comment-dots" },
  launcherSize: { values: ["small", "standard", "large"], default: "standard" },
  windowStyle: { values: ["soft", "flat", "glass", "compact"], default: "soft" },
  windowSize: { values: ["compact", "standard", "large"], default: "standard" },
  headerStyle: { values: ["tint", "solid", "minimal"], default: "tint" },
  cornerStyle: { values: ["soft", "rounded", "square"], default: "soft" },
  fontSize: { values: ["small", "standard", "large"], default: "standard" },
};

/** Le classi CSS che ogni opzione produce sulla radice. Il prefisso è parte del contratto. */
export const CLASS_PREFIX = {
  theme: "wpai-theme-",
  motion: "wpai-motion-",
  launcherStyle: "wpai-launcher-",
  launcherSize: "wpai-launcher-size-",
  windowStyle: "wpai-window-",
  windowSize: "wpai-size-",
  headerStyle: "wpai-header-",
  cornerStyle: "wpai-corners-",
  fontSize: "wpai-font-",
};

/**
 * Le opzioni che **non** diventano una classe sulla radice, e come si usano invece.
 *
 * Sta scritto qui perché è l'unica differenza fra le opzioni, e senza dichiararla resterebbe
 * folklore: chi aggiunge un'opzione dimenticando il prefisso otterrebbe un'impostazione
 * configurabile e senza alcun effetto, che è il modo silenzioso di sbagliare. Il test
 * `schema.test.js` obbliga a scegliere una delle due strade per ogni opzione nuova.
 */
export const WITHOUT_ROOT_CLASS = {
  position: "due classi dedicate, wpai-left / wpai-right",
  launcherIcon: "il nome dell'icona sull'elemento del pulsante (fa-solid fa-…)",
};

/** Opzioni booleane, con il loro default. */
export const FLAGS = {
  showAvatar: true,
  showStatus: true,
};

export const DEFAULT_COLOR = "#635bff";

const HEX_COLOR = /^#[0-9a-f]{6}$/i;

/** Un colore accettabile, o quello predefinito: un valore non valido non deve finire nel CSS. */
export function color(value) {
  return HEX_COLOR.test(String(value || "")) ? String(value) : DEFAULT_COLOR;
}

/** Il valore di un'opzione se è nel vocabolario, altrimenti il default. Mai un valore inventato. */
export function option(name, value) {
  const spec = APPEARANCE[name];
  if (!spec) return undefined;
  return spec.values.includes(value) ? value : spec.default;
}

/** Un booleano, trattando `undefined` come "usa il default" e non come falso. */
export function flag(name, value) {
  if (value === undefined || value === null) return FLAGS[name];
  return Boolean(value);
}

/**
 * L'aspetto normalizzato: ogni opzione presente, ogni valore dentro il vocabolario.
 *
 * Restituisce sempre l'oggetto completo, anche quando l'ingresso è vuoto, così chi disegna non
 * deve avere un default a sua volta — un secondo default è un secondo posto dove sbagliare.
 */
export function appearance(input) {
  const source = input || {};
  const out = {};
  for (const name of Object.keys(APPEARANCE)) out[name] = option(name, source[name]);
  for (const name of Object.keys(FLAGS)) out[name] = flag(name, source[name]);
  out.color = color(source.color);
  return out;
}

/** Le classi CSS della radice per un aspetto già normalizzato. */
export function rootClasses(normalised) {
  const classes = [normalised.position === "left" ? "wpai-left" : "wpai-right"];
  for (const [name, prefix] of Object.entries(CLASS_PREFIX)) {
    classes.push(prefix + normalised[name]);
  }
  return classes;
}

/** Elenco piatto dei nomi, per chi genera una whitelist altrove (PHP, pannello). */
export function optionNames() {
  return [...Object.keys(APPEARANCE), ...Object.keys(FLAGS), "color"];
}
