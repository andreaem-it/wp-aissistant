/**
 * Lo snippet da incollare nel proprio sito.
 *
 * Sta fuori dal componente perché è la parte che **decide**: cosa entra nella configurazione,
 * cosa resta fuori, e come si scrive. Il componente disegna. È lo stesso criterio del widget —
 * ciò che decide si può verificare senza un browser.
 *
 * Due scelte che sembrano dettagli e non lo sono:
 *
 * - **Si emette solo ciò che differisce dal default.** Uno snippet con ventiquattro righe di
 *   valori identici ai default è illeggibile, e nasconde le due cose che il cliente ha davvero
 *   cambiato in mezzo a ventidue che non ha toccato.
 * - **`site` c'è sempre, anche se coincide con il dominio registrato.** La licenza è legata al
 *   dominio: senza quel valore il widget non parte e lo dice in console. Ometterlo perché
 *   "tanto si capisce dall'Origin" sposterebbe un errore chiaro in un fallimento muto.
 *
 * **Cosa NON entra più, e perché è la correzione più importante di questo file.**
 *
 * `backendUrl` era un'opzione in chiaro nella pagina di ogni cliente, e il percorso dello script
 * portava il **numero di versione**. Insieme facevano una cosa sola: congelavano nel sito del
 * cliente due decisioni che sono nostre. Per spostare il backend, o per correggere un difetto nel
 * widget, avremmo dovuto chiedere a ogni cliente di ricopiare lo snippet — cioè non avremmo
 * potuto farlo, e il primo difetto serio ce l'avrebbe insegnato con i suoi tempi.
 *
 * Ora l'indirizzo del backend è compilato nell'artefatto e lo script sta su un percorso
 * **stabile** (`/widget/v1/`), che pubblichiamo noi. Il costo è dichiarato: su un percorso che
 * cambia non si può mettere `integrity`, perché un'impronta fissa e un file che si aggiorna sono
 * la stessa cosa detta in due modi opposti. Fra «il cliente verifica il byte» e «possiamo
 * correggere un difetto sul sito del cliente senza chiederglielo», per un servizio ospitato vince
 * la seconda: è il motivo per cui il CDN esiste. Il plugin, che ha una copia locale e un canale
 * di aggiornamento suo, resta sulla versione pinnata con SRI.
 */

const INDENT = "    ";

/**
 * Un valore JavaScript, con le virgolette giuste e niente che possa uscire dalla stringa.
 *
 * `</` va spezzato anche dentro una stringa già virgolettata: il parser HTML chiude il blocco
 * `<script>` al primo `</script>` che incontra, **senza guardare** se sta dentro una stringa
 * JavaScript. Un titolo che contiene quella sequenza spaccherebbe in due lo snippet che il
 * cliente incolla nel proprio sito, e il resto finirebbe nella pagina come testo — o peggio,
 * come markup. `JSON.stringify` da solo non lo copre, perché è una regola dell'HTML e non del
 * JavaScript.
 */
export function literal(value) {
  if (typeof value === "boolean") return String(value);
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return JSON.stringify(String(value ?? ""))
    .replace(/<\//g, "<\\/")
    .replace(/<!--/g, "<\\u0021--");
}

/** Le sole voci che il cliente ha cambiato rispetto al vocabolario. */
export function changed(values, defaults) {
  const out = {};
  for (const [name, value] of Object.entries(values || {})) {
    if (value === undefined || value === null || value === "") continue;
    if (defaults && defaults[name] === value) continue;
    out[name] = value;
  }
  return out;
}

function block(name, values) {
  const entries = Object.entries(values);
  if (!entries.length) return null;
  const inner = entries.map(([key, value]) => `${INDENT}  ${key}: ${literal(value)},`).join("\n");
  return `${INDENT}${name}: {\n${inner}\n${INDENT}},`;
}

/**
 * Lo snippet completo.
 *
 * `defaults` è il vocabolario che arriva dal backend insieme alla configurazione: senza, questa
 * funzione dovrebbe conoscere i default per conto suo, che sarebbe la terza dichiarazione della
 * stessa cosa.
 */
export function buildSnippet({ apiKey, site, cdnUrl, channel, appearance, texts, defaults }) {
  const appearanceDefaults = {};
  for (const [name, spec] of Object.entries(defaults?.appearance || {})) {
    appearanceDefaults[name] = spec.default;
  }
  Object.assign(appearanceDefaults, defaults?.flags || {});
  appearanceDefaults.color = defaults?.defaultColor;

  const lines = [
    `${INDENT}apiKey: ${literal(apiKey)},`,
    `${INDENT}site: ${literal(site)},`,
  ];
  const look = block("appearance", changed(appearance, appearanceDefaults));
  if (look) lines.push(look);
  const copy = block("texts", changed(texts, {}));
  if (copy) lines.push(copy);

  const base = String(cdnUrl || "").replace(/\/$/, "");
  const track = String(channel || "v1");
  const src = `${base}/widget/${track}/wpai-widget.js`;
  const css = `${base}/widget/${track}/wpai-widget.css`;

  return [
    `<link rel="stylesheet" href="${css}">`,
    "<script>",
    "  window.WPAissistantConfig = {",
    ...lines,
    "  };",
    "</script>",
    `<script async src="${src}"></script>`,
  ].join("\n");
}

/**
 * Il dominio da mettere in `site`: quello live registrato, o niente.
 *
 * Niente è meglio di un valore inventato — lo snippet con `site` vuoto non parte e lo dice,
 * mentre uno con un dominio sbagliato parte e riceve un 403 che il cliente non sa spiegarsi.
 */
export function siteFor(origins) {
  const live = (origins || []).find((o) => o.kind === "live");
  return live ? live.origin : "";
}
