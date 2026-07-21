const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export function getApiKey() {
  return localStorage.getItem("api_key") || "";
}

export function setApiKey(key) {
  localStorage.setItem("api_key", key);
}

async function call(path, { method = "GET", params = {}, body } = {}) {
  const qs = new URLSearchParams(params).toString();
  const headers = { Authorization: `Bearer ${getApiKey()}` };
  if (!(body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(`${BASE}${path}${qs ? `?${qs}` : ""}`, {
    method,
    headers,
    body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}`);
  return res.json();
}

export const api = {
  conversations: () => call("/conversations"),
  messages: (id) => call(`/conversations/${id}/messages`),
  tickets: (status = "open") => call("/tickets", { params: { status } }),
  replyTicket: (id, reply) => call(`/tickets/${id}/reply`, { method: "POST", params: { reply } }),
  stats: () => call("/stats"),
  uploadDocument: (file) => {
    const form = new FormData();
    form.append("file", file);
    return call("/ingest/document", { method: "POST", body: form });
  },
};
