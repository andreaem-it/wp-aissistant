const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export function getToken() {
  return localStorage.getItem("operator_token") || "";
}

export function setToken(token) {
  localStorage.setItem("operator_token", token);
}

export function clearToken() {
  localStorage.removeItem("operator_token");
}

export function getEmail() {
  return localStorage.getItem("operator_email") || "";
}

export function setEmail(email) {
  localStorage.setItem("operator_email", email);
}

async function call(path, { method = "GET", params = {}, body, auth = true } = {}) {
  const qs = new URLSearchParams(params).toString();
  const headers = {};
  if (auth) headers.Authorization = `Bearer ${getToken()}`;
  if (!(body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(`${BASE}${path}${qs ? `?${qs}` : ""}`, {
    method,
    headers,
    body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
  });
  // an expired/invalid session drops us back to the login screen
  if (res.status === 401 && auth) {
    clearToken();
    window.location.reload();
  }
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}`);
  return res.json();
}

export const api = {
  login: (email, password) =>
    call("/operator/login", { method: "POST", body: { email, password }, auth: false }),
  publicPlans: () => call("/public/plans", { auth: false }),
  signup: (body) => call("/signup", { method: "POST", body, auth: false }),
  logout: () => call("/operator/logout", { method: "POST" }),
  conversations: () => call("/conversations"),
  messages: (id) => call(`/conversations/${id}/messages`),
  tickets: (status = "open") => call("/tickets", { params: { status } }),
  replyTicket: (id, reply) => call(`/tickets/${id}/reply`, { method: "POST", params: { reply } }),
  stats: () => call("/stats"),
  knowledgeBase: () => call("/knowledge-base"),
  uploadDocument: (file) => {
    const form = new FormData();
    form.append("file", file);
    return call("/ingest/document", { method: "POST", body: form });
  },
  me: () => call("/me"),
  changePassword: (current_password, new_password) =>
    call("/me/password", { method: "POST", body: { current_password, new_password } }),
  rotateKey: () => call("/me/rotate-key", { method: "POST" }),
  plans: () => call("/billing/plans"),
  checkout: (plan_id) => call("/billing/checkout", { method: "POST", body: { plan_id } }),
};
