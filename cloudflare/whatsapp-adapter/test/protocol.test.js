import test from "node:test";
import assert from "node:assert/strict";
import { graphPayload, inboundText, tenantConfig, tenantFromPhone } from "../src/protocol.js";

const tenants = JSON.stringify({ 4: { phone_number_id: "phone-1", access_token: "secret", channel_api_key: "key" } });

test("maps tenant in both directions", () => {
  assert.equal(tenantConfig(tenants, 4).phone_number_id, "phone-1");
  assert.equal(tenantFromPhone(tenants, "phone-1").clientId, 4);
  assert.equal(tenantFromPhone(tenants, "missing"), null);
});

test("normalizes inbound text, interactions and media captions", () => {
  assert.equal(inboundText({ type: "text", text: { body: " Ciao " } }), "Ciao");
  assert.equal(inboundText({ type: "interactive", interactive: { button_reply: { title: "Conferma" } } }), "Conferma");
  assert.equal(inboundText({ type: "image", image: { id: "media-1", caption: "Foto danno" } }), "[Immagine allegata: Foto danno]");
  assert.equal(inboundText({ type: "location", location: {} }), "");
});

test("builds Meta text payload with reply context", () => {
  assert.deepEqual(graphPayload({ type: "text", to: "39333", text: "Ciao", reply_to_message_id: "wamid.1" }), {
    messaging_product: "whatsapp", recipient_type: "individual", to: "39333", type: "text",
    text: { preview_url: false, body: "Ciao" }, context: { message_id: "wamid.1" },
  });
});

test("builds Meta template body parameters", () => {
  const payload = graphPayload({ type: "template", to: "39333", template: "ordine", language: "it", parameters: ["Mario", "123"] });
  assert.equal(payload.template.name, "ordine");
  assert.deepEqual(payload.template.components[0].parameters, [{ type: "text", text: "Mario" }, { type: "text", text: "123" }]);
});
