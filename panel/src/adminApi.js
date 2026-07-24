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
  rotateKey: (id) => call(`/admin/clients/${id}/rotate-key`, { method: "POST" }),
  operators: (id) => call(`/admin/clients/${id}/operators`),
  createOperator: (id, email, password) =>
    call(`/admin/clients/${id}/operators`, { method: "POST", body: { email, password } }),
  deleteOperator: (operatorId) => call(`/admin/operators/${operatorId}`, { method: "DELETE" }),
  reembed: () => call("/admin/reembed", { method: "POST" }),
};
