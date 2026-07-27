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
  if (!res.ok) {
    // preserve the HTTP status so callers can branch (e.g. 403 = email not verified)
    const err = new Error(`${method} ${path} -> ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const api = {
  login: (email, password) =>
    call("/operator/login", { method: "POST", body: { email, password }, auth: false }),
  publicPlans: () => call("/public/plans", { auth: false }),
  signup: (body) => call("/signup", { method: "POST", body, auth: false }),
  forgotPassword: (email) => call("/auth/forgot", { method: "POST", body: { email }, auth: false }),
  resetPassword: (token, new_password) =>
    call("/auth/reset", { method: "POST", body: { token, new_password }, auth: false }),
  verifyEmail: (token) => call("/auth/verify-email", { method: "POST", body: { token }, auth: false }),
  resendVerification: (email) =>
    call("/auth/resend-verification", { method: "POST", body: { email }, auth: false }),
  logout: () => call("/operator/logout", { method: "POST" }),
  conversations: () => call("/conversations"),
  messages: (id) => call(`/conversations/${id}/messages`),
  tickets: (status = "open") => call("/tickets", { params: { status } }),
  replyTicket: (id, reply) => call(`/tickets/${id}/reply`, { method: "POST", params: { reply } }),
  replyConversation: (id, reply) => call(`/conversations/${id}/reply`, { method: "POST", body: { reply } }),
  setConversationStatus: (id, status) => call(`/conversations/${id}/status`, { method: "POST", body: { status } }),
  conversationInfo: (id) => call(`/conversations/${id}/info`),
  setConversationInfo: (id, info) => call(`/conversations/${id}/info`, { method: "PUT", body: { info } }),
  cannedResponses: () => call("/canned-responses"),
  createCanned: (title, body) => call("/canned-responses", { method: "POST", body: { title, body } }),
  deleteCanned: (id) => call(`/canned-responses/${id}`, { method: "DELETE" }),
  infoFields: () => call("/info-fields"),
  createInfoField: (label) => call("/info-fields", { method: "POST", body: { label } }),
  deleteInfoField: (id) => call(`/info-fields/${id}`, { method: "DELETE" }),
  stats: () => call("/stats"),
  knowledgeBase: () => call("/knowledge-base"),
  uploadDocument: (file) => {
    const form = new FormData();
    form.append("file", file);
    return call("/ingest/document", { method: "POST", body: form });
  },
  teachKnowledge: (title, content) => call("/knowledge/teach", { method: "POST", body: { title, content } }),
  me: () => call("/me"),
  setName: (name) => call("/me/name", { method: "POST", body: { name } }),
  typing: (id) => call(`/conversations/${id}/typing`, { method: "POST" }),
  changePassword: (current_password, new_password) =>
    call("/me/password", { method: "POST", body: { current_password, new_password } }),
  rotateKey: () => call("/me/rotate-key", { method: "POST" }),
  usage: () => call("/usage"),
  plans: () => call("/billing/plans"),
  checkout: (plan_id) => call("/billing/checkout", { method: "POST", body: { plan_id } }),
};
