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
export function buildSnippet({ apiKey, backendUrl, site, cdnUrl, version, appearance, texts, defaults }) {
  const appearanceDefaults = {};
  for (const [name, spec] of Object.entries(defaults?.appearance || {})) {
    appearanceDefaults[name] = spec.default;
  }
  Object.assign(appearanceDefaults, defaults?.flags || {});
  appearanceDefaults.color = defaults?.defaultColor;

  const lines = [
    `${INDENT}apiKey: ${literal(apiKey)},`,
    `${INDENT}backendUrl: ${literal(backendUrl)},`,
    `${INDENT}site: ${literal(site)},`,
  ];
  const look = block("appearance", changed(appearance, appearanceDefaults));
  if (look) lines.push(look);
  const copy = block("texts", changed(texts, {}));
  if (copy) lines.push(copy);

  const src = `${String(cdnUrl || "").replace(/\/$/, "")}/widget/${version}/wpai-widget.js`;
  const css = `${String(cdnUrl || "").replace(/\/$/, "")}/widget/${version}/wpai-widget.css`;

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
