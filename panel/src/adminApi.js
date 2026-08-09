const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

// sessionStorage (not localStorage): this key grants access to every client, so it
// shouldn't linger on disk past the browser tab closing.
export function getAdminKey() {
  return sessionStorage.getItem("wpai_admin_key") || "";
}

export function setAdminKey(key) {
  sessionStorage.setItem("wpai_admin_key", key);
}

export function clearAdminKey() {
  sessionStorage.removeItem("wpai_admin_key");
}

async function call(path, { method = "GET", body } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { Authorization: `Bearer ${getAdminKey()}`, "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    clearAdminKey();
    window.location.reload();
  }
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}`);
  return res.status === 204 ? null : res.json();
}

export const adminApi = {
  // a throwaway GET just to validate the key against the server
  ping: () => call("/admin/clients"),
  clients: () => call("/admin/clients"),
  createClient: (name, allowed_origins) => call("/admin/clients", { method: "POST", body: { name, allowed_origins } }),
  setOrigins: (id, allowed_origins) => call(`/admin/clients/${id}/origins`, { method: "POST", body: { allowed_origins } }),
  renameClient: (id, name) => call(`/admin/clients/${id}`, { method: "PATCH", body: { name } }),
  // `confirm` è il nome esatto del cliente: il backend rifiuta qualunque altra cosa
  deleteClient: (id, confirm) => call(`/admin/clients/${id}`, { method: "DELETE", body: { confirm } }),
  rotateKey: (id) => call(`/admin/clients/${id}/rotate-key`, { method: "POST" }),
  operators: (id) => call(`/admin/clients/${id}/operators`),
  createOperator: (id, email, password) =>
    call(`/admin/clients/${id}/operators`, { method: "POST", body: { email, password } }),
  deleteOperator: (operatorId) => call(`/admin/operators/${operatorId}`, { method: "DELETE" }),
  reembed: () => call("/admin/reembed", { method: "POST" }),
  plans: () => call("/admin/plans"),
  createPlan: (plan) => call("/admin/plans", { method: "POST", body: plan }),
  setClientPlan: (clientId, plan_id) => call(`/admin/clients/${clientId}/plan`, { method: "POST", body: { plan_id } }),
  // commercial actions: these change the subscription at Stripe; our rows follow via webhook
  extendTrial: (clientId, days) =>
    call(`/admin/clients/${clientId}/subscription/trial`, { method: "POST", body: { days } }),
  applyDiscount: (clientId, coupon) =>
    call(`/admin/clients/${clientId}/subscription/discount`, { method: "POST", body: { coupon } }),
  removeDiscount: (clientId) =>
    call(`/admin/clients/${clientId}/subscription/discount`, { method: "DELETE" }),
  pauseSubscription: (clientId, paused) =>
    call(`/admin/clients/${clientId}/subscription/pause`, { method: "POST", body: { paused } }),
  cancelSubscription: (clientId, cancel) =>
    call(`/admin/clients/${clientId}/subscription/cancel`, { method: "POST", body: { cancel } }),
  // observability (Fase 3b/3c)
  stats: () => call("/admin/stats"),
  revenue: (days = 30) => call(`/admin/revenue?days=${days}`),
  costs: (days = 30) => call(`/admin/costs?days=${days}`),
  activation: (days = 90) => call(`/admin/activation?days=${days}`),
  atRisk: (days = 14) => call(`/admin/at-risk?days=${days}`),
  modelPrices: () => call("/admin/model-prices"),
  setModelPrice: (price) => call("/admin/model-prices", { method: "PUT", body: price }),
  deleteModelPrice: (id) => call(`/admin/model-prices/${id}`, { method: "DELETE" }),
  health: () => call("/admin/health"),
  testEmail: (to) => call("/admin/test-email", { method: "POST", body: { to } }),
  audit: (clientId) => call(`/admin/audit${clientId ? `?client_id=${clientId}` : ""}`),
  problematic: (includeUngrounded) =>
    call(`/admin/problematic${includeUngrounded ? "?include_ungrounded=true" : ""}`),
  conversationDebug: (id) => call(`/admin/conversations/${id}/debug`),
};
