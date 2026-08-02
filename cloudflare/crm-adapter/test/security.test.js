import test from "node:test";
import assert from "node:assert/strict";
import worker, { sameString } from "../src/index.js";

const env = {
  ADAPTER_TOKEN: "backend-secret",
  CRM_TENANTS_JSON: JSON.stringify({ 7: { brevo: { account_id: "account-1", access_token: "provider-secret" } } }),
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
      client_id: 8, provider: "brevo", external_account_id: "account-1",
      lead: { data: { email: "anna@example.it" } },
    }),
  }), env);
  assert.equal(response.status, 404);
});

test("upserts Brevo contacts and never forwards the adapter secret", async (t) => {
  const originalFetch = globalThis.fetch;
  let captured;
  globalThis.fetch = async (url, options) => {
    captured = { url, options };
    return new Response(JSON.stringify({ id: 9 }), { status: 201 });
  };
  t.after(() => { globalThis.fetch = originalFetch; });
  const response = await worker.fetch(new Request("https://worker/sync", {
    method: "POST",
    headers: { Authorization: "Bearer backend-secret", "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: 7, provider: "brevo", external_account_id: "account-1",
      lead: { data: { nome: "Anna Verdi", email: "anna@example.it" } },
    }),
  }), env);
  assert.deepEqual(await response.json(), { ok: true, external_id: "9" });
  assert.equal(captured.url, "https://api.brevo.com/v3/contacts");
  assert.equal(captured.options.headers["api-key"], "provider-secret");
  assert.doesNotMatch(captured.options.body, /backend-secret|provider-secret/);
});

test("upserts Zoho contacts in the European data center", async (t) => {
  const originalFetch = globalThis.fetch;
  let captured;
  globalThis.fetch = async (url, options) => {
    captured = { url, options };
    return new Response(JSON.stringify({ data: [{ details: { id: "zoho-42" } }] }), { status: 200 });
  };
  t.after(() => { globalThis.fetch = originalFetch; });
  const zohoEnv = {
    ...env,
    CRM_TENANTS_JSON: JSON.stringify({ 7: { zoho: {
      account_id: "org-1", access_token: "zoho-secret", api_domain: "https://www.zohoapis.eu",
    } } }),
  };
  const response = await worker.fetch(new Request("https://worker/sync", {
    method: "POST",
    headers: { Authorization: "Bearer backend-secret", "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: 7, provider: "zoho", external_account_id: "org-1",
      lead: { data: { nome: "Anna Verdi", email: "anna@example.it" } },
    }),
  }), zohoEnv);
  assert.deepEqual(await response.json(), { ok: true, external_id: "zoho-42" });
  assert.equal(captured.url, "https://www.zohoapis.eu/crm/v8/Contacts/upsert");
  assert.equal(captured.options.headers.Authorization, "Zoho-oauthtoken zoho-secret");
});
