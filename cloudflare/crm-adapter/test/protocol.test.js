import test from "node:test";
import assert from "node:assert/strict";
import { brevoUpsert, contactFields, pipedrivePerson, tenantProvider, zohoUpsert } from "../src/protocol.js";

test("matches tenant, provider and account as one security boundary", () => {
  const raw = JSON.stringify({ 7: { brevo: { account_id: "account-1", access_token: "secret" } } });
  assert.equal(tenantProvider(raw, 7, "brevo", "account-1").access_token, "secret");
  assert.equal(tenantProvider(raw, 8, "brevo", "account-1"), null);
  assert.equal(tenantProvider(raw, 7, "brevo", "account-2"), null);
  assert.equal(tenantProvider("bad json", 7, "brevo", "account-1"), null);
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
  assert.deepEqual(brevoUpsert(fields), {
    email: "a@example.it", attributes: { FIRSTNAME: "Anna" }, updateEnabled: true,
  });
  assert.deepEqual(zohoUpsert(fields), {
    data: [{ Email: "a@example.it", Last_Name: "Anna", First_Name: "Anna" }],
    duplicate_check_fields: ["Email"],
  });
  assert.deepEqual(pipedrivePerson(fields), {
    name: "Anna", emails: [{ value: "a@example.it", primary: true, label: "work" }],
  });
});
