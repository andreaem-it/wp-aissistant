import test from "node:test";
import assert from "node:assert/strict";
import {
  collectAttachments, fetchMedia, isMetaMediaUrl, mediaDescriptor, mediaFilename, toBase64,
} from "../src/media.js";
import { inboundBody } from "../src/protocol.js";

const OPTIONS = { token: "tenant-secret", graphVersion: "v21.0" };

function graph({ mime = "image/jpeg", size = 1024, url = "https://scontent.fbcdn.net/file", bytes = new Uint8Array([1, 2, 3]) } = {}) {
  const calls = [];
  const fetchImpl = async (target, init) => {
    calls.push({ url: String(target), auth: init?.headers?.Authorization });
    if (String(target).startsWith("https://graph.facebook.com/")) {
      return new Response(JSON.stringify({ mime_type: mime, file_size: size, url }), { status: 200 });
    }
    return new Response(bytes, { status: 200 });
  };
  return { calls, fetchImpl };
}

test("riconosce i media e ne deriva il nome file", () => {
  assert.equal(mediaDescriptor({ type: "text", text: { body: "ciao" } }), null);
  assert.equal(mediaDescriptor({ type: "image", image: {} }), null);
  const descriptor = mediaDescriptor({ type: "image", image: { id: "media-1", caption: "Il danno" } });
  assert.deepEqual(descriptor, { id: "media-1", filename: "", caption: "Il danno", kind: "image" });
  assert.equal(mediaFilename(descriptor, "image/jpeg"), "image-media-1.jpg");
  assert.equal(mediaFilename({ ...descriptor, filename: "scheda.pdf" }, "application/pdf"), "scheda.pdf");
});

test("accetta solo URL di media Meta in HTTPS", () => {
  assert.equal(isMetaMediaUrl("https://scontent.fbcdn.net/v/file.jpg"), true);
  assert.equal(isMetaMediaUrl("https://lookaside.fbsbx.com/file"), true);
  assert.equal(isMetaMediaUrl("http://scontent.fbcdn.net/file"), false);
  assert.equal(isMetaMediaUrl("https://attacker.example/file"), false);
  // un host che finge di essere Meta come sottodominio non deve passare
  assert.equal(isMetaMediaUrl("https://fbcdn.net.attacker.example/file"), false);
  assert.equal(isMetaMediaUrl(""), false);
});

test("scarica il media e non manda mai il token fuori dagli host Meta", async () => {
  const { calls, fetchImpl } = graph();
  const media = await fetchMedia(mediaDescriptor({ type: "image", image: { id: "media-1" } }), { ...OPTIONS, fetchImpl });
  assert.deepEqual(media, { filename: "image-media-1.jpg", content_type: "image/jpeg", data: toBase64(new Uint8Array([1, 2, 3])) });
  assert.equal(calls.length, 2);
  assert.ok(calls.every((call) => call.auth === "Bearer tenant-secret"));
  assert.ok(calls.every((call) => new URL(call.url).hostname.endsWith("facebook.com") || new URL(call.url).hostname.endsWith("fbcdn.net")));
});

test("scarta i media che il backend rifiuterebbe invece di inviarli", async () => {
  const descriptor = mediaDescriptor({ type: "document", document: { id: "media-2" } });
  for (const attempt of [
    graph({ mime: "image/svg+xml" }),                          // formato pericoloso
    graph({ size: 11 * 1024 * 1024 }),                         // oltre il limite per file
    graph({ url: "https://attacker.example/steal" }),          // URL fuori dagli host Meta
  ]) {
    assert.equal(await fetchMedia(descriptor, { ...OPTIONS, fetchImpl: attempt.fetchImpl }), null);
  }
  // l'URL non attendibile non deve nemmeno essere chiamato: il token non esce
  const blocked = graph({ url: "https://attacker.example/steal" });
  await fetchMedia(descriptor, { ...OPTIONS, fetchImpl: blocked.fetchImpl });
  assert.equal(blocked.calls.length, 1);
});

test("un errore di rete non fa perdere il messaggio", async () => {
  const failing = async () => {
    throw new Error("network down");
  };
  const result = await collectAttachments([mediaDescriptor({ type: "image", image: { id: "media-3" } })], {
    ...OPTIONS, fetchImpl: failing,
  });
  assert.deepEqual(result, { attachments: [], skipped: 1 });
});

test("tronca ai limiti del backend invece di far rifiutare tutto il messaggio", async () => {
  const { fetchImpl } = graph();
  const many = Array.from({ length: 7 }, (_unused, index) =>
    mediaDescriptor({ type: "image", image: { id: `media-${index}` } }));
  const result = await collectAttachments(many, { ...OPTIONS, fetchImpl });
  assert.equal(result.attachments.length, 5);
  assert.equal(result.skipped, 2);
});

test("il testo inoltrato dipende da cosa è stato davvero allegato", () => {
  const message = { type: "image", image: { id: "media-1", caption: "Il danno" } };
  assert.equal(inboundBody(message, { delivered: 1 }), "Il danno");
  // senza file resta l'etichetta: l'operatore deve sapere che c'era un'immagine
  assert.equal(inboundBody(message, { delivered: 0 }), "[Immagine allegata: Il danno]");
  assert.equal(inboundBody({ type: "text", text: { body: "Ciao" } }, { delivered: 0 }), "Ciao");
});
