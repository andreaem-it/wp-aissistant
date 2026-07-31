// Conversione tra lo stato dei filtri dell'inbox (stringhe delle <select>) e il formato
// accettato dal backend, usato sia per le query sia per le viste salvate.

export const EMPTY_FILTERS = {
  status: "",
  priority: "",
  assignment: "", // "" | "unassigned" | id operatore
  department_id: "",
  sla_state: "",
  tag_id: "",
  intent: "",
  urgency: "",
  sort: "recent",
};

export const INTENT_LABELS = {
  informazione: "Informazione",
  acquisto: "Acquisto",
  ordine: "Ordine",
  reso: "Reso",
  reclamo: "Reclamo",
  assistenza_tecnica: "Assistenza tecnica",
  altro: "Altro",
};

export const URGENCY_LABELS = { bassa: "Bassa", media: "Media", alta: "Alta" };

/** Filtri nel formato salvato/accettato dal backend (senza l'ordinamento). */
export function toApiFilters(filters) {
  const out = {};
  if (filters.status) out.status = filters.status;
  if (filters.priority) out.priority = filters.priority;
  if (filters.department_id) out.department_id = Number(filters.department_id);
  if (filters.sla_state) out.sla_state = filters.sla_state;
  if (filters.tag_id) out.tag_id = Number(filters.tag_id);
  if (filters.intent) out.intent = filters.intent;
  if (filters.urgency) out.urgency = filters.urgency;
  if (filters.assignment === "unassigned") out.unassigned = true;
  else if (filters.assignment) out.assigned_operator_id = Number(filters.assignment);
  return out;
}

/** Query string di /conversations: filtri + ordinamento. */
export function toQueryParams(filters) {
  return { ...toApiFilters(filters), sort: filters.sort || "recent" };
}

/** Stato dei filtri a partire da una vista salvata. */
export function fromApiFilters(saved, sort) {
  const source = saved || {};
  return {
    ...EMPTY_FILTERS,
    status: source.status || "",
    priority: source.priority || "",
    department_id: source.department_id ? String(source.department_id) : "",
    sla_state: source.sla_state || "",
    tag_id: source.tag_id ? String(source.tag_id) : "",
    intent: source.intent || "",
    urgency: source.urgency || "",
    assignment: source.unassigned
      ? "unassigned"
      : source.assigned_operator_id
        ? String(source.assigned_operator_id)
        : "",
    sort: sort || "recent",
  };
}

export function hasActiveFilters(filters) {
  return Object.keys(toApiFilters(filters)).length > 0;
}

/** True quando i filtri correnti corrispondono alla vista salvata (per evidenziarla). */
export function matchesView(filters, view) {
  if (!view) return false;
  const current = JSON.stringify(toApiFilters(filters), Object.keys(EMPTY_FILTERS).sort());
  const saved = JSON.stringify(view.filters || {}, Object.keys(EMPTY_FILTERS).sort());
  return current === saved && (filters.sort || "recent") === (view.sort || "recent");
}
