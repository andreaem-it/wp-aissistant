import test from "node:test";
import assert from "node:assert/strict";
import {
  graphPayload, normalizeEvent, platformOf, sendingId, tenantConfig, tenantFromEntry,
} from "../src/protocol.js";

const TENANTS = JSON.stringify({
  4: { page_id: "page-1", instagram_id: "ig-1", access_token: "secret", channel_api_key: "key-4" },
  9: { page_id: "page-9", access_token: "secret-9", channel_api_key: "key-9" },
});

test("riconosce la piattaforma dall'oggetto del webhook", () => {
  assert.equal(platformOf("page"), "messenger");
  assert.equal(platformOf("instagram"), "instagram");
  assert.equal(platformOf("whatsapp_business_account"), "");
});

test("mappa il tenant dalla pagina o dall'account Instagram", () => {
  assert.equal(tenantFromEntry(TENANTS, "page-1", "messenger").clientId, 4);
  assert.equal(tenantFromEntry(TENANTS, "ig-1", "instagram").clientId, 4);
  // la pagina di un tenant non deve valere come account Instagram di nessuno
  assert.equal(tenantFromEntry(TENANTS, "page-1", "instagram"), null);
  assert.equal(tenantFromEntry(TENANTS, "page-9", "instagram"), null);
  assert.equal(tenantFromEntry(TENANTS, "sconosciuta", "messenger"), null);
  assert.equal(tenantConfig(TENANTS, 9).page_id, "page-9");
  assert.equal(tenantConfig(TENANTS, 99), null);
});

test("sceglie la risorsa Graph su cui inviare", () => {
  const tenant = tenantConfig(TENANTS, 4);
  assert.equal(sendingId(tenant, "messenger"), "page-1");
  assert.equal(sendingId(tenant, "instagram"), "ig-1");
  assert.equal(sendingId(tenantConfig(TENANTS, 9), "instagram"), "");
});

test("normalizza un messaggio di testo", () => {
  const event = { sender: { id: "psid-1" }, message: { mid: "mid.1", text: "  Ciao  " } };
  assert.deepEqual(normalizeEvent(event), {
    senderId: "psid-1", messageId: "mid.1", text: "Ciao", attachments: [],
  });
});

test("ignora gli echo dei nostri stessi invii", () => {
  const echo = { sender: { id: "page-1" }, message: { mid: "mid.2", text: "Risposta operatore", is_echo: true } };
  assert.equal(normalizeEvent(echo), null);
});

test("ignora consegne, letture e reazioni", () => {
  assert.equal(normalizeEvent({ sender: { id: "psid-1" }, delivery: { mids: ["mid.1"] } }), null);
  assert.equal(normalizeEvent({ sender: { id: "psid-1" }, read: { watermark: 1 } }), null);
  assert.equal(normalizeEvent({ message: { mid: "mid.3", text: "senza mittente" } }), null);
  assert.equal(normalizeEvent({ sender: { id: "psid-1" }, message: { text: "senza mid" } }), null);
});

test("tiene solo gli allegati che sono contenuto del cliente", () => {
  const event = {
    sender: { id: "psid-1" },
    message: {
      mid: "mid.4",
      text: "",
      attachments: [
        { type: "image", payload: { url: "https://scontent.xx.fbcdn.net/foto.jpg" } },
        { type: "fallback", payload: { url: "https://example.com/articolo" } },
        { type: "template", payload: {} },
        { type: "file", payload: { url: "https://cdninstagram.com/doc.pdf" } },
      ],
    },
  };
  assert.deepEqual(normalizeEvent(event).attachments, [
    { type: "image", url: "https://scontent.xx.fbcdn.net/foto.jpg" },
    { type: "file", url: "https://cdninstagram.com/doc.pdf" },
  ]);
});

test("un postback diventa un messaggio con id stabile fra i retry", () => {
  const event = { sender: { id: "psid-1" }, timestamp: 1700, postback: { title: "Parla con un operatore", payload: "HUMAN" } };
  const first = normalizeEvent(event);
  assert.deepEqual(first, {
    senderId: "psid-1", messageId: "postback:psid-1:1700", text: "Parla con un operatore", attachments: [],
  });
  assert.deepEqual(normalizeEvent(event), first);
  assert.equal(normalizeEvent({ sender: { id: "psid-1" }, postback: {} }), null);
});

test("costruisce il payload della Send API", () => {
  assert.deepEqual(graphPayload({ recipient_id: "psid-1", text: "Come possiamo aiutarti?" }), {
    recipient: { id: "psid-1" }, messaging_type: "RESPONSE", message: { text: "Come possiamo aiutarti?" },
  });
  assert.throws(() => graphPayload({ recipient_id: "psid-1", text: "   " }));
  assert.throws(() => graphPayload({ text: "Ciao" }));
});
