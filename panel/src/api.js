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

async function download(path) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (res.status === 401) {
    clearToken();
    window.location.reload();
  }
  if (!res.ok) {
    const err = new Error(`GET ${path} -> ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.blob();
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
  pushConfig: () => call("/push/config"),
  savePushSubscription: (body) => call("/push/subscriptions", { method: "POST", body }),
  updatePushPreferences: (preferences) => call("/push/preferences", { method: "PATCH", body: { preferences } }),
  deletePushSubscription: (endpoint) => call("/push/subscriptions", { method: "DELETE", body: { endpoint } }),
  conversations: (params = {}) => call("/conversations", { params }),
  messages: (id) => call(`/conversations/${id}/messages`),
  uploadAttachment: (id, file) => {
    const body = new FormData();
    body.append("file", file);
    return call(`/conversations/${id}/attachments`, { method: "POST", body });
  },
  downloadAttachment: (id) => download(`/attachments/${id}`),
  deleteAttachment: (id) => call(`/attachments/${id}`, { method: "DELETE" }),
  tickets: (status = "open") => call("/tickets", { params: { status } }),
  replyTicket: (id, reply) => call(`/tickets/${id}/reply`, { method: "POST", params: { reply } }),
  helpdeskConnections: () => call("/helpdesk/connections"),
  setHelpdeskConnection: (provider, body) => call(`/helpdesk/connections/${provider}`, { method: "PUT", body }),
  deleteHelpdeskConnection: (provider) => call(`/helpdesk/connections/${provider}`, { method: "DELETE" }),
  exportTicketToHelpdesk: (id, provider) =>
    call(`/tickets/${id}/helpdesk-export`, { method: "POST", body: { provider } }),
  replyConversation: (id, reply) => call(`/conversations/${id}/reply`, { method: "POST", body: { reply } }),
  whatsappStatus: (id) => call(`/conversations/${id}/whatsapp/status`),
  sendWhatsappTemplate: (id, body) => call(`/conversations/${id}/whatsapp/template`, { method: "POST", body }),
  setConversationStatus: (id, status) => call(`/conversations/${id}/status`, { method: "POST", body: { status } }),
  setConversationRouting: (id, body) => call(`/conversations/${id}/routing`, { method: "PATCH", body }),
  deleteConversation: (id) => call(`/conversations/${id}`, { method: "DELETE" }),
  gdprExport: (email) => call("/gdpr/export", { method: "POST", body: { email } }),
  gdprErase: (email) => call("/gdpr/erase", { method: "POST", body: { email } }),
  teamOperators: () => call("/team/operators"),
  departments: () => call("/departments"),
  createDepartment: (name) => call("/departments", { method: "POST", body: { name } }),
  deleteDepartment: (id) => call(`/departments/${id}`, { method: "DELETE" }),
  departmentMembers: (id) => call(`/departments/${id}/members`),
  addDepartmentMember: (id, operator_id) =>
    call(`/departments/${id}/members`, { method: "POST", body: { operator_id } }),
  removeDepartmentMember: (id, operatorId) =>
    call(`/departments/${id}/members/${operatorId}`, { method: "DELETE" }),
  slaPolicies: () => call("/sla-policies"),
  createSlaPolicy: (body) => call("/sla-policies", { method: "POST", body }),
  updateSlaPolicy: (id, body) => call(`/sla-policies/${id}`, { method: "PATCH", body }),
  deleteSlaPolicy: (id) => call(`/sla-policies/${id}`, { method: "DELETE" }),
  supportSchedule: () => call("/support-schedule"),
  setSupportSchedule: (body) => call("/support-schedule", { method: "PUT", body }),
  tags: () => call("/tags"),
  createTag: (name, color = "") => call("/tags", { method: "POST", body: { name, color } }),
  deleteTag: (id) => call(`/tags/${id}`, { method: "DELETE" }),
  tagConversation: (id, body) => call(`/conversations/${id}/tags`, { method: "POST", body }),
  untagConversation: (id, tagId) => call(`/conversations/${id}/tags/${tagId}`, { method: "DELETE" }),
  classifyConversation: (id) => call(`/conversations/${id}/classify`, { method: "POST" }),
  notes: (id) => call(`/conversations/${id}/notes`),
  createNote: (id, body, mentions = []) =>
    call(`/conversations/${id}/notes`, { method: "POST", body: { body, mentions } }),
  deleteNote: (id, noteId) => call(`/conversations/${id}/notes/${noteId}`, { method: "DELETE" }),
  mentions: (unread_only = true) => call("/mentions", { params: { unread_only } }),
  markMentionsRead: (mention_ids = []) => call("/mentions/read", { method: "POST", body: { mention_ids } }),
  presence: (id, composing = false) =>
    call(`/conversations/${id}/presence`, { method: "POST", body: { composing } }),
  conversationActivity: (id) => call(`/conversations/${id}/activity`),
  savedViews: () => call("/saved-views"),
  createSavedView: (body) => call("/saved-views", { method: "POST", body }),
  updateSavedView: (id, body) => call(`/saved-views/${id}`, { method: "PATCH", body }),
  deleteSavedView: (id) => call(`/saved-views/${id}`, { method: "DELETE" }),
  routingSettings: () => call("/routing-settings"),
  setRoutingSettings: (mode, fallback_department_id = null) =>
    call("/routing-settings", { method: "PUT", body: { mode, fallback_department_id } }),
  conversationInfo: (id) => call(`/conversations/${id}/info`),
  setConversationInfo: (id, info) => call(`/conversations/${id}/info`, { method: "PUT", body: { info } }),
  cannedResponses: () => call("/canned-responses"),
  createCanned: (title, body) => call("/canned-responses", { method: "POST", body: { title, body } }),
  deleteCanned: (id) => call(`/canned-responses/${id}`, { method: "DELETE" }),
  infoFields: () => call("/info-fields"),
  createInfoField: (label) => call("/info-fields", { method: "POST", body: { label } }),
  deleteInfoField: (id) => call(`/info-fields/${id}`, { method: "DELETE" }),
  leadForms: () => call("/lead-forms"),
  createLeadForm: (body) => call("/lead-forms", { method: "POST", body }),
  updateLeadForm: (id, body) => call(`/lead-forms/${id}`, { method: "PATCH", body }),
  deleteLeadForm: (id) => call(`/lead-forms/${id}`, { method: "DELETE" }),
  leads: (params = {}) => call("/leads", { params }),
  crmConnections: () => call("/crm/connections"),
  connectBrevo: (api_key) => call("/crm/connect/brevo", { method: "POST", body: { api_key } }),
  setCrmConnection: (provider, body) => call(`/crm/connections/${provider}`, { method: "PUT", body }),
  deleteCrmConnection: (provider) => call(`/crm/connections/${provider}`, { method: "DELETE" }),
  syncLeadToCrm: (id, provider) => call(`/leads/${id}/crm-sync`, { method: "POST", body: { provider } }),
  proactiveRules: () => call("/proactive-rules"),
  createProactiveRule: (body) => call("/proactive-rules", { method: "POST", body }),
  updateProactiveRule: (id, body) => call(`/proactive-rules/${id}`, { method: "PATCH", body }),
  finishProactiveExperiment: (id, action) =>
    call(`/proactive-rules/${id}/experiment`, { method: "POST", body: { action } }),
  deleteProactiveRule: (id) => call(`/proactive-rules/${id}`, { method: "DELETE" }),
  workflows: () => call("/workflows"),
  createWorkflow: (body) => call("/workflows", { method: "POST", body }),
  updateWorkflow: (id, body) => call(`/workflows/${id}`, { method: "PATCH", body }),
  deleteWorkflow: (id) => call(`/workflows/${id}`, { method: "DELETE" }),
  workflowRuns: (id) => call(`/workflows/${id}/runs`),
  workflowScheduled: (id) => call(`/workflows/${id}/scheduled`),
  previewWorkflow: (id, conversation_id) =>
    call(`/workflows/${id}/preview`, { method: "POST", body: { conversation_id } }),
  apiKeys: () => call("/api-keys"),
  createApiKey: (name, scopes) => call("/api-keys", { method: "POST", body: { name, scopes } }),
  revokeApiKey: (id) => call(`/api-keys/${id}`, { method: "DELETE" }),
  webhooks: () => call("/webhooks"),
  createWebhook: (url, events, description = "") =>
    call("/webhooks", { method: "POST", body: { url, events, description } }),
  updateWebhook: (id, body) => call(`/webhooks/${id}`, { method: "PATCH", body }),
  deleteWebhook: (id) => call(`/webhooks/${id}`, { method: "DELETE" }),
  testWebhook: (id) => call(`/webhooks/${id}/test`, { method: "POST" }),
  webhookDeliveries: (id, params = {}) => call(`/webhooks/${id}/deliveries`, { params }),
  webhookStats: (id, days = 30) => call(`/webhooks/${id}/stats`, { params: { days } }),
  replayWebhookDelivery: (endpointId, deliveryId) =>
    call(`/webhooks/${endpointId}/deliveries/${deliveryId}/replay`, { method: "POST" }),
  stats: () => call("/stats"),
  csat: (days = 30) => call("/csat", { params: { days } }),
  analyticsOverview: (days = 30) => call("/analytics/overview", { params: { days } }),
  knowledgeGaps: (days = 30) => call("/analytics/knowledge-gaps", { params: { days } }),
  reviewKnowledgeGap: (question, status, questions = []) =>
    call("/analytics/knowledge-gaps/review", { method: "POST", body: { question, status, questions } }),
  knowledgeDrafts: () => call("/analytics/knowledge-drafts"),
  createKnowledgeDraft: (question, questions = []) =>
    call("/analytics/knowledge-gaps/draft", { method: "POST", body: { question, questions } }),
  publishKnowledgeDraft: (id, title, content) =>
    call(`/analytics/knowledge-drafts/${id}/publish`, { method: "POST", body: { title, content } }),
  knowledgeBase: () => call("/knowledge-base"),
  uploadDocument: (file) => {
    const form = new FormData();
    form.append("file", file);
    return call("/ingest/document", { method: "POST", body: form });
  },
  teachKnowledge: (title, content) => call("/knowledge/teach", { method: "POST", body: { title, content } }),
  me: () => call("/me"),
  onboardingStatus: () => call("/onboarding/status"),
  setName: (name) => call("/me/name", { method: "POST", body: { name } }),
  typing: (id) => call(`/conversations/${id}/typing`, { method: "POST" }),
  changePassword: (current_password, new_password) =>
    call("/me/password", { method: "POST", body: { current_password, new_password } }),
  rotateKey: () => call("/me/rotate-key", { method: "POST" }),
  usage: () => call("/usage"),
  plans: () => call("/billing/plans"),
  checkout: (plan_id, billing_interval = "month") =>
    call("/billing/checkout", { method: "POST", body: { plan_id, billing_interval } }),
};
