import { collectAttachments, skippedNote } from "./media.js";
import { graphPayload, normalizeEvent, platformOf, sendingId, tenantConfig, tenantFromEntry } from "./protocol.js";

const encoder = new TextEncoder();

function sameString(left, right) {
  const a = encoder.encode(left || "");
  const b = encoder.encode(right || "");
  let mismatch = a.length ^ b.length;
  const length = Math.max(a.length, b.length);
  for (let i = 0; i < length; i += 1) mismatch |= (a[i] || 0) ^ (b[i] || 0);
  return mismatch === 0;
}

async function validMetaSignature(raw, signature, secret) {
  if (!secret || !signature?.startsWith("sha256=")) return false;
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const digest = await crypto.subtle.sign("HMAC", key, raw);
  const hex = [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
  return sameString(`sha256=${hex}`, signature);
}

/** Nome del contatto, se il token della pagina ha i permessi. Senza, si prosegue anonimi. */
async function profileName(senderId, tenant, env, fetchImpl = fetch) {
  try {
    const response = await fetchImpl(
      `https://graph.facebook.com/${env.META_GRAPH_VERSION}/${encodeURIComponent(senderId)}?fields=name`,
      { headers: { Authorization: `Bearer ${tenant.access_token}` } },
    );
    if (!response.ok) return "";
    const profile = await response.json();
    return String(profile?.name || "").slice(0, 255);
  } catch {
    return "";
  }
}

async function webhook(request, env) {
  if (request.method === "GET") {
    const url = new URL(request.url);
    if (url.searchParams.get("hub.mode") === "subscribe" && sameString(url.searchParams.get("hub.verify_token"), env.META_VERIFY_TOKEN)) {
      return new Response(url.searchParams.get("hub.challenge") || "", { status: 200 });
    }
    return new Response("Verification failed", { status: 403 });
  }
  const raw = await request.arrayBuffer();
  if (!(await validMetaSignature(raw, request.headers.get("x-hub-signature-256"), env.META_APP_SECRET))) {
    return new Response("Invalid signature", { status: 401 });
  }
  const payload = JSON.parse(new TextDecoder().decode(raw));
  const platform = platformOf(payload.object);
  if (!platform) return Response.json({ ok: true, ignored: "object" });

  for (const entry of payload.entry || []) {
    const tenant = tenantFromEntry(env.META_TENANTS_JSON, entry.id, platform);
    if (!tenant) continue;
    for (const event of entry.messaging || []) {
      const message = normalizeEvent(event);
      if (!message) continue;
      // i byte li scarichiamo qui: il backend riceve solo allegati già verificati
      const { attachments, skipped } = await collectAttachments(message.attachments);
      const text = [message.text, skippedNote(skipped)].filter(Boolean).join("\n");
      if (!text && !attachments.length) continue;
      const response = await fetch(`${env.BACKEND_URL.replace(/\/$/, "")}/channels/meta/inbound`, {
        method: "POST",
        headers: { Authorization: `Bearer ${tenant.channel_api_key}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          platform,
          sender_id: message.senderId,
          sender_name: await profileName(message.senderId, tenant, env),
          text,
          message_id: message.messageId,
          ...(attachments.length ? { attachments } : {}),
        }),
      });
      if (!response.ok) throw new Error(`Backend Meta adapter ${response.status}: ${(await response.text()).slice(0, 300)}`);
    }
  }
  return Response.json({ ok: true });
}

async function outbound(request, env) {
  if (!sameString(request.headers.get("authorization"), `Bearer ${env.OUTBOUND_TOKEN}`)) {
    return new Response("Unauthorized", { status: 401 });
  }
  const payload = await request.json();
  const platform = payload.platform === "instagram" ? "instagram" : "messenger";
  const tenant = tenantConfig(env.META_TENANTS_JSON, payload.client_id);
  const from = sendingId(tenant, platform);
  if (!tenant?.access_token || !from) return new Response("Tenant not configured", { status: 404 });
  let body;
  try {
    body = graphPayload(payload);
  } catch {
    return new Response("Invalid outbound payload", { status: 400 });
  }
  const response = await fetch(`https://graph.facebook.com/${env.META_GRAPH_VERSION}/${from}/messages`, {
    method: "POST",
    headers: { Authorization: `Bearer ${tenant.access_token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) return new Response((await response.text()).slice(0, 1000), { status: response.status });
  return Response.json({ ok: true, provider: await response.json() });
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (path === "/webhook" && (request.method === "GET" || request.method === "POST")) return webhook(request, env);
    if (path === "/send" && request.method === "POST") return outbound(request, env);
    if (path === "/health" && request.method === "GET") return Response.json({ ok: true });
    return new Response("Not found", { status: 404 });
  },
};

export { profileName, sameString, validMetaSignature };
