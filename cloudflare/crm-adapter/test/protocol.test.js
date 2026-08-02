import test from "node:test";
import assert from "node:assert/strict";
import { contactFields, hubspotUpsert, pipedrivePerson, tenantProvider } from "../src/protocol.js";

test("matches tenant, provider and account as one security boundary", () => {
  const raw = JSON.stringify({ 7: { hubspot: { account_id: "portal-1", access_token: "secret" } } });
  assert.equal(tenantProvider(raw, 7, "hubspot", "portal-1").access_token, "secret");
  assert.equal(tenantProvider(raw, 8, "hubspot", "portal-1"), null);
  assert.equal(tenantProvider(raw, 7, "hubspot", "portal-2"), null);
  assert.equal(tenantProvider("bad json", 7, "hubspot", "portal-1"), null);
});

test("maps common Italian and English lead fields", () => {
  assert.deepEqual(contactFields({ data: {
    nome: "Anna Verdi", email: "anna@example.it", telefono: "+39 333", azienda: "Acme",
  } }), {
    email: "anna@example.it", firstname: "Anna", lastname: "Verdi", phone: "+39 333", company: "Acme",
  });
  assert.throws(() => contactFields({ data: { nome: "Anna" } }), /valid email/);
});

test("builds provider payloads without internal metadata", () => {
  const fields = { email: "a@example.it", firstname: "Anna", lastname: "", phone: "", company: "" };
  assert.deepEqual(hubspotUpsert(fields), { inputs: [{
    idProperty: "email", id: "a@example.it", properties: { email: "a@example.it", firstname: "Anna" },
  }] });
  assert.deepEqual(pipedrivePerson(fields), {
    name: "Anna", emails: [{ value: "a@example.it", primary: true, label: "work" }],
  });
});
