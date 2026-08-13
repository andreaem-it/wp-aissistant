/**
 * Le icone del widget, disegnate qui dentro.
 *
 * Prima erano `<i class="fa-solid fa-…">`, cioè una dipendenza da Font Awesome **caricata dalla
 * pagina ospite**. Il plugin WordPress la accodava da un CDN di terzi e tutto sembrava a posto;
 * l'installazione JavaScript no, e il risultato era un pulsante d'invio vuoto e un launcher
 * senza simbolo. Un bundle che si dichiara «senza dipendenze» ne aveva una, non dichiarata, su
 * un dominio che non controlliamo — e il difetto si vedeva solo dove la dipendenza mancava.
 *
 * Tre ragioni per disegnarle invece che accodare il CSS di Font Awesome anche da qui:
 *
 * - **Nessuna richiesta a terzi.** È una promessa che facciamo già altrove nella roadmap, e un
 *   font di icone da un CDN esterno la romperebbe su ogni sito dei clienti.
 * - **Nessuna CSP da spiegare.** Un `<link>` verso un dominio esterno è la prima cosa che una
 *   Content-Security-Policy stretta blocca, e il sintomo sarebbe di nuovo «icone invisibili».
 * - **Nessun problema di licenza.** Questi tracciati sono nostri: geometrie semplici su una
 *   griglia 24×24, non i glifi di qualcun altro copiati dentro il nostro pacchetto.
 *
 * Sono tratti (`stroke`) e non riempimenti, con `currentColor`: ereditano colore e dimensione da
 * chi le contiene, che è esattamente ciò che faceva il font.
 */

const STROKE = 'fill="none" stroke="currentColor" stroke-width="2" '
  + 'stroke-linecap="round" stroke-linejoin="round"';

/** I tracciati. Chiave = nome dell'icona, valore = il contenuto dell'`<svg>`. */
const PATHS = {
  "arrow-up": `<path ${STROKE} d="M12 19V5M5 12l7-7 7 7"/>`,
  xmark: `<path ${STROKE} d="M18 6 6 18M6 6l12 12"/>`,
  check: `<path ${STROKE} d="m20 6-11 11-5-5"/>`,
  clock: `<circle ${STROKE} cx="12" cy="12" r="9"/><path ${STROKE} d="M12 7v5l3 2"/>`,
  // La bolla con i tre punti: è anche l'icona predefinita del launcher.
  "comment-dots": `<path ${STROKE} d="M20 12a8 8 0 0 1-8 8H7.5L3 22.5V18a8 8 0 1 1 17-6Z"/>`
    + `<circle cx="8.5" cy="12" r="1" fill="currentColor"/>`
    + `<circle cx="12" cy="12" r="1" fill="currentColor"/>`
    + `<circle cx="15.5" cy="12" r="1" fill="currentColor"/>`,
  comments: `<path ${STROKE} d="M17 11a6 6 0 0 1-6 6H8l-4 3v-4.2A6 6 0 0 1 8 5h3a6 6 0 0 1 6 6Z"/>`
    + `<path ${STROKE} d="M15.5 8h1.5a4 4 0 0 1 4 4v6.5L18.5 17"/>`,
  sparkles: `<path ${STROKE} d="M12 3.5 13.8 9 19 10.8 13.8 12.6 12 18l-1.8-5.4L5 10.8 10.2 9Z"/>`
    + `<path ${STROKE} d="M18.5 3.5v3M20 5h-3"/>`,
  headset: `<path ${STROKE} d="M4 14v-1a8 8 0 1 1 16 0v1"/>`
    + `<path ${STROKE} d="M4 14h2v6H5.5A1.5 1.5 0 0 1 4 18.5Z"/>`
    + `<path ${STROKE} d="M20 14h-2v6h.5a1.5 1.5 0 0 0 1.5-1.5Z"/>`,
  star: `<path fill="currentColor" d="m12 3.6 2.6 5.4 5.9.9-4.3 4.1 1 5.9-5.2-2.8-5.2 2.8 1-5.9L3.5 9.9l5.9-.9Z"/>`,
  "star-outline": `<path ${STROKE} d="m12 3.6 2.6 5.4 5.9.9-4.3 4.1 1 5.9-5.2-2.8-5.2 2.8 1-5.9L3.5 9.9l5.9-.9Z"/>`,
  "thumbs-up": `<path ${STROKE} d="M7 20V10l4.5-7A2.5 2.5 0 0 1 14 6v3h4.6a2 2 0 0 1 2 2.4l-1.3 6.5a2 2 0 0 1-2 1.6Z"/>`
    + `<path ${STROKE} d="M7 10H4v10h3"/>`,
  "thumbs-down": `<path ${STROKE} d="M7 4v10l4.5 7A2.5 2.5 0 0 0 14 18v-3h4.6a2 2 0 0 0 2-2.4l-1.3-6.5a2 2 0 0 0-2-1.6Z"/>`
    + `<path ${STROKE} d="M7 14H4V4h3"/>`,
};

/** I nomi disponibili, per chi vuole verificare che il vocabolario e le icone non divergano. */
export function names() {
  return Object.keys(PATHS);
}

/**
 * Il markup di un'icona, o stringa vuota per un nome sconosciuto.
 *
 * Vuota e non un segnaposto: un nome sbagliato deve lasciare un buco silenzioso, non un simbolo
 * inventato che sembra una scelta. `aria-hidden` perché accanto c'è sempre un testo o una
 * `aria-label` — un'icona annunciata due volte è peggio di una non annunciata.
 */
export function iconMarkup(name) {
  const paths = PATHS[name];
  if (!paths) return "";
  return `<svg class="wpai-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${paths}</svg>`;
}

/** L'icona come elemento, per chi costruisce il DOM invece di comporre stringhe. */
export function icon(name) {
  const holder = document.createElement("span");
  holder.className = "wpai-icon-slot";
  holder.innerHTML = iconMarkup(name);
  return holder;
}
