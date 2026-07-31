// Traduzione in italiano delle azioni registrate nell'audit di una conversazione.

export const ACTION_LABELS = {
  "conversation.reply": "Risposta operatore",
  "conversation.routing": "Instradamento aggiornato",
  "conversation.open": "Conversazione riaperta",
  "conversation.closed": "Conversazione chiusa",
  "conversation.delete": "Conversazione eliminata",
  "note.create": "Nota interna aggiunta",
  "note.delete": "Nota interna eliminata",
  "sla.breach": "SLA violato",
  "ticket.reply": "Risposta al ticket",
};

export function actionLabel(action) {
  return ACTION_LABELS[action] || action;
}

/** Data e ora locali abbreviate, es. "31/07, 14:05". */
export function formatMoment(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Chi ha compiuto l'azione: il monitor SLA è di sistema, non un operatore. */
export function actorLabel(entry) {
  if (!entry) return "";
  return entry.actor_type === "system" ? "Sistema" : entry.actor || "—";
}
