// Presentazione degli SLA nell'inbox. Il backend invia stato e scadenze già calcolati
// (date ISO in UTC, con la Z finale): qui si traducono in etichette italiane.

export const SLA_STATE_LABELS = {
  ok: "SLA rispettato",
  in_scadenza: "In scadenza",
  violato: "SLA violato",
};

export const SLA_STATE_CLASS = {
  ok: "ok",
  in_scadenza: "warn",
  violato: "breach",
};

export function formatDuration(minutes) {
  const total = Math.max(0, Math.round(minutes));
  if (total < 60) return `${total} min`;
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  if (hours < 24) return rest ? `${hours} h ${rest} min` : `${hours} h`;
  const days = Math.floor(hours / 24);
  const restHours = hours % 24;
  return restHours ? `${days} g ${restHours} h` : `${days} g`;
}

/** Testo di una singola scadenza SLA, es. "Prima risposta entro 12 min". */
export function describeTarget(label, target, now = Date.now()) {
  if (!target || !target.due_at) return null;
  const due = new Date(target.due_at).getTime();
  if (target.met_at) {
    const met = new Date(target.met_at).getTime();
    const late = (met - due) / 60000;
    return late > 0
      ? `${label}: in ritardo di ${formatDuration(late)}`
      : `${label}: nei tempi`;
  }
  const remaining = (due - now) / 60000;
  return remaining >= 0
    ? `${label}: entro ${formatDuration(remaining)}`
    : `${label}: scaduta da ${formatDuration(-remaining)}`;
}

/** Righe descrittive per le due scadenze di una conversazione. */
export function describeSla(sla, now = Date.now()) {
  if (!sla) return [];
  return [
    describeTarget("Prima risposta", sla.first_response, now),
    describeTarget("Risoluzione", sla.resolution, now),
  ].filter(Boolean);
}
