import test from "node:test";
import assert from "node:assert/strict";
import worker, { sameString } from "../src/index.js";

const env = {
  ADAPTER_TOKEN: "backend-secret",
  CRM_TENANTS_JSON: JSON.stringify({ 7: { hubspot: { account_id: "portal-1", access_token: "provider-secret" } } }),
  HUBSPOT_API_VERSION: "2026-03",
};

test("health is public but sync requires the backend secret", async () => {
  assert.equal((await worker.fetch(new Request("https://worker/health"), env)).status, 200);
  assert.equal((await worker.fetch(new Request("https://worker/sync", { method: "POST", body: "{}" }), env)).status, 401);
  assert.equal(sameString("secret", "secret"), true);
  assert.equal(sameString("secret", "secrex"), false);
});

test("rejects cross-tenant account mapping before provider calls", async () => {
  const response = await worker.fetch(new Request("https://worker/sync", {
    method: "POST",
    headers: { Authorization: "Bearer backend-secret", "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: 8, provider: "hubspot", external_account_id: "portal-1",
      lead: { data: { email: "anna@example.it" } },
    }),
  }), env);
  assert.equal(response.status, 404);
});

test("upserts HubSpot contacts and never forwards the adapter secret", async (t) => {
  const originalFetch = globalThis.fetch;
  let captured;
  globalThis.fetch = async (url, options) => {
    captured = { url, options };
    return new Response(JSON.stringify({ results: [{ id: "contact-9" }] }), { status: 200 });
  };
  t.after(() => { globalThis.fetch = originalFetch; });
  const response = await worker.fetch(new Request("https://worker/sync", {
    method: "POST",
    headers: { Authorization: "Bearer backend-secret", "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: 7, provider: "hubspot", external_account_id: "portal-1",
      lead: { data: { nome: "Anna Verdi", email: "anna@example.it" } },
    }),
  }), env);
  assert.deepEqual(await response.json(), { ok: true, external_id: "contact-9" });
  assert.match(captured.url, /2026-03\/contacts\/batch\/upsert$/);
  assert.equal(captured.options.headers.Authorization, "Bearer provider-secret");
  assert.doesNotMatch(captured.options.body, /backend-secret|provider-secret/);
});
