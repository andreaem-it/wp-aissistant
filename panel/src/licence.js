/**
 * Come si legge lo stato della licenza legata al dominio.
 *
 * Sta fuori dal componente perché è la parte che **decide** — quanti slot restano, cosa si può
 * ancora registrare, quale messaggio mostrare — mentre il componente disegna. È lo stesso
 * criterio usato per il widget del plugin: esce ciò che decide, resta ciò che disegna, e ciò
 * che decide si può verificare senza un browser.
 *
 * Le regole vere vivono nel backend (`app/origins.py`) e sono lui ad applicarle: qui si spiega
 * soltanto, e un rifiuto arriva sempre col motivo scritto dal backend, mai riscritto a mano —
 * due formulazioni della stessa regola divergono al primo cambiamento.
 */

export const KIND_LABELS = {
  live: "Produzione",
  staging: "Staging",
  observed: "Visto in uso",
};

export const SOURCE_LABELS = {
  plugin: "Verificato dal plugin WordPress",
  panel: "Aggiunto dal pannello",
  admin: "Impostato dall'assistenza",
  traffic: "Rilevato dal traffico",
};

/** Il messaggio da mostrare quando un'operazione fallisce: quello del backend se c'è. */
export function errorMessage(error, fallback = "Operazione non riuscita. Riprova.") {
  if (error && typeof error.detail === "string" && error.detail.trim()) return error.detail;
  if (error && error.status === 404) return "Dominio non trovato.";
  return fallback;
}

/** Quanti siti di produzione restano, in parole: `null` significa illimitato, non zero. */
export function liveSlotsLabel(slots) {
  if (!slots) return "";
  if (slots.live_limit === 0) return "Domini di produzione: illimitati";
  const available = Math.max(0, slots.live_limit - slots.live_used);
  if (available === 0) {
    return `Domini di produzione: ${slots.live_used} di ${slots.live_limit} (esaurito)`;
  }
  return `Domini di produzione: ${slots.live_used} di ${slots.live_limit}`;
}

/**
 * Che cosa può ancora fare il cliente. Con un solo slot occupato l'aggiunta non è vietata: è un
 * **cambio** del dominio di produzione, e chiamarla "aggiungi" quando sostituisce è il modo di
 * far perdere a qualcuno il proprio sito senza volerlo.
 */
export function liveAction(slots) {
  if (!slots) return { kind: "add", label: "Aggiungi", replaces: false };
  const unlimited = slots.live_limit === 0;
  const free = unlimited || slots.live_used < slots.live_limit;
  if (free) return { kind: "add", label: "Aggiungi", replaces: false };
  if (slots.live_limit === 1) {
    return { kind: "replace", label: "Sostituisci", replaces: true };
  }
  return { kind: "blocked", label: "Aggiungi", replaces: false };
}

export function canAddStaging(slots) {
  return Boolean(slots) && slots.staging_used < slots.staging_limit;
}

/** Il tenant è servibile? Senza domini registrati il widget non parte da nessuna parte. */
export function isCovered(origins) {
  return Array.isArray(origins) && origins.some((o) => o.kind === "live" || o.kind === "staging");
}

/**
 * I domini osservati che vale la pena mostrare: quelli non già registrati. Il backend annota il
 * traffico anche dai domini registrati (per dire "visto l'ultima volta il…"), ma qui servono
 * solo quelli su cui il cliente deve decidere qualcosa.
 */
export function pendingObserved(observed, origins) {
  const known = new Set((origins || []).map((o) => o.host));
  return (observed || []).filter((o) => !known.has(o.host));
}

/** Data leggibile, o stringa vuota: un "Invalid Date" in pagina è peggio di niente. */
export function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit", year: "numeric" });
}
