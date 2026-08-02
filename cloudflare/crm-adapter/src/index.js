import { contactFields, hubspotUpsert, pipedrivePerson, tenantProvider } from "./protocol.js";

const encoder = new TextEncoder();

export function sameString(left, right) {
  const a = encoder.encode(left || "");
  const b = encoder.encode(right || "");
  let mismatch = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) mismatch |= (a[i] || 0) ^ (b[i] || 0);
  return mismatch === 0;
}

async function providerJson(url, token, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = {}; }
  if (!response.ok) {
    console.error(JSON.stringify({ event: "crm.provider_error", status: response.status }));
    throw new Error(`CRM provider returned ${response.status}`);
  }
  return data;
}

async function syncHubSpot(config, fields, env) {
  const version = env.HUBSPOT_API_VERSION || "2026-03";
  const result = await providerJson(`https://api.hubapi.com/crm/objects/${version}/contacts/batch/upsert`, config.access_token, {
    method: "POST", body: JSON.stringify(hubspotUpsert(fields)),
  });
  return String(result.results?.[0]?.id || "");
}

async function syncPipedrive(config, fields) {
  const base = String(config.api_url || "https://api.pipedrive.com").replace(/\/$/, "");
  if (!/^https:\/\/[A-Za-z0-9.-]+$/.test(base)) throw new Error("Invalid Pipedrive API URL");
  const search = await providerJson(
    `${base}/api/v2/persons/search?term=${encodeURIComponent(fields.email)}&fields=email&exact_match=true&limit=1`,
    config.access_token,
  );
  const existingId = search.data?.items?.[0]?.item?.id || search.data?.items?.[0]?.id;
  const result = await providerJson(`${base}/api/v2/persons${existingId ? `/${existingId}` : ""}`, config.access_token, {
    method: existingId ? "PATCH" : "POST", body: JSON.stringify(pipedrivePerson(fields)),
  });
  return String(result.data?.id || existingId || "");
}

async function sync(request, env) {
  if (!sameString(request.headers.get("authorization"), `Bearer ${env.ADAPTER_TOKEN}`)) {
    return new Response("Unauthorized", { status: 401 });
  }
  let payload;
  try { payload = await request.json(); } catch { return new Response("Invalid JSON", { status: 400 }); }
  if (!["hubspot", "pipedrive"].includes(payload.provider)) return new Response("Unsupported provider", { status: 400 });
  const config = tenantProvider(
    env.CRM_TENANTS_JSON, payload.client_id, payload.provider, payload.external_account_id,
  );
  if (!config) return new Response("Tenant CRM account not configured", { status: 404 });
  let fields;
  try { fields = contactFields(payload.lead); } catch (error) { return new Response(error.message, { status: 422 }); }
  try {
    const externalId = payload.provider === "hubspot"
      ? await syncHubSpot(config, fields, env)
      : await syncPipedrive(config, fields);
    if (!externalId) throw new Error("Provider response omitted contact id");
    return Response.json({ ok: true, external_id: externalId });
  } catch (error) {
    console.error(JSON.stringify({ event: "crm.sync_failed", provider: payload.provider, client_id: payload.client_id }));
    return Response.json({ ok: false, error: "CRM provider unavailable" }, { status: 502 });
  }
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (path === "/sync" && request.method === "POST") return sync(request, env);
    if (path === "/health" && request.method === "GET") return Response.json({ ok: true });
    return new Response("Not found", { status: 404 });
  },
};
