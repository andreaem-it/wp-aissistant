import test from "node:test";
import assert from "node:assert/strict";
import { createClient, WpAissistantError } from "../src/index.js";

function storage() { const data = new Map(); return { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, String(v)), removeItem: (k) => data.delete(k) }; }
function response(payload, status = 200) { return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } }); }

test("requires HTTPS outside local development", () => {
  assert.throws(() => createClient({ apiBase: "http://example.com", apiKey: "key" }), /HTTPS/);
  assert.doesNotThrow(() => createClient({ apiBase: "http://localhost:8000", apiKey: "key" }));
});

test("persists and resumes a conversation without leaking its token into the URL", async () => {
  const calls = []; const store = storage();
  const client = createClient({ apiBase: "https://backend.example", apiKey: "public-key", storage: store, fetchImpl: async (url, options) => {
    calls.push({ url: String(url), options, body: options.body ? JSON.parse(options.body) : null });
    return response({ conversation_id: 12, conversation_token: "private-token", status: "open", reply: "Ciao" });
  } });
  await client.send("Ciao", { locale: "it-IT", siteUrl: "https://shop.example/prodotto" }); await client.send("Ancora");
  assert.equal(client.session.conversationId, 12); assert.equal(calls[1].body.conversation_token, "private-token");
  assert.doesNotMatch(calls[1].url, /private-token|public-key/); assert.equal(calls[0].options.headers.Authorization, "Bearer public-key");
});

test("polls messages with the private token header", async () => {
  const store = storage(); store.setItem("wpai_sdk:conversation", "4"); store.setItem("wpai_sdk:token", "conv-secret"); let call;
  const client = createClient({ apiBase: "https://backend.example", apiKey: "key", storage: store, fetchImpl: async (url, options) => { call = { url: String(url), options }; return response({ status: "open", messages: [] }); } });
  await client.messages({ afterId: 9, limit: 20 }); assert.match(call.url, /after_id=9&limit=20/); assert.equal(call.options.headers["X-Conversation-Token"], "conv-secret");
});

test("requires an active conversation for protected actions", () => {
  const client = createClient({ apiBase: "https://backend.example", apiKey: "key", storage: storage(), fetchImpl: async () => response({}) });
  assert.throws(() => client.rating(5), WpAissistantError);
});

test("surfaces safe API errors", async () => {
  const client = createClient({ apiBase: "https://backend.example", apiKey: "key", storage: storage(), fetchImpl: async () => response({ detail: "rate limited" }, 429) });
  await assert.rejects(() => client.leadForm(), (error) => error.status === 429 && error.message === "rate limited");
});

test("streams SSE events split across network chunks and remembers the session", async () => {
  const store = storage();
  const encoder = new TextEncoder();
  const body = new ReadableStream({ start(controller) {
    controller.enqueue(encoder.encode('data: {"type":"start","conversation_id":8,"conversation_token":"tok'));
    controller.enqueue(encoder.encode('en"}\n\ndata: {"type":"token","text":"Ciao"}\n\ndata: {"type":"done","conversation_id":8}\n\n'));
    controller.close();
  } });
  const client = createClient({ apiBase: "https://backend.example", apiKey: "key", storage: store, fetchImpl: async () => new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }) });
  const events = [];
  for await (const event of client.stream("Ciao")) events.push(event);
  assert.deepEqual(events.map((event) => event.type), ["start", "token", "done"]);
  assert.equal(client.session.conversationId, 8); assert.equal(client.session.conversationToken, "token");
});
