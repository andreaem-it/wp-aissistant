import test from "node:test";
import assert from "node:assert/strict";
import worker, { sameString, validMetaSignature } from "../src/index.js";

const TENANTS = JSON.stringify({
  4: { page_id: "page-1", instagram_id: "ig-1", access_token: "page-secret", channel_api_key: "key-4" },
});

const ENV = {
  BACKEND_URL: "https://backend.example/",
  META_GRAPH_VERSION: "v21.0",
  META_APP_SECRET: "app-secret",
  META_VERIFY_TOKEN: "verify-me",
  OUTBOUND_TOKEN: "outbound-secret",
  META_TENANTS_JSON: TENANTS,
};

async function signature(body, secret) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const digest = await crypto.subtle.sign("HMAC", key, body);
  return `sha256=${[...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("")}`;
}

async function post(payload, { secret = "app-secret" } = {}) {
  const body = new TextEncoder().encode(JSON.stringify(payload));
  return new Request("https://worker.example/webhook", {
    method: "POST",
    headers: { "x-hub-signature-256": await signature(body, secret), "content-type": "application/json" },
    body,
  });
}

function stubFetch(calls, { profile = "Mario Rossi" } = {}) {
  return async (url, init) => {
    const target = String(url);
    calls.push({ url: target, init });
    if (target.startsWith("https://graph.facebook.com/") && target.includes("fields=name")) {
      return new Response(JSON.stringify({ name: profile }), { status: 200 });
    }
    if (target.startsWith("https://graph.facebook.com/")) return new Response(JSON.stringify({ message_id: "mid.out" }), { status: 200 });
    return new Response(JSON.stringify({ ok: true, created: true, conversation_id: 1 }), { status: 200 });
  };
}

test("confronta i segreti senza uscita anticipata", () => {
  assert.equal(sameString("secret", "secret"), true);
  assert.equal(sameString("secret", "secrex"), false);
  assert.equal(sameString("short", "longer"), false);
});

test("valida la firma HMAC del webhook Meta", async () => {
  const body = new TextEncoder().encode('{"entry":[]}');
  const signed = await signature(body, "app-secret");
  assert.equal(await validMetaSignature(body, signed, "app-secret"), true);
  assert.equal(await validMetaSignature(body, signed, "altro-secret"), false);
  assert.equal(await validMetaSignature(body, "", "app-secret"), false);
});

test("risponde alla verifica della sottoscrizione solo con il token giusto", async () => {
  const ok = await worker.fetch(
    new Request("https://worker.example/webhook?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=123"), ENV,
  );
  assert.equal(ok.status, 200);
  assert.equal(await ok.text(), "123");
  const ko = await worker.fetch(
    new Request("https://worker.example/webhook?hub.mode=subscribe&hub.verify_token=sbagliato&hub.challenge=123"), ENV,
  );
  assert.equal(ko.status, 403);
});

test("rifiuta un webhook non firmato", async () => {
  const request = await post({ object: "page", entry: [] }, { secret: "secret-di-un-altro" });
  const response = await worker.fetch(request, ENV);
  assert.equal(response.status, 401);
});

test("inoltra un messaggio Instagram al tenant giusto", async () => {
  const calls = [];
  globalThis.fetch = stubFetch(calls);
  const request = await post({
    object: "instagram",
    entry: [{ id: "ig-1", messaging: [{ sender: { id: "igsid-1" }, message: { mid: "mid.1", text: "Avete la taglia M?" } }] }],
  });
  const response = await worker.fetch(request, ENV);
  assert.equal(response.status, 200);

  const inbound = calls.find((call) => call.url === "https://backend.example/channels/meta/inbound");
  assert.ok(inbound, "il backend deve ricevere il messaggio");
  assert.equal(inbound.init.headers.Authorization, "Bearer key-4");
  assert.deepEqual(JSON.parse(inbound.init.body), {
    platform: "instagram", sender_id: "igsid-1", sender_name: "Mario Rossi",
    text: "Avete la taglia M?", message_id: "mid.1",
  });
});

test("una pagina non mappata non raggiunge nessun tenant", async () => {
  const calls = [];
  globalThis.fetch = stubFetch(calls);
  const request = await post({
    object: "page",
    entry: [{ id: "pagina-di-un-altro", messaging: [{ sender: { id: "psid-9" }, message: { mid: "mid.9", text: "Ciao" } }] }],
  });
  assert.equal((await worker.fetch(request, ENV)).status, 200);
  assert.deepEqual(calls, []);
});

test("l'invio richiede il token dell'outbound e un tenant configurato", async () => {
  const calls = [];
  globalThis.fetch = stubFetch(calls);
  const unauthorized = await worker.fetch(
    new Request("https://worker.example/send", { method: "POST", headers: { authorization: "Bearer sbagliato" }, body: "{}" }),
    ENV,
  );
  assert.equal(unauthorized.status, 401);
  assert.deepEqual(calls, []);

  const unknownTenant = await worker.fetch(
    new Request("https://worker.example/send", {
      method: "POST",
      headers: { authorization: "Bearer outbound-secret", "content-type": "application/json" },
      body: JSON.stringify({ client_id: 99, platform: "messenger", recipient_id: "psid-1", text: "Ciao" }),
    }),
    ENV,
  );
  assert.equal(unknownTenant.status, 404);

  const sent = await worker.fetch(
    new Request("https://worker.example/send", {
      method: "POST",
      headers: { authorization: "Bearer outbound-secret", "content-type": "application/json" },
      body: JSON.stringify({ client_id: 4, platform: "instagram", recipient_id: "igsid-1", text: "Sì, disponibile" }),
    }),
    ENV,
  );
  assert.equal(sent.status, 200);
  const graph = calls.at(-1);
  assert.equal(graph.url, "https://graph.facebook.com/v21.0/ig-1/messages");
  assert.equal(graph.init.headers.Authorization, "Bearer page-secret");
  assert.deepEqual(JSON.parse(graph.init.body), {
    recipient: { id: "igsid-1" }, messaging_type: "RESPONSE", message: { text: "Sì, disponibile" },
  });
});
