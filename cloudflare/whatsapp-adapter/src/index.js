import { graphPayload, inboundBody, tenantConfig, tenantFromPhone } from "./protocol.js";
import { collectAttachments, mediaDescriptor } from "./media.js";

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
  for (const entry of payload.entry || []) {
    for (const change of entry.changes || []) {
      const value = change.value || {};
      const tenant = tenantFromPhone(env.META_TENANTS_JSON, value.metadata?.phone_number_id);
      if (!tenant) continue;
      const names = new Map((value.contacts || []).map((contact) => [contact.wa_id, contact.profile?.name || ""]));
      for (const message of value.messages || []) {
        if (!message.id || !message.from) continue;
        const descriptor = mediaDescriptor(message);
        // i byte li scarichiamo qui con il token del tenant: il backend non vede mai Meta
        const { attachments } = descriptor
          ? await collectAttachments([descriptor], {
              token: tenant.access_token,
              graphVersion: env.META_GRAPH_VERSION,
            })
          : { attachments: [] };
        const text = inboundBody(message, { delivered: attachments.length });
        if (!text && !attachments.length) continue;
        const response = await fetch(`${env.BACKEND_URL.replace(/\/$/, "")}/channels/whatsapp/inbound`, {
          method: "POST",
          headers: { Authorization: `Bearer ${tenant.channel_api_key}`, "Content-Type": "application/json" },
          body: JSON.stringify({
            from_number: `+${String(message.from).replace(/^\+/, "")}`,
            from_name: names.get(message.from) || "",
            text,
            message_id: message.id,
            ...(attachments.length ? { attachments } : {}),
          }),
        });
        if (!response.ok) throw new Error(`Backend WhatsApp adapter ${response.status}: ${(await response.text()).slice(0, 300)}`);
      }
    }
  }
  return Response.json({ ok: true });
}

async function outbound(request, env) {
  if (!sameString(request.headers.get("authorization"), `Bearer ${env.OUTBOUND_TOKEN}`)) {
    return new Response("Unauthorized", { status: 401 });
  }
  const payload = await request.json();
  const tenant = tenantConfig(env.META_TENANTS_JSON, payload.client_id);
  if (!tenant?.phone_number_id || !tenant?.access_token) return new Response("Tenant not configured", { status: 404 });
  const response = await fetch(
    `https://graph.facebook.com/${env.META_GRAPH_VERSION}/${tenant.phone_number_id}/messages`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${tenant.access_token}`, "Content-Type": "application/json" },
      body: JSON.stringify(graphPayload(payload)),
    },
  );
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

export { sameString, validMetaSignature };
